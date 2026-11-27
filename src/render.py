"""渲染层：Obsidian MD + HTML 邮件

MD 规则：
- frontmatter 带标签与双链所需字段
- 每篇先确保实体 stub 存在，双链永不悬空
- 标签用中文短名，实体页文件用前缀解耦
"""
import os
import re
from datetime import datetime, timedelta, timezone

import config

BJ = timezone(timedelta(hours=8))

TAG_LINE = {
    "battery": "电池管理", "power": "电源管理", "driver": "智能驱动",
    "sensor": "传感", "link": "传输", "mcu": "MCU",
}
IMPACT_ZH = {"high": "high", "medium": "medium", "low": "low"}
ROLE_TAG = {"竞对": "竞对", "客户": "客户", "供应链": "供应链", "政策": "政策", "行业": "行业"}


def _safe(name):
    name = re.sub(r'[\\/:*?"<>|#^\[\]]', "", name)
    return name.strip()[:60]


def _bj(dt):
    if not dt:
        return None
    return dt.astimezone(BJ)


def ensure_entity(vault, kind, name):
    """kind: 产品线 | 竞对 | 客户 | 机构。返回 md 文件名（不含 .md）。"""
    prefix = {"产品线": "产品线-", "竞对": "竞对-", "客户": "客户-", "机构": "机构-"}[kind]
    folder = os.path.join(vault, "40-Entities", kind)
    os.makedirs(folder, exist_ok=True)
    fname = _safe(prefix + name)
    path = os.path.join(folder, fname + ".md")
    if not os.path.exists(path):
        tag = {"产品线": "sc/line", "竞对": "sc/role/竞对",
               "客户": "sc/role/客户", "机构": "sc/role/行业"}[kind]
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"""---
type: entity
kind: {kind}
name: {name}
tags:
  - sc/entity/{kind}
  - {tag}
---

# {name}

## 简介

（待补充）

## 相关新闻

""")
    return fname


