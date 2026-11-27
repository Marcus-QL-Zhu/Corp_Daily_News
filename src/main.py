"""主流水线

流程：采集 → 判重 → 判定 → 聚簇 → 排序 → 选 TOP5 → 招聘素材 → 写 MD → 发邮件

聚簇修正（关键）：字面相似度前先过「主体一致」硬门。
中文财经标题模板高度雷同（"XX发布2026三季报"），纯字面会把两家不相干的公司聚成一条。
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import analyze
import collect
import config
import dedup
import mail
import render
import state

BJ = timezone(timedelta(hours=8))
LINE_ORDER = ["battery", "power", "driver", "sensor", "link", "mcu"]


# ── 判重 ────────────────────────────────────────────────────────────────
def normalize_url(u):
    u = u.strip().lower()
    u = re.sub(r"[?#].*$", "", u)
    u = re.sub(r"^https?://(www\.)?", "", u)
    return u.rstrip("/")


def dedupe_url(items):
    seen, out = set(), []
    for it in items:
        k = normalize_url(it.get("url", ""))
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def date_from_url(u):
    """从 URL 里抠日期：/2026/2026-03-23-xxx 或 /20261124/ 或 archives/1795492801102(ms)"""
    if not u:
        return None
    m = re.search(r"/(20\d{2})[-/](\d{2})[-/](\d{2})", u)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=BJ)
        except Exception:
            return None
    m = re.search(r"/(20\d{2})(\d{2})(\d{2})", u)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=BJ)
        except Exception:
            return None
    m = re.search(r"archives/(\d{13})", u)
    if m:
        try:
            return datetime.fromtimestamp(int(m.group(1)) / 1000, BJ)
        except Exception:
            return None
    return None


def freshness_ok(it, days=3):
    """已知日期且超过 days 天 → 丢。未知日期 → 保留（网页列表拿不到时间）。

    无日期条目靠「跨天去重」兜底：URL 已刊出过就不进来（见 cross_day_filter）。
    """
    pub = it.get("published") or date_from_url(it.get("url"))
    if not pub:
        return True, None
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=BJ)
    age = (datetime.now(BJ) - pub).days
    return age <= days, pub


# ── 聚簇（带主体硬门）──────────────────────────────────────────────────
# 字面相似度、主体签名、同事件判定统一由 dedup 提供：突发通道（poll.py）
# 用的是同一套口径，否则日报和突发会对「是不是同一件事」给出不同答案。
bigrams = dedup.bigrams
lexical = dedup.lexical
subject_key = dedup.subject_key


def cluster(items, min_sim=0.55):
    """同事件聚簇。返回 clusters: [[item,...]]，每个 cluster 内已按代表性排序。"""
    clusters = []
    for it in items:
        placed = False
        for cl in clusters:
            head = cl[0]
            # 硬门：类型不能冲突得太狠（财报 vs 产品发布）—— 日报特有
            if it.get("type") == "财务经营" and head.get("type") == "产品发布":
                continue
            if dedup.same_event(subject_key(it), it["title_zh"],
                                subject_key(head), head["title_zh"],
                                min_sim=min_sim):
                cl.append(it)
                placed = True
                break
        if not placed:
            clusters.append([it])

    # 每个簇按「官方优先 → 分数 → 时间」选代表
    tier_rank = {"T1": 0, "T1_5": 1, "T2": 2}
    out = []
    for cl in clusters:
        cl.sort(key=lambda x: (tier_rank.get(x.get("source_tier"), 3),
                               -int(x.get("score") or 0)))
        rep = cl[0]
        rep["cluster_size"] = len(cl)
        rep["sources_all"] = sorted({x.get("source_name") for x in cl})
        out.append(rep)
    return out


# ── 当日孤儿清理 ────────────────────────────────────────────────────────
def gc_day_news(vault, day):
    """把当日「已落盘但未被日报引用」的新闻 MD 移入 .trash。

    write_news_md 是只写不删的，write_daily_md 是覆盖同一天的文件。
    同一天重跑而条目集合变了，上一轮的条目就留在盘上成为孤儿 ——
    Obsidian 的 Dataview 直接扫文件系统，孤儿会当成「当天新闻」被查出来，
    但它从未进过任何一期邮件。所以每次发刊成功后要对齐一次。
    """
    folder = os.path.join(vault, "30-News", day[:4], day[5:7])
    daily = os.path.join(vault, "10-Daily", day[:4], f"{day}.md")
    if not os.path.isdir(folder) or not os.path.exists(daily):
        return []
    with open(daily, encoding="utf-8") as f:
        refs = set(re.findall(r"\[\[(.+?)\]\]", f.read()))
    trash = os.path.join(vault, ".trash", "gc-" + day.replace("-", ""))
    moved = []
    for fn in sorted(os.listdir(folder)):
        if not fn.startswith(day) or not fn.endswith(".md"):
            continue
        if fn[:-3] in refs:
            continue
        os.makedirs(trash, exist_ok=True)
        os.rename(os.path.join(folder, fn), os.path.join(trash, fn))
        moved.append(fn)
    return moved


# ── 跨天去重（URL 硬门 + 同事件软门）──────────────────────────────────
def cross_day_filter(items, history, min_sim=0.55):
    """丢掉「过去 N 天已刊出过」的条目。

    两道门，命中任一即丢，无例外白名单：
      1. URL 硬门：url_key 出现在 daily_items（逐字相同，最可靠）
      2. 同事件软门：主体有交集 且 标题字面相似度高（换源/换标题重发）
    返回 (kept, dropped)。dropped 里的条目带 _dup_reason 供日志用。
    """
    hist_keys = {h["url_key"] for h in history if h.get("url_key")}
    kept, dropped = [], []
    for it in items:
        k = state.url_key(it.get("url"))
        if k and k in hist_keys:
            it["_dup_reason"] = "url"
            dropped.append(it)
            continue
        s_it = subject_key(it)
        hit = None
        for h in history:
            if s_it and h["subject"] and not (s_it & h["subject"]):
                continue
            if lexical(it.get("title_zh", ""), h["title"]) >= min_sim:
                hit = h
                break
        if hit:
            it["_dup_reason"] = f"event@{hit['day']}"
            dropped.append(it)
            continue
        kept.append(it)
    return kept, dropped


# ── 渠道上架稿门（2026-11-27）─────────────────────────────────────────
# 「贸泽开售 TI TRF2001」被判为「TI 竞对动作、50 分」入刊。但主体是分销商，
# 不是原厂：分销商上架对公司零情报价值。只看标题（不看摘要），避免误杀
# 那些正文顺带提到渠道的真新闻。
def distributor_listing(it):
    """标题主体是分销商 + 上架类动作 → 渠道稿，不入刊。"""
    t = it.get("title_zh") or it.get("title") or ""
    if not any(d in t for d in config.DISTRIBUTORS):
        return False
    return any(a in t for a in config.DISTRIBUTOR_ACTIONS)


# ── 政策实质门（2026-11-27）───────────────────────────────────────
# 「美国算力管制再升级东方算芯打造全国产供应链」判 55 分 impact=high 入刊，
# 全文只有「管制又升级了 + 某公司表示要国产化」两句表态，无新事实。
def policy_has_substance(it):
    """政策类条目必须能指到具体事实（数字/日期/条款/禁令），否则不入刊。"""
    if it.get("type") != "政策标准":
        return True
    text = " ".join([it.get("title_zh") or "", it.get("title") or "",
                     it.get("summary") or ""])
    return re.search(config.POLICY_FACT_RE, text) is not None


# ── 事实回填（2026-11-27）─────────────────────────────────────────
# 接续条目需要真事实才能当招聘谈资。两路回填，都失败才用标题兜底。
def _is_good_fact(s):
    """摘要能不能用：必须中文为主、不是截断残句。

    2026-11-27 踩过的坑：digitimes 的 og:description 是英文且被页面
    截在半句（「Taiwan has secured a place in the lowest tier of
    Washington」），直接当摘要会让整条新闻失去信息量，招聘素材也用不上。
    """
    s = (s or "").strip()
    if len(s) < 30:
        return False
    cjk = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    if cjk < len(s) * 0.3:          # 中文占比过低（英文稿）
        return False
    # 截断在句中的特征：结尾没有句末标点，且末尾是 English 词片断
    if not re.search(r"[。！？；\u201d\)）]$", s) and re.search(r"[A-Za-z]{1,}$", s):
        return False
    return True


def _fetch_fact(url, timeout=12):
    """从原文抓可用的事实摘要。优先 og:description，退而找正文中文段。"""
    if not url:
        return ""
    try:
        import requests
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return ""
        html = r.text

        # 1) og:description / description，取最长且合格的一条
        cands = re.findall(
            r'<meta[^>]+(?:name|property)=["\'](?:og:)?description["\'][^>]+'
            r'content=["\']([^"\']{20,})', html, re.I)
        for c in sorted(cands, key=len, reverse=True):
            c = re.sub(r"\s+", " ", c).strip()
            if _is_good_fact(c):
                return c[:220]

        # 2) 正文里找第一段中文句子（含句末标点的完整句）
        body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html,
                      flags=re.S | re.I)
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"\s+", " ", body)
        for sent in re.split(r"(?<=[。！？])", body):
            sent = sent.strip()
            if len(sent) >= 30 and _is_good_fact(sent + "。"):
                return sent[:220]
        return ""
    except Exception:
        return ""


def _fact_from_cache(title):
    """从判定缓存里找同一事件的现成摘要（标题不完全一致，用字面相似）。"""
    try:
        cache = analyze._load_cache()
    except Exception:
        return ""
    best, best_sim = "", 0.0
    for v in cache.values():
        s = (v.get("summary") or "").strip()
        if len(s) < 20:
            continue
        t = v.get("title_zh") or ""
        sim = dedup.lexical(title, t)
        if sim > best_sim:
            best, best_sim = s, sim
    return best if best_sim >= 0.55 else ""


# ── 前一日突发接续（2026-11-27）────────────────────────────────────
# 突发通道（poll.py 写 alerts）与日报（本文件）原先是两个独立池子，日报
# 从不读 alerts 表。导致昨天推过的行业级突发，今天既不在日报里、也不会
# 再推一次，直接消失。这里把它接续进来。
def alert_carryover(items, history):
    """把近 ALERT_CARRYOVER_HOURS 小时已推送的突发接续进今日条目。

    返回 (接续条数, 合成条数)。合成指今天没再采到、只能凭 alerts 记录重建的。
    同一线索（topic）只接一条；已刊出过的不接。
    """
    alerts = state.recent_alerts(hours=config.ALERT_CARRYOVER_HOURS)
    if not alerts:
        return 0, 0

    hist_keys = {h["url_key"] for h in history if h.get("url_key")}
    by_key = {state.url_key(it.get("url")): it for it in items}
    carried, synthesized, seen_topic = 0, 0, set()

    for a in alerts:
        if carried >= config.ALERT_CARRYOVER_MAX:
            break
        k = a.get("url_key") or ""
        if k and k in hist_keys:
            continue                    # 已刊出过，不重复
        topic = (a.get("topic") or "").strip()
        sig = topic or (a.get("title") or k)
        if sig in seen_topic:
            continue                    # 同一线索只接一条
        seen_topic.add(sig)

        rule = a.get("rule") or ""
        floor = config.ALERT_SCORE_FLOOR.get(rule, 56)
        existing = by_key.get(k)
        if existing is not None:
            # 今日又采到了：用已有的完整判定，只抬分数 + 标记
            existing["_carried"] = True
            existing["alert_rule"] = rule
            existing["alert_topic"] = topic or None
            if int(existing.get("score") or 0) < floor:
                existing["score"] = floor
            carried += 1
            continue

        # 今日没再采到：用 alerts 记录合成一条最小可用条目
        title = (a.get("title") or "").strip()
        if not title:
            continue
        # 旧 alerts 记录的 headline/detail 为空（历史数据，插入时未写入）。
        # 2026-11-27 修：原先只拼「昨日已作为突发推送，此处接续归档」就完事，
        # 这句话等于告诉模型「这里没有事实」，导致艾为收购钰泰、三星入股
        # ams OSRAM 这种大事进不了招聘素材（实测：换成真实摘要后立刻产出）。
        # 现在按优先级取真事实：og:description 抓取 → 判定缓存 → 标题兜底。
        headline = (a.get("headline") or "").strip()
        detail = (a.get("detail") or "").strip()
        if not detail:
            detail = _fetch_fact("https://" + k if k else "") or ""
        if not detail:
            detail = _fact_from_cache(title)
        if not detail:
            # 实在拿不到：只留标题与线索，不再写「此处归档」那种空话
            detail = title + (f"（所属线索：{topic}）" if topic else "")
        it = {
            "title": title,
            "title_zh": (headline or title)[:60],
            "summary": detail[:200],
            "url": ("https://" + k) if k else "",
            "source_name": "突发通道",
            "source_tier": "T1",
            "published": datetime.fromtimestamp(a["sent_at"], BJ),
            "keep": True,
            "score": floor,
            "line": None,
            "line_secondary": [],
            "type": "政策标准",
            "role": "政策" if rule == "B" else "竞对",
            "impact": "high" if a.get("urgency") == "high" else "medium",
            "entities": [],
            "competitor_hit": None,
            "customer_hit": None,
            "_carried": True,
            "alert_rule": rule,
            "alert_topic": topic or None,
        }
        blob = title + topic
        if re.search(r"并购|收购|入股|融资|控股", blob):
            it["type"] = "并购融资"
        elif re.search(r"涨价|降价|报价|涨价函", blob):
            it["type"] = "价格行情"
        items.append(it)
        by_key[k] = it
        carried += 1
        synthesized += 1

    return carried, synthesized


# ── 主流程 ──────────────────────────────────────────────────────────────
def run(send=True, day=None):
    t_start = time.time()
    now = datetime.now(BJ)
    day = day or now.strftime("%Y-%m-%d")
    print(f"=== {config.REPORT_NAME} 流水线 {now.strftime('%Y-%m-%d %H:%M')} ===")

    # 1 采集
    print("[1/7] 采集")
    # 日报必须拿全量快照：304 表示「与上次抓取时相同」，但代码不缓存正文，
    # 304 会把该源的全部条目当成空 → 直接丢稿。日报一天只跑一次，省这点流量不值得。
    results = collect.collect_all(config.SOURCES)
    raw = []
    for r in results:
        raw.extend(r["items"])
    ok_src = sum(1 for r in results if r["ok"])
    print(f"      {ok_src}/{len(results)} 源可用，{len(raw)} 条原始")

    # 2 判重
    items = dedupe_url(raw)
    print(f"[2/7] 判重：{len(raw)} → {len(items)}")

    # 2.1 跨天硬门（URL）——先拦掉已刊出过的，省判定 token
    history = state.daily_history(day, days=config.LOOKBACK_DAYS)
    hist_urls = {h["url_key"] for h in history if h.get("url_key")}
    if hist_urls:
        before = len(items)
        items = [it for it in items if state.url_key(it.get("url")) not in hist_urls]
        print(f"[2.1] 跨天URL去重：{before} → {len(items)} "
              f"（比对 {len(history)} 条历史，回溯 {config.LOOKBACK_DAYS} 天）")
    else:
        print("[2.1] 跨天URL去重：无历史记录，跳过")

    # 2.5 时效过滤
    fresh, stale = [], 0
    for it in items:
        ok, pub = freshness_ok(it)
        if ok:
            if pub and not it.get("published"):
                it["published"] = pub
            fresh.append(it)
        else:
            stale += 1
    items = fresh
    print(f"[2.5] 时效：丢弃 {stale} 条过期，剩 {len(items)}")

    # 3 判定
    print("[3/7] 判定（预筛+评分+结构化）")
    items = analyze.analyze_all(config, items)

    # 3.5 跨天同事件软门（换源/改标题重发）
    if history:
        before = len(items)
        items, dropped = cross_day_filter(items, history)
        if dropped:
            for d in dropped[:8]:
                print(f"      丢 {d['_dup_reason']:14} {d.get('title_zh','')[:34]}")
        print(f"[3.5] 跨天事件去重：{before} → {len(items)}（丢弃 {len(dropped)}）")
    else:
        print("[3.5] 跨天事件去重：无历史记录，跳过")

    # 3.6 前一日突发接续（2026-11-27）
    # 突发通道推过的条目，次日日报要能看到。必须在「4 过滤」之前注入，
    # 否则它们会被门槛再刷一遍（合成条目本来就已判过突发）。
    carried, synthesized = alert_carryover(items, history)
    if carried:
        print(f"[3.6] 前一日突发接续：+{carried} 条"
              f"（其中今日未重采、凭记录重建 {synthesized} 条）")
    else:
        print("[3.6] 前一日突发接续：无")

    # 4 过滤
    def th(it):
        return config.THRESHOLDS.get(it.get("source_tier"), 68)

    # 4.1 渠道上架稿硬门（分销商开售原厂产品对公司无情报价值）
    dist_dropped = [it for it in items if distributor_listing(it)]
    if dist_dropped:
        items = [it for it in items if not distributor_listing(it)]
        for d in dist_dropped[:5]:
            print(f"      丢 渠道稿          {(d.get('title_zh') or '')[:34]}")
    print(f"[4.1] 渠道稿过滤：丢 {len(dist_dropped)} 条")

    # 4.2 政策实质门：政策类必须能指到具体事实（数字/日期/条款/禁令）
    pol_dropped = [it for it in items if it.get("keep") and not policy_has_substance(it)]
    if pol_dropped:
        items = [it for it in items if not (it.get("keep") and not policy_has_substance(it))]
        for d in pol_dropped[:5]:
            print(f"      丢 政策无实质      {(d.get('title_zh') or '')[:34]}")
    print(f"[4.2] 政策实质门：丢 {len(pol_dropped)} 条")

    kept = [it for it in items if it.get("keep") and int(it.get("score") or 0) >= th(it)]
    # 已判突发的条目不再受信源门槛限制（突发判定比日报评分更严）
    for it in items:
        if it.get("_carried") and it.get("keep") and it not in kept:
            kept.append(it)
    line_of = {k: v["name"] for k, v in config.PRODUCT_LINES.items()}
    for it in kept:
        it["line_name"] = line_of.get(it.get("line")) if it.get("line") else None
        it["line_names_map"] = line_of
        pub = it.get("published")
        it["time_str"] = pub.astimezone(BJ).strftime("%m-%d") if pub else day[5:]
    print(f"[4/7] 过滤：{len(items)} → {len(kept)} 条入刊")

    # 5 聚簇
    print("[5/7] 聚簇")
    clustered = cluster(kept)
    print(f"      {len(kept)} → {len(clustered)} 个事件")
    merged = len(kept) - len(clustered)

    # 6 排序 + TOP5
    # TOP5 排序：先按「有产品线」优先，再分数，再聚簇规模
    clustered.sort(key=lambda x: (0 if x.get("line") else 1,
                                  -int(x.get("score") or 0),
                                  -(x.get("cluster_size") or 1)))
    top5 = clustered[:config.TOP_N]
    top_ids = {id(x) for x in top5}
    for it in clustered:
        it["in_top"] = id(it) in top_ids

    # 7 招聘素材
    print("[6/7] 招聘素材")
    recruit_input = sorted(clustered, key=lambda x: (-int(x.get("score") or 0), x["title_zh"]))
    recruit = analyze.recruit_material(config, recruit_input)
    if recruit is None:
        recruit = analyze.recruit_material(config, recruit_input)
    if recruit:
        print(f"      pull={len(recruit.get('pull', []))} push={len(recruit.get('push', []))}")
    else:
        print("      本日无素材，板块不出")

    # 7.5 记录主体签名（供明天去重）
    for it in clustered:
        it["_subject"] = sorted(subject_key(it))

    # 8 写 MD
    print("[7/7] 落 MD")
    # 演练模式写到沙箱：dry run 曾把正式 vault 与 out-<day>.html 覆盖，
    # 导致已发出的日报被改。send=False 时一律不碰正式目录。
    if send:
        vault = config.VAULT
        os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
        out_html = os.path.join(config.BASE_DIR, "build", f"out-{day}.html")
    else:
        vault = f"/tmp/daily-dry/{day}/vault"
        out_html = f"/tmp/daily-dry/{day}/out-{day}.html"
        os.makedirs(vault, exist_ok=True)
        print(f"      [DRY] 写入沙箱 {vault}")
    for it in clustered:
        rel, fname = render.write_news_md(vault, it, day)
        it["md_name"] = fname
        it["md_path"] = rel
    render.write_daily_md(vault, day, clustered, top5, recruit)
    print(f"      {len(clustered)} 篇新闻 + 1 篇日报 → {vault}")
    if send:
        moved = gc_day_news(vault, day)
        if moved:
            print(f"      清理当日孤儿 {len(moved)} 篇 → {vault}/.trash/gc-{day.replace('-', '')}")

    # 9 渲染邮件
    groups = []
    for key in LINE_ORDER:
        name = line_of[key]
        arr = [it for it in clustered if it.get("line") == key]
        arr.sort(key=lambda x: -int(x.get("score") or 0))
        groups.append({"key": key, "name": name, "items": arr})
    unc = [it for it in clustered if not it.get("line")]
    if unc:
        groups.append({"key": "other", "name": "行业与政策", "items": unc})

    weekday = "一二三四五六日"[now.weekday()]
    day_label = f"{day} 周{weekday}"
    html = mail.render(day_label, top5, recruit, groups,
                       {"total": len(clustered), "merged": merged})

    os.makedirs(os.path.dirname(out_html), exist_ok=True)
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)

    # 10 发信
    summary = {
        "day": day, "raw": len(raw), "after_dedupe": len(items),
        "kept": len(kept), "clusters": len(clustered), "merged": merged,
        "top5": [x["title_zh"] for x in top5],
        "recruit": bool(recruit), "html": out_html,
        "sources_ok": ok_src, "sources_total": len(results),
        "elapsed_s": round(time.time() - t_start, 1),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if send:
        import subprocess
        subject = f"{config.REPORT_NAME} · {day} 早报"
        r = subprocess.run(
            ["node", "scripts/smtp.js", "send", "--to", config.MAIL_TO,
             "--subject", subject, "--html-file", out_html],
            cwd="/home/admin/.openclaw/workspace/skills/imap-smtp-email",
            capture_output=True, text=True, timeout=180)
        print("--- send:", r.stdout.strip()[-300:] or r.stderr.strip()[-300:])
        try:
            sent = '"success": true' in (r.stdout or "")
        except Exception:
            sent = False
        if sent:
            state.record_daily(clustered, day)
            print(f"--- 已登记 {len(clustered)} 条到 daily_items（{day}）")
        else:
            print("--- 发信未确认成功，不登记 daily_items（重试会重新发）")

    return summary


if __name__ == "__main__":
    send = "--send" in sys.argv
    run(send=send)
