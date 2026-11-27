"""判定层：预筛 → 评分 → 结构化（单次调用完成，省 token）

每条的输出：
  keep, score, line(产品线), line_secondary, type(内容类型), role(角色), impact,
  title_zh, summary(一句话事实，描述性), entities, why_recruit(可空)

判断只做「是不是这个行业 / 属于哪条线 / 有多重要」，不写"所以呢"。
"""
import json
import os
import re
import time

import config
import requests

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
BASE = "https://api.deepseek.com/v1"
MODEL = "deepseek-chat"


def _post(payload, retries=3, timeout=90):
    last = None
    for i in range(retries):
        try:
            r = requests.post(f"{BASE}/chat/completions", timeout=timeout,
                              headers={"Content-Type": "application/json",
                                       "Authorization": f"Bearer {API_KEY}"},
                              json=payload)
            if r.status_code == 429:
                time.sleep(3 * (i + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


def _extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def build_prompt(cfg, batch):
    lines = "\n".join(
        f'{i+1}. 标题：{it["title"]}\n   来源：{it["source_name"]}（{it["source_tier"]}）\n'
        f'   摘要：{(it.get("summary") or "")[:300]}'
        for i, it in enumerate(batch))

    line_desc = "\n".join(
        f'- {k}（{v["name"]}）：{"/".join(v["kw"][:12])}'
        for k, v in cfg.PRODUCT_LINES.items())

    return f"""你在为{cfg.COMPANY}（{cfg.COMPANY_TICKER}）内部新闻播报做判定。{cfg.COMPANY}是{cfg.INDUSTRY_NAME}设计公司，{len(cfg.PRODUCT_LINES)} 条产品线：{"、".join(v["name"] for v in cfg.PRODUCT_LINES.values())}。

对每一条资料判断并输出 JSON 数组，每条一个对象：

1. keep：true/false。true 的条件是「与上述产品线或上下游有实质关联」。以下一律 false：与本公司业务无关的终端发布、招聘广告、纯活动通知、纯观点无事实、明显软文通稿且无任何信息增量。
2. score：0-100 重要性分。评分只看五点，不要综合印象：
   - 事实密度：有具体型号/参数/金额/时间/客户名 +15；只有形容词 -10
   - 主体权重：竞对或客户公司的实质动作 +20；行业机构/标准组织 +10；其他 +0
   - 影响范围：影响整条产品线或行业格局 +25；只影响单一产品 +10；无影响 +0
   - 新鲜度：明确发生在 3 天内 +15；无日期 +0
   - 稿件性质：非事件性稿件 -20。判定标准是「有没有谁做了什么」：
     第三方研究报告/产业链分析、拆解实测评测、行业综述与趋势推演、
     “XX路径与考验”“XX元年未放量”这类评论稿，都没有明确行为主体和动作，
     一律扣 20 分。厂商自己发布新品/宣布量产/签约/并购，属于事件，不扣。
   基线 30 分。厂商纯通稿最多 45 分。
3. line：六条线之一，key 取值只能是 {" / ".join(cfg.PRODUCT_LINES.keys())}。判断不清给 null。
   边界：驱动负载（开关/马达/LED/栅极）归 driver；变换电压（AC-DC/DC-DC/LDO/PMIC）归 power；与电池直接耦合（充电/保护/电量计）归 battery。
4. line_secondary：0-2 个次相关产品线 key。
5. type：产品发布 / 技术突破 / 产能供应链 / 财务经营 / 并购融资 / 人事组织 / 政策标准 / 客户导入 / 价格行情 / 研究报告
6. role：竞对 / 客户 / 供应链 / 政策 / 行业 之一。
   - 主体是竞对名录里的公司 → 竞对
   - 主体是客户名录里的公司 → 客户
   - 主体是晶圆厂/封测/材料/设备 → 供应链
   - 主体是政府/标准组织/协会 → 政策
   - 其他 → 行业
7. impact：high / medium / low。high 仅用于：竞对重大动作、行业级冲击（管制/关税/标准强制）、头部厂重大财务变化。
8. title_zh：中文标题，≤28 字，自足（不依赖上下文能看懂），不加书名号引号。
9. summary：一句话事实摘要，40-70 字，只陈述事实（谁做了什么、对象是什么、关键数字），禁止出现"意味着""说明""值得关注""将影响"这类判断词。
10. entities：文中实际讨论的主体公司名数组（不是顺带提及），0-4 个，用常用简称。
11. competitor_hit：主体是否命中竞对名录，返回命中的那个名字，否则 null。
12. customer_hit：主体是否命中客户名录，返回命中的那个名字，否则 null。

# 2026-11-27：去掉 [:80] / [:45] 截断。原来只送前 80 条竞对，导致
# 兆易创新、澜起科技、汇顶科技、韦尔股份、思特威、格科微等 46 家对手
# 模型根本看不到，role 判成「行业」。客户名录同理漏了 15 家。
竞对名录（共 {len(cfg.COMPETITOR_SET)} 家）：{"、".join(cfg.COMPETITOR_SET)}

注意：CIS（CMOS 图像传感器）、SPAD（单光子雪崩二极管）、ToF（飞行时间测距）是传感芯片线的重要组成部分。涉及韦尔股份/豪威、思特威、格科微、灵明光子、阜时科技、芯视界、宇称电子等的 CIS/SPAD/ToF 产品动态，属于传感芯片线，且是竞对动作，不要判为无关。
客户名录（共 {len(cfg.CUSTOMER_SET)} 家）：{"、".join(cfg.CUSTOMER_SET)}

六条产品线关键词：
{line_desc}

资料列表：
{lines}

只输出 JSON 数组，长度必须等于 {len(batch)}，不要任何解释。顺序与输入一致。"""


def analyze_batch(cfg, batch):
    prompt = build_prompt(cfg, batch)
    payload = {"model": MODEL, "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.2, "max_tokens": 4000,
               "response_format": {"type": "json_object"}}
    # deepseek json_object 需要 object，用数组包裹
    payload["messages"][0]["content"] = prompt.replace(
        "只输出 JSON 数组", '输出 JSON 对象 {"items": [...]}，items 是数组').replace(
        "长度必须等于", "长度必须等于")
    try:
        data = _post(payload)
        text = data["choices"][0]["message"]["content"]
        obj = _extract_json(text)
        if isinstance(obj, dict):
            items = obj.get("items") or obj.get("data") or []
        elif isinstance(obj, list):
            items = obj
        else:
            items = []
        if len(items) != len(batch):
            # 长度不符，退化成逐条
            return None
        return items
    except Exception as e:
        print("    ! batch fail:", type(e).__name__, str(e)[:80])
        return None


def analyze_one(cfg, item):
    prompt = build_prompt(cfg, [item])
    prompt = prompt.replace("只输出 JSON 数组", '输出 JSON 对象 {"items": [...]}').replace(
        f"长度必须等于 1", "items 长度必须等于 1")
    payload = {"model": MODEL, "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.2, "max_tokens": 1200,
               "response_format": {"type": "json_object"}}
    try:
        data = _post(payload)
        obj = _extract_json(data["choices"][0]["message"]["content"])
        if isinstance(obj, dict):
            items = obj.get("items") or []
            return items[0] if items else None
        if isinstance(obj, list) and obj:
            return obj[0]
    except Exception as e:
        print("    ! one fail:", type(e).__name__, str(e)[:60])
    return None


CACHE_PATH = config.CACHE_PATH

def _load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_cache(c):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False)

def _ckey(it):
    import hashlib
    return hashlib.sha256((it.get("url","") + "|" + it.get("title","")).encode()).hexdigest()[:32]


def analyze_all(cfg, items, batch_size=8):
    """判所有条目。命中缓存直接复用；未命中的分批调模型。原顺序返回。"""
    cache = _load_cache()
    for it in items:
        hit = cache.get(_ckey(it))
        if hit:
            it.update(hit)
    todo = [it for it in items if _ckey(it) not in cache]
    if len(todo) < len(items):
        print(f"  (缓存命中 {len(items)-len(todo)} 条，需判定 {len(todo)} 条)")

    total = len(todo)
    for i in range(0, total, batch_size):
        batch = todo[i:i + batch_size]
        print(f"  判定 {i+1}-{i+len(batch)} / {total}")
        res = analyze_batch(cfg, batch)
        if res is None:
            res = []
            for it in batch:
                r = analyze_one(cfg, it)
                res.append(r or {})
        for it, r in zip(batch, res):
            if not isinstance(r, dict):
                r = {}
            it.update({
                "keep": bool(r.get("keep", False)),
                "score": int(r.get("score") or 0),
                "line": r.get("line") if r.get("line") in cfg.PRODUCT_LINES else None,
                "line_secondary": [x for x in (r.get("line_secondary") or [])
                                   if x in cfg.PRODUCT_LINES],
                "type": r.get("type") or "行业动态",
                "role": r.get("role") if r.get("role") in
                        ("竞对", "客户", "供应链", "政策", "行业") else "行业",
                "impact": r.get("impact") if r.get("impact") in
                          ("high", "medium", "low") else "low",
                "title_zh": (r.get("title_zh") or it["title"])[:60],
                "summary": (r.get("summary") or "")[:200],
                "entities": [cfg.norm_entity(x) for x in (r.get("entities") or [])
                             if isinstance(x, str)][:4],
                "competitor_hit": cfg.norm_entity(r.get("competitor_hit")),
                "customer_hit": cfg.norm_entity(r.get("customer_hit")),
            })
            cache[_ckey(it)] = {k: it.get(k) for k in (
                "keep","score","line","line_secondary","type","role","impact",
                "title_zh","summary","entities","competitor_hit","customer_hit")}
    if total:
        _save_cache(cache)
    return items


def _load_pitch():
    """读公司 pitch（招聘事实底座）。缺失不致命，降级为空串。

    模型本身不知道你的公司是家什么企业，只能拿提示词里那几句业务范围硬凑，
    写出来的“为什么该选我们”全是空话。pitch 给它客户、技术底子、阶段、
    风险的可引用事实，才能写出具体理由。模板见 pitch/company-pitch.md。
    """
    import pathlib
    p = pathlib.Path(config.PITCH_PATH)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return ""
    # 去掉 frontmatter 与最后的「维护清单」——维护说明对模型没用，白烧 token
    text = re.sub(r"^---.*?---\s*", "", text, flags=re.S)
    cut = text.find("## 八、")
    if cut > 0:
        text = text[:cut]
    return text.strip()


def recruit_material(cfg, items):
    """生成招聘板块素材。无素材返回 None。"""
    if not items:
        return None
    brief = "\n".join(
        f'- [{it["role"]}/{it["impact"]}] {it["title_zh"]}｜{it["source_name"]}｜{it["summary"]}'
        for it in items[:24])

    pitch = _load_pitch()
    co = cfg.COMPANY
    pitch_block = f"""
【{co}事实底座】以下是{co}的公开事实，写理由时只能引用这里出现的内容，
不要自己编数字、客户名或产品型号：

{pitch}
""" if pitch else ""

    prompt = f"""你在为{co} HR 团队（招聘专员与 HRBP）写一段招聘谈资素材。

读者是专业 HR，懂行业术语，不需要解释名词。他们的用途是：和候选人沟通时，用当天的行业动态作为论据。
{pitch_block}
从下面今日新闻中，选出真能支撑论据的条目。原则：
- 论据必须来自上面列出的今日新闻。新闻媒体报道本身就是合法出处，出处写媒体名+日期即可。
- 宁缺勿滥指的是“没有事实就别写”，不是“事情不够大就别写”。并购整合、竞对动作、
  行业格局变化、新品发布本身就是硬论据，不要因为“这只是行业新闻”就弃用。
- 不要写“{co}平台广阔”“成长空间大”这种没有事实的套话。

输出 JSON 对象：
{{"pull": [...], "push": [...]}}

pull 每一项（"可以吸引候选人的点"）：
{{"fact": "一句话事实，含具体数字或型号，≤50字",
  "ncis": "为什么应该加入{co}，≤50字。必须以「{co}」为主语或核心，点出{co}在这件事上的
           具体位置或已有的对应产品线/积累，让候选人看完就知道「所以该来{co}」。
           只夸行业、说不出{co}有什么的，这条不要输出。",
  "why": "为什么这条对招聘有意义，≤40字",
  "script": "可以这样讲的口语原话，≤55字，必须出现「{co}」二字",
  "roles": "适用岗位，如 研发/产品定义，或 通用",
  "source": "出处，写新闻媒体名+日期，如 XX媒体 11-27"}}

硬要求：pull 的每一条都必须落到{co}身上，理由从上面的「{co}事实底座」里找依据，
不要泛泛而谈。对不上{co}任何一条产品线或客户的事实，宁可不写这一条。

push 每一项（"可以用来对冲其他 offer 的"）：
{{"against": "对哪类 offer，如 国际大厂同行", "fact": "≤50字", "why": "≤40字",
  "script": "≤45字", "roles": "通用", "source": "出处，写新闻媒体名+日期"}}

pull 最多 3 条，push 最多 3 条。任一侧为空就给空数组。

今日新闻：
{brief}"""

    payload = {"model": MODEL, "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.3, "max_tokens": 2000,
               "response_format": {"type": "json_object"}}
    try:
        data = _post(payload)
        obj = _extract_json(data["choices"][0]["message"]["content"])
        if not isinstance(obj, dict):
            return None
        pull = [x for x in (obj.get("pull") or []) if isinstance(x, dict) and x.get("fact")]
        push = [x for x in (obj.get("push") or []) if isinstance(x, dict) and x.get("fact")]
        # ncis（为什么该加入本公司）缺失时用 why 兑底，
        # 保证渲染层永远有东西可显示，不会出现半截条目。
        for x in pull:
            if not (x.get("ncis") or "").strip():
                x["ncis"] = x.get("why") or ""
        if not pull and not push:
            return None
        return {"pull": pull[:3], "push": push[:3]}
    except Exception as e:
        print("  ! recruit fail:", type(e).__name__, str(e)[:80])
        return None
