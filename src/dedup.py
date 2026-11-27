"""事件级去重：字面相似度 + 主体硬门。

日报（main.py）与突发轮询（poll.py）共用同一套「是不是同一事件」的判断，
避免两边各写一份、口径不一致。这也是 SPEC §0.2 那条「同一事件多家媒体
重复报道只出一条」红线的唯一实现点。
"""
import re

SIM_THRESHOLD = 0.55


def bigrams(s):
    s = re.sub(r"\s+", "", s or "")
    chars = list(s)
    return set("".join(chars[i:i + 2]) for i in range(len(chars) - 1))


def lexical(a, b):
    g, h = bigrams(a), bigrams(b)
    if not g or not h:
        return 0.0
    return len(g & h) / min(len(g), len(h))


def subject_key(it):
    """从实体与命中项推主体签名，用于主体一致硬门。"""
    parts = []
    for k in ("competitor_hit", "customer_hit"):
        if it.get(k):
            parts.append(it[k])
    for e in (it.get("entities") or []):
        parts.append(e)
    return set(p.strip() for p in parts if p and p.strip())


def same_event(subj_a, title_a, subj_b, title_b, min_sim=SIM_THRESHOLD):
    """同事件判定：主体有交集（两边都有主体时）+ 标题字面相似度达阈值。

    任一侧主体为空时只比字面 —— 宁可漏合并，不可错合并：
    错合并会让两条真新闻少发一条，漏合并只是重复，读者能自己看出来。
    """
    a, b = set(subj_a or []), set(subj_b or [])
    if a and b and not (a & b):
        return False
    return lexical(title_a, title_b) >= min_sim
