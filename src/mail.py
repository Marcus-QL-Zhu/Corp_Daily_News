"""渲染层：HTML 邮件（与用户已确认的 v6 版式一致）

顺序：TOP5 → 招聘启示 → 目录 → 六线新闻
无废话：不写条数统计、不写引导语、不写溯源脚注、不写名词速查。
"""
from datetime import datetime

import config

LINE_ORDER = config.LINE_ORDER
IMPACT_COLOR = {"high": "#c8102e", "medium": "#d48806", "low": "#8c8c8c"}
IMPACT_ZH = {"high": "高", "medium": "中", "low": "低"}


def _esc(s):
    if not s:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _url(u):
    """邮件里的 href 需转义 & 等字符。"""
    if not u:
        return ""
    return (_esc(u).replace('"', "&quot;").replace("'", "&#39;"))


def _anchor(key):
    return f"sec-{key}"


def render(day_label, top5, recruit, groups, counts):
    """groups: [{'key','name','items'}]，按 LINE_ORDER 排好"""
    P = []
    A = P.append

    A('<!DOCTYPE html><html><head><meta charset="utf-8">'
      '<meta name="viewport" content="width=device-width,initial-scale=1">')
    # 窄窗口换行（2026-11-27）：原来容器写死 width=680，窗口一窄就横向溢出。
    # 改成 max-width + 100% 宽，并给所有文本块开 word-break，长料号/英文标题
    # 也能在容器内折行，不再把版式撑破。
    A('<style>'
      'body,table,td,div,p,a,span{-webkit-text-size-adjust:100%;}'
      'table,td,div,p,a,span,li{word-wrap:break-word;overflow-wrap:break-word;'
      'word-break:break-word;white-space:normal;}'
      '@media only screen and (max-width:640px){'
      '.px{padding-left:16px !important;padding-right:16px !important;}'
      '}'
      '</style>')
    A('</head>')
    A('<body style="margin:0;padding:0;background:#f4f5f7;'
      "font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;\">")
    A('<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f5f7;padding:20px 0;">')
    A('<tr><td align="center">')
    A('<table width="100%" cellpadding="0" cellspacing="0" style="max-width:680px;background:#fff;'
      'border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08);">')

    # ── HEADER ──
    A('<tr><td class="px" style="background:#1a3a5c;padding:20px 28px;">')
    A('<table width="100%" cellpadding="0" cellspacing="0"><tr>')
    A(f'<td><div style="color:#fff;font-size:19px;font-weight:600;">{_esc(config.REPORT_NAME)} · 早报</div>'
      f'<div style="color:#a8c0d8;font-size:12px;margin-top:4px;">{_esc(day_label)}</div></td>')
    A('<td align="right"><div style="color:#7fa3c4;font-size:11px;">内部资料<br>请勿外传</div></td>')
    A('</tr></table></td></tr>')

    # ── 1. TOP 5 ──
    A('<tr><td class="px" style="padding:24px 28px 0;">')
    A('<div style="font-size:13px;font-weight:700;color:#c8102e;letter-spacing:1px;'
      'padding-bottom:10px;border-bottom:2px solid #c8102e;">今日必读 TOP 5</div></td></tr>')
    A('<tr><td class="px" style="padding:14px 28px 0;"><table width="100%" cellpadding="0" cellspacing="0">')
    for i, it in enumerate(top5, 1):
        color = IMPACT_COLOR.get(it.get("impact"), "#8c8c8c")
        link = _url(it.get("url"))
        A('<tr><td style="padding:0 0 16px;">')
        title = _esc(it["title_zh"])
        if link:
            title = (f'<a href="{link}" style="color:#111;text-decoration:none;">'
                     f'{title}</a>')
        A(f'<div style="font-size:15px;font-weight:600;color:#111;line-height:1.5;">'
          f'<span style="color:#c8102e;">{i} ·</span> {title}</div>')
        src = _esc(it["source_name"])
        if link:
            src = (f'<a href="{link}" style="color:#999;text-decoration:none;">'
                   f'{src}</a>')
        A(f'<div style="font-size:11px;color:#999;margin:5px 0 6px;">'
          f'{src} · {_esc(it.get("time_str"))} · '
          f'{_esc(it.get("line_name") or "行业与政策")} · '
          f'<span style="color:{color};font-weight:600;">{IMPACT_ZH.get(it.get("impact"), "低")}</span></div>')
        if it.get("summary"):
            A(f'<div style="font-size:13px;color:#444;line-height:1.7;">{_esc(it["summary"])}</div>')
        A('</td></tr>')
    A('</table></td></tr>')

    # ── 2. 招聘启示（有素材才出）──
    if recruit and (recruit.get("pull") or recruit.get("push")):
        A('<tr><td class="px" style="padding:10px 28px 0;">')
        A('<table width="100%" cellpadding="0" cellspacing="0" '
          'style="border:1px solid #d9e2ec;border-radius:6px;overflow:hidden;">')
        A('<tr><td style="background:#eef4fa;padding:12px 16px;border-bottom:1px solid #d9e2ec;">'
          '<div style="font-size:13px;font-weight:700;color:#1a3a5c;letter-spacing:1.5px;">'
          "招 聘 启 示</div></td></tr>")

        if recruit.get("pull"):
            A('<tr><td style="padding:16px 16px 6px;">')
            A('<div style="font-size:12px;font-weight:700;color:#0a6b4a;letter-spacing:.5px;'
              'margin-bottom:10px;">▎可以吸引候选人的点</div>')
            A('<table width="100%" cellpadding="0" cellspacing="0" '
              'style="font-size:13.5px;color:#333;line-height:1.85;">')
            for r in recruit["pull"]:
                A('<tr><td style="padding:8px 0 14px 14px;text-indent:-14px;">')
                A(f'<span style="color:#0a6b4a;">●</span>  {_esc(r.get("fact"))}<br>')
                # 为什么该选本公司必须紧跟事实，且视觉上突出，
                # 不能让读者读完只记住「行业在整合」而不知道跟本公司有什么关系。
                if r.get("ncis"):
                    A(f'<span style="color:#0a6b4a;font-size:13px;">　<b>为什么该选{_esc(config.COMPANY)}：</b>'
                      f'{_esc(r["ncis"])}</span><br>')
                if r.get("why"):
                    A(f'<span style="color:#7b8794;font-size:12.5px;">　<b>为什么对招聘有意义：</b>'
                      f'{_esc(r["why"])}</span><br>')
                if r.get("script"):
                    A(f'<span style="color:#7b8794;font-size:12.5px;">　<b>可以这样讲：</b>'
                      f'{_esc(r["script"])}</span><br>')
                meta = []
                if r.get("roles"):
                    meta.append(f'适用：{_esc(r["roles"])}')
                if r.get("source"):
                    meta.append(f'出处：{_esc(r["source"])}')
                if meta:
                    A(f'<span style="color:#a0aab4;font-size:11.5px;">　{"　｜　".join(meta)}</span>')
                A('</td></tr>')
            A('</table></td></tr>')

        if recruit.get("push"):
            A('<tr><td style="padding:12px 16px 16px;">')
            A('<div style="font-size:12px;font-weight:700;color:#b35c00;letter-spacing:.5px;'
              'margin-bottom:10px;padding-top:12px;border-top:1px dashed #e3e8ee;">'
              "▎可以用来对冲其他 offer 的</div>")
            A('<table width="100%" cellpadding="0" cellspacing="0" '
              'style="font-size:13.5px;color:#333;line-height:1.85;">')
            for r in recruit["push"]:
                A('<tr><td style="padding:8px 0 14px 14px;text-indent:-14px;">')
                A(f'<span style="color:#b35c00;">●</span>  '
                  f'<b>候选人手上是{_esc(r.get("against", ""))}的 offer</b><br>')
                if r.get("fact"):
                    A(f'<span style="color:#7b8794;font-size:12.5px;">　<b>事实：</b>'
                      f'{_esc(r["fact"])}</span><br>')
                if r.get("why"):
                    A(f'<span style="color:#7b8794;font-size:12.5px;">　<b>怎么对冲：</b>'
                      f'{_esc(r["why"])}</span><br>')
                meta = []
                if r.get("roles"):
                    meta.append(f'适用：{_esc(r["roles"])}')
                if r.get("source"):
                    meta.append(f'出处：{_esc(r["source"])}')
                if meta:
                    A(f'<span style="color:#a0aab4;font-size:11.5px;">　{"　｜　".join(meta)}</span>')
                A('</td></tr>')
            A('</table></td></tr>')
        A('</table></td></tr>')

    # ── 3. 目录 ──
    shown = [g for g in groups if g["items"]]
    if shown:
        A('<tr><td class="px" style="padding:22px 28px 0;">')
        A('<table width="100%" cellpadding="0" cellspacing="0" style="background:#f8f9fb;border-radius:6px;">')
        A('<tr><td style="padding:14px 16px;">')
        A('<table width="100%" cellpadding="0" cellspacing="0" style="font-size:12.5px;line-height:2;">')
        pairs = [shown[i:i + 2] for i in range(0, len(shown), 2)]
        for pair in pairs:
            A("<tr>")
            for g in pair:
                A(f'<td width="50%"><a href="#{_anchor(g["key"])}" '
                  f'style="color:#1a3a5c;text-decoration:none;">{_esc(g["name"])} '
                  f'<span style="color:#999;">({len(g["items"])})</span></a></td>')
            if len(pair) == 1:
                A('<td width="50%"></td>')
            A("</tr>")
        A('</table></td></tr></table></td></tr>')

    # ── 4. 六线新闻 ──
    for g in shown:
        A('<tr><td class="px" style="padding:26px 28px 0;">')
        A(f'<table width="100%" cellpadding="0" cellspacing="0" id="{_anchor(g["key"])}"><tr>'
          f'<td style="font-size:14px;font-weight:700;color:#1a3a5c;padding-bottom:8px;'
          f'border-bottom:1px solid #dfe4ea;">{_esc(g["name"])}</td></tr></table></td></tr>')
        A('<tr><td class="px" style="padding:0 28px;"><table width="100%" cellpadding="0" cellspacing="0">')
        for it in g["items"]:
            color = IMPACT_COLOR.get(it.get("impact"), "#8c8c8c")
            link = _url(it.get("url"))
            A(f'<tr><td style="padding:12px 0 12px 14px;border-left:2px solid {color};">')
            title = _esc(it["title_zh"])
            if link:
                title = (f'<a href="{link}" style="color:#111;text-decoration:none;">'
                         f'{title}</a>')
            A(f'<div style="font-size:14px;font-weight:600;color:#111;line-height:1.5;">'
              f'{title}</div>')
            tag = " · 已在必读" if it.get("in_top") else ""
            if it.get("_carried"):
                tag += " · 昨日突发接续"
            meta = (f'{_esc(it["source_name"])} · {_esc(it.get("time_str"))} · '
                    f'{_esc(it.get("role"))}{tag}')
            if link:
                meta += (f' · <a href="{link}" style="color:#1a3a5c;'
                         f'text-decoration:none;font-weight:600;">原文</a>')
            A(f'<div style="font-size:11px;color:#999;margin-top:4px;">{meta}</div>')
            if it.get("summary"):
                A(f'<div style="font-size:13px;color:#555;line-height:1.7;margin-top:5px;">'
                  f'{_esc(it["summary"])}</div>')
            A('</td></tr>')
        A('</table></td></tr>')

    # ── FOOTER ──
    A('<tr><td class="px" style="padding:24px 28px 24px;">')
    A('<table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #eef0f3;">')
    A('<tr><td style="padding-top:14px;font-size:11px;color:#bbb;">'
      f'{_esc(config.REPORT_NAME)}播报 · 内部资料，请勿转发外部</td></tr>')
    A('</table></td></tr>')

    A('</table></td></tr></table></body></html>')
    return "".join(P)
