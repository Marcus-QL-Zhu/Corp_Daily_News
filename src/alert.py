"""突发即时：判定 + 飞书推送

触发条件：
  1. 竞对重大动作：新品/并购/扩产/大客户定点
  2. 行业级冲击：出口管制/关税/标准强制切换/头部厂涨降价
  —— 不含自家公告，不含客户动作

判定只对「新出现的 URL」做，命中才发，已发过的不再发。
"""
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import config
import requests

BJ = timezone(timedelta(hours=8))

FEISHU_APP_ID = "cli_a92b060e06785bd6"
FEISHU_API = "https://open.feishu.cn/open-apis"

# 免打扰：22:00-07:00 不发，除非是最高级别（出口管制/关税/禁运）
QUIET_START, QUIET_END = 22, 7

_token_cache = {"token": None, "exp": 0}


def _secret():
    s = os.environ.get("FEISHU_APP_SECRET")
    if s:
        return s
    from pathlib import Path
    for line in (Path.home() / ".openclaw/.env").read_text(encoding="utf-8").splitlines():
        if line.startswith("FEISHU_APP_SECRET="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("FEISHU_APP_SECRET missing")


def tenant_token():
    if _token_cache["token"] and _token_cache["exp"] > time.time() + 60:
        return _token_cache["token"]
    r = requests.post(f"{FEISHU_API}/auth/v3/tenant_access_token/internal",
                      json={"app_id": FEISHU_APP_ID, "app_secret": _secret()},
                      timeout=15)
    d = r.json()
    if d.get("code") != 0 or not d.get("tenant_access_token"):
        raise RuntimeError(f"feishu token: {d.get('msg')}")
    _token_cache["token"] = d["tenant_access_token"]
    _token_cache["exp"] = time.time() + int(d.get("expire") or 3600)
    return _token_cache["token"]


def send_text(open_id, text):
    """发纯文本卡片给个人。返回 message_id 或抛错。"""
    token = tenant_token()
    payload = {
        "receive_id": open_id,
        "msg_type": "interactive",
        "content": json.dumps(_card(text), ensure_ascii=False),
    }
    auth = "Bearer " + token
    r = requests.post(f"{FEISHU_API}/im/v1/messages?receive_id_type=open_id",
                      headers={"Authorization": auth,
                               "Content-Type": "application/json"},
                      json=payload, timeout=25)
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"feishu send: {d.get('code')} {d.get('msg')}")
    return d.get("data", {}).get("message_id")


def _esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _card(text):
    """极简卡片：一条突发一个卡，标题红点 + 正文。"""
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"⚡ {config.REPORT_NAME} · 突发"},
            "template": "red",
        },
        "body": {"elements": [{"tag": "markdown", "content": text}]},
    }


# ── 判定 ────────────────────────────────────────────────────────────────
ALERT_PROMPT = """你在为{company}（{industry}，产品线：{lines}）做突发新闻判定。

对每条资料判断：是否值得「立刻」推送给业务负责人（不等日报）。

只有两类算突发：
A. 竞对重大动作 —— 新品发布（有明确规格突破或新品类）、并购融资、产能扩张、拿到大客户定点。常规型号更新、参数微调、常规营销活动不算。
B. 行业级冲击 —— 出口管制/关税/禁运/强制标准切换；头部厂（TI/ADI/Infineon/ST/Renesas/MPS 等国际大厂）的整线涨价或降价。征求意见稿、行业会议、常规政策解读不算。

严格排除（一律不算突发，无论幅度多大）：
- 常规调价、单型号报价变动、涨价通知函 —— 价格波动是常态，不属于突发
- 存储、内存、面板、晶圆代工等大宗价格行情与分析
- 由价格变化衍生的市场反应稿（板块涨跌、股价、抛售、资金流向）
- 媒体分析稿、综述稿、流向地图、产业链推演、评论
- 自家公告、客户新品、研报观点、拆解评测

输出 JSON 对象 {"items": [...]}，items 里每条一个对象，顺序与资料一致：
{"alert": true/false,
 "rule": "A" 或 "B" 或 null,
 "urgency": "high" 或 "normal",
 "headline": "一句话，≤30字，说清谁做了什么",
 "detail": "2-3句，含关键数字与对公司的直接关联，≤120字",
 "line": "六条线之一的中文名或 null",
 "topic": "事件线索的稳定短标签，≤14字"}

topic 用于 24 小时内同线索只推一次。判断方式：把这条归到它所属的那条
政策/交易线索上，而不是复述这条的具体细节。同一线索的后续进展、不同
媒体的不同说法，都必须用同一个 topic。例：
- 「BIS新规生效，H200停售」「美AI芯片管制扩至跨境云算力」「美国会推进
  三项AI芯片出口法案」→ 都用「美对华AI芯片出口管制」
- 「美对16国启动301调查」「美301方案台湾维持15%」→ 都用「美301关税调查」
- 「欧盟拟对混动车设年度进口配额」→「欧盟混动车进口配额」
- 「纳芯微4.87亿并购」→「纳芯微并购」；并购不同标的才换 topic
alert=false 时 topic 给 null。

urgency=high 仅用于出口管制/关税/禁运/头部厂重大并购。涨价降价永远不是 high。

资料：
{items}"""


