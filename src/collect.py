"""采集层：RSS + 网页列表，支持条件请求（ETag / Last-Modified）

只做抓取与解析，不做任何判断。
304 表示内容未变，不消耗流量、不判定、不报警。
"""
import re
import html as htmlmod
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}


def _cond_headers(etag=None, last_modified=None):
    h = dict(HEADERS)
    if etag:
        h["If-None-Match"] = etag
    if last_modified:
        h["If-Modified-Since"] = last_modified
    return h


def _clean(text):
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = htmlmod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(raw):
    if not raw:
        return None
    raw = raw.strip()
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d", "%Y/%m/%d %H:%M", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            dt = datetime.strptime(raw[:len(fmt) + 6], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def parse_rss(content, limit=30):
    """从 RSS/Atom 字节解析出条目。"""
    root = ET.fromstring(content)
    items = []
    for node in root.iter():
        if node.tag.split("}")[-1] not in ("item", "entry"):
            continue
        d = {}
        for ch in node:
            tag = ch.tag.split("}")[-1]
            if tag not in ("title", "link", "description", "summary", "pubDate",
                           "published", "updated", "content", "encoded"):
                continue
            val = ch.text or ""
            if tag == "link" and not val:
                val = ch.attrib.get("href", "")
            if not d.get(tag):
                d[tag] = val
        title = _clean(d.get("title"))
        url = (d.get("link") or "").strip()
        if not url or not title:
            continue
        summary = _clean(d.get("description") or d.get("summary") or
                         d.get("content") or d.get("encoded"))[:600]
        pub = _parse_date(d.get("pubDate") or d.get("published") or d.get("updated"))
        items.append({"title": title, "url": url, "summary": summary, "published": pub})
        if len(items) >= limit:
            break
    return items


def parse_web_list(src, text, limit=30):
    """按 src['pattern'] 匹配 href，抽出标题。

    src['must_match']（可选）：标题必须命中的正则。用于综合型列表页
    （新品频道/关键词检索页）——只留自家与核心竞对的条目，不把全站
    几十条无关内容送进评分，省 token 也压噪声。
    """
    pat = re.compile(src["pattern"])
    must = re.compile(src["must_match"]) if src.get("must_match") else None
    base = src.get("base", "")
    out, seen = [], set()
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', text, re.S):
        href, inner = m.group(1), m.group(2)
        if not pat.search(href):
            continue
        title = _clean(inner)
        if src.get("title_strip"):
            title = re.sub(src["title_strip"], "", title).strip()
        if not (8 <= len(title) <= 110):
            continue
        if must and not must.search(title):
            continue
        url = href if href.startswith("http") else base.rstrip("/") + "/" + href.lstrip("/")
        if url in seen:
            continue
        seen.add(url)
        out.append({"title": title, "url": url, "summary": "", "published": None})
        if len(out) >= limit:
            break
    return out


def collect_one(src, etag=None, last_modified=None, timeout=20):
    """抓一个源。

    返回 {ok, not_modified, source, count, items, etag, last_modified, ms, error?}
    """
    t0 = time.time()
    try:
        r = requests.get(src["url"], headers=_cond_headers(etag, last_modified),
                         timeout=timeout)
        if r.status_code == 304:
            return {"ok": True, "not_modified": True, "source": src["id"],
                    "count": 0, "items": [], "ms": int((time.time() - t0) * 1000)}
        r.raise_for_status()

        if src["kind"] == "rss":
            items = parse_rss(r.content)
            if src.get("must_match"):
                pat = re.compile(src["must_match"])
                items = [x for x in items if pat.search(x["title"]) or pat.search(x.get("summary") or "")]
        else:
            # 部分站点（如电子发烧友）响应头不带 charset，requests 会退回
            # ISO-8859-1，中文标题全成乱码。有 meta charset 时按内容猜。
            if "charset=" not in (r.headers.get("Content-Type") or "").lower():
                r.encoding = r.apparent_encoding or "utf-8"
            items = parse_web_list(src, r.text)

        for it in items:
            it["source_id"] = src["id"]
            it["source_name"] = src["name"]
            it["source_tier"] = src["tier"]

        return {"ok": True, "not_modified": False, "source": src["id"],
                "count": len(items), "items": items,
                "etag": r.headers.get("ETag"),
                "last_modified": r.headers.get("Last-Modified"),
                "ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"ok": False, "not_modified": False, "source": src["id"],
                "error": f"{type(e).__name__}: {e}", "count": 0, "items": [],
                "ms": int((time.time() - t0) * 1000)}


def collect_all(sources, verbose=True, use_cache=False):
    """全量抓取。use_cache=True 时带条件请求（突发轮询用）。

    源里 enabled=False 的直接跳过，告警也不计入失败——配置留占位模板时
    不该每天报一次抓取失败。
    """
    import state
    out = []
    for src in sources:
        if not src.get("enabled", True):
            if verbose:
                print(f"  [SKIP] {src.get('id'):16} 已禁用")
            continue
        etag = lm = None
        if use_cache:
            etag, lm = state.get_http(src["id"])
        res = collect_one(src, etag, lm)
        if res.get("ok") and not res.get("not_modified"):
            if use_cache and (res.get("etag") or res.get("last_modified")):
                state.set_http(src["id"], res.get("etag"), res.get("last_modified"))
        if verbose:
            if not res["ok"]:
                print(f"  [FAIL] {res['source']:16} {res['error'][:70]}")
            elif res.get("not_modified"):
                print(f"  [304]  {res['source']:16} 未变更")
            else:
                print(f"  [OK]   {res['source']:16} {res['count']:3d} 条  {res['ms']}ms")
        out.append(res)
    return out