def write_news_md(vault, it, day=None):
    """写单条新闻 MD，返回相对路径。"""
    dt = _bj(it.get("published")) or datetime.now(BJ)
    d = day or dt.strftime("%Y-%m-%d")
    ym = d[:7].replace("-", "/")
    folder = os.path.join(vault, "30-News", ym)
    os.makedirs(folder, exist_ok=True)

    # 双链：产品线 + 实体
    line = it.get("line")
    links = []
    if line:
        links.append(ensure_entity(vault, "产品线", it["line_name"]))
    # 实体归一 + 去重：同一家公司只建一个 stub，且优先按 竞对/客户 归类
    comp = config.norm_entity(it.get("competitor_hit"))
    cust = config.norm_entity(it.get("customer_hit"))
    ent_links = []
    seen_ent = set()
    if comp:
        ent_links.append(ensure_entity(vault, "竞对", comp)); seen_ent.add(comp)
    if cust and cust not in seen_ent:
        ent_links.append(ensure_entity(vault, "客户", cust)); seen_ent.add(cust)
    for e in (it.get("entities") or []):
        ne = config.norm_entity(e)
        if ne and ne not in seen_ent:
            kind = "竞对" if ne in config.COMPETITOR_SET else ("客户" if ne in config.CUSTOMER_SET else "机构")
            ent_links.append(ensure_entity(vault, kind, ne)); seen_ent.add(ne)

    tags = []
    if line:
        tags.append(f"sc/line/{TAG_LINE[line]}")
    tags.append(f"sc/type/{it.get('type', '行业动态')}")
    tags.append(f"sc/role/{ROLE_TAG.get(it.get('role'), '行业')}")
    tags.append(f"sc/impact/{IMPACT_ZH[it.get('impact', 'low')]}")
    tags.append(f"sc/src/{it.get('source_tier', 'T2').lower().replace('.', '_')}")
    for e in [comp, cust]:
        if e and f"sc/co/{_safe(e)}" not in tags:
            tags.append(f"sc/co/{_safe(e)}")

    title = _safe(it["title_zh"])
    fname = f"{d}-{title}"
    # 同日同标题即同一条新闻 → 覆盖写，不再生成 -2/-3 副本（重跑幂等）
    path = os.path.join(folder, fname + ".md")
    fname = os.path.basename(path)[:-3]

    pub = _bj(it.get("published"))
    fm = ["---"]
    fm.append(f'title: "{it["title_zh"].replace(chr(34), chr(39))}"')
    fm.append(f"date: {d}")
    if pub:
        fm.append(f'time: "{pub.strftime("%H:%M")}"')
    fm.append(f'source: "{it.get("source_name", "")}"')
    fm.append(f'source_url: "{it.get("url", "")}"')
    fm.append(f"source_tier: {it.get('source_tier', 'T2')}")
    fm.append(f"product_line: {it.get('line_name') or '未分类'}")
    if it.get("line_secondary"):
        sec = [it["line_names_map"][k] for k in it["line_secondary"] if k in it.get("line_names_map", {})]
        if sec:
            fm.append(f"product_lines_secondary: [{', '.join(sec)}]")
    fm.append(f"type: {it.get('type', '行业动态')}")
    fm.append(f"role: {it.get('role', '行业')}")
    fm.append(f"impact: {it.get('impact', 'low')}")
    fm.append(f"relevance: {it.get('score', 0)}")
    if it.get("entities"):
        fm.append(f"entities: [{', '.join(it['entities'])}]")
    if comp:
        fm.append(f"competitors: [{comp}]")
    if cust:
        fm.append(f"customers: [{cust}]")
    fm.append("tags:")
    for t in tags:
        fm.append(f"  - {t}")
    fm.append("---")

    body = [""]
    body.append(f'# {it["title_zh"]}')
    body.append("")
    if it.get("summary"):
        body.append(f'> {it["summary"]}')
        body.append("")
    body.append("## 事实")
    body.append("")
    if it.get("entities"):
        body.append(f'- 主体：{"、".join(it["entities"])}')
    body.append(f'- 类型：{it.get("type", "行业动态")}')
    if it.get("line_name"):
        body.append(f'- 产品线：{it["line_name"]}')
    if pub:
        body.append(f'- 原文时间：{pub.strftime("%Y-%m-%d %H:%M")}（北京时间）')
    body.append("")
    body.append("## 关联")
    body.append("")
    for l in links:
        body.append(f"- 产品线：[[{l}]]")
    for l in ent_links:
        body.append(f"- 实体：[[{l}]]")
    body.append(f"- 当日日报：[[{d}]]")
    body.append("")
    if it.get("summary"):
        body.append("## 摘要")
        body.append("")
        body.append(it["summary"])
        body.append("")
    body.append("## 溯源")
    body.append("")
    body.append(f'- 信源：{it.get("source_name", "")}（{it.get("source_tier", "T2")}）')
    body.append(f'- 原文：{it.get("url", "")}')
    body.append(f'- 评分：{it.get("score", 0)}')
    body.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(fm + body))
    return os.path.relpath(path, vault), fname


def write_daily_md(vault, day, items, top5, recruit):
    """写日报索引 MD。"""
    folder = os.path.join(vault, "10-Daily", day[:4])
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{day}.md")

    lines = ["---", f"date: {day}", "type: daily",
             "tags:", "  - daily/news", "---", "", f"# {config.REPORT_NAME} · {day}", ""]

    if top5:
        lines.append("## 今日必读 TOP 5")
        lines.append("")
        for i, it in enumerate(top5, 1):
            lines.append(f'{i}. [[{it["md_name"]}]] — {it["title_zh"]}')
        lines.append("")

    if recruit:
        lines.append("## 招聘启示")
        lines.append("")
        if recruit.get("pull"):
            lines.append("### 可以吸引候选人的点")
            lines.append("")
            for r in recruit["pull"]:
                lines.append(f'- **{r.get("fact","")}** — {r.get("why","")}')
            lines.append("")
        if recruit.get("push"):
            lines.append("### 可以用来对冲其他 offer 的")
            lines.append("")
            for r in recruit["push"]:
                lines.append(f'- 对 {r.get("against","")}：**{r.get("fact","")}** — {r.get("why","")}')
            lines.append("")

    by_line = {}
    for it in items:
        by_line.setdefault(it.get("line_name") or "未分类", []).append(it)
    if by_line:
        lines.append("## 全部条目")
        lines.append("")
        for name, arr in by_line.items():
            lines.append(f"### {name}")
            lines.append("")
            for it in arr:
                lines.append(f'- [[{it["md_name"]}]] — {it["title_zh"]}')
            lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return os.path.join("10-Daily", day[:4], f"{day}.md")