def _extract_json(text):
    text = (text or "").strip()
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


def judge_alerts(new_items, api_key=None, model="deepseek-chat", max_n=15,
                 return_judged=False):
    """对新条目做突发判定。

    return_judged=True 时返回 (hits, judged)，judged 是「真正送进模型并拿到
    结论」的条目 —— 调用方据此决定登记哪些为已见。截断和异常都不能算判定过。
    """
    if not new_items:
        return ([], []) if return_judged else []
    api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
    batch = new_items[:max_n]
    lines = "\n".join(
        f'{i+1}. 标题：{it["title"]}\n   来源：{it.get("source_name","")}\n'
        f'   摘要：{(it.get("summary") or "")[:260]}'
        for i, it in enumerate(batch))
    # 先填公司/行业/产品线占位符，再填资料。不能用 str.format，
    # 提示词里还有 JSON 示例的花括号。
    prompt = (ALERT_PROMPT
              .replace("{company}", config.COMPANY)
              .replace("{industry}", config.INDUSTRY_NAME)
              .replace("{lines}", " / ".join(v["name"] for v in config.PRODUCT_LINES.values()))
              .replace("{items}", lines))

    try:
        auth = "Bearer " + api_key
        r = requests.post("https://api.deepseek.com/v1/chat/completions",
                          headers={"Content-Type": "application/json",
                                   "Authorization": auth},
                          json={"model": model,
                                "messages": [{"role": "user", "content": prompt}],
                                "temperature": 0.1, "max_tokens": 2500,
                                "response_format": {"type": "json_object"}},
                          timeout=90)
        r.raise_for_status()
        obj = _extract_json(r.json()["choices"][0]["message"]["content"])
        arr = obj.get("items") if isinstance(obj, dict) else obj
        if not isinstance(arr, list):
            return ([], []) if return_judged else []
        out = []
        for it, verdict in zip(batch, arr):
            if not isinstance(verdict, dict) or not verdict.get("alert"):
                continue
            out.append({
                "item": it,
                "rule": verdict.get("rule"),
                "urgency": verdict.get("urgency") or "normal",
                "headline": (verdict.get("headline") or it["title"])[:60],
                "detail": (verdict.get("detail") or "")[:300],
                "line": verdict.get("line"),
                "topic": (verdict.get("topic") or "")[:40] or None,
            })
        return (out, batch) if return_judged else out
    except Exception as e:
        print(f"  ! judge_alerts fail: {type(e).__name__} {str(e)[:80]}")
        return ([], []) if return_judged else []


# ── 渲染与发送 ──────────────────────────────────────────────────────────
def render_alert(alert):
    it = alert["item"]
    src = it.get("source_name", "")
    pub = it.get("published")
    when = pub.astimezone(BJ).strftime("%m-%d %H:%M") if pub else ""
    rule_zh = {"A": "竞对动作", "B": "行业冲击"}.get(alert.get("rule"), "动态")
    line = alert.get("line") or ""
    meta = " · ".join(x for x in (src, when, rule_zh, line) if x)
    parts = [f'**{_esc(alert["headline"])}**', "",
             f'<font color="grey">{_esc(meta)}</font>']
    if alert.get("detail"):
        parts += ["", _esc(alert["detail"])]
    parts += ["", f'[原文]({it.get("url","")})']
    return "\n".join(parts)


def in_quiet_hours(urgency="normal"):
    h = datetime.now(BJ).hour
    quiet = (h >= QUIET_START or h < QUIET_END)
    return quiet and urgency != "high"


def push(alert, open_id):
    """发一条突发。返回 True/False。"""
    if in_quiet_hours(alert.get("urgency", "normal")):
        print(f"    (免打扰时段，跳过：{alert['headline'][:30]})")
        return False
    try:
        mid = send_text(open_id, render_alert(alert))
        print(f"    ✓ 已推送飞书 {mid}")
        return True
    except Exception as e:
        print(f"    ! 推送失败 {type(e).__name__} {str(e)[:80]}")
        return False


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import config
    mid = send_text(config.FEISHU_OPEN_ID,
                    f"**突发通道自检**\n\n这是{config.REPORT_NAME}的突发推送测试，收到即通道正常。\n\n"
                    "<font color=\"grey\">来源：系统自检 · 无需回复</font>")
    print("sent", mid)
