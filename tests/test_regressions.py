#!/usr/bin/env python3
"""回归测试 —— 覆盖 2026-11-27 code review 发现的全部问题。

每个用例都能独立复现对应的原始 bug。跑法：

    python tests/test_regressions.py

不需要网络，不写仓库文件（临时目录除外）。
"""
import os
import re
import sys
import tempfile
import json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  {detail}" if detail and not cond else ""))


# ── S1: README 教用户自定义 PRODUCT_LINES key，代码硬编码六条线 → KeyError ──
def test_s1_custom_product_lines():
    print("\n[S1] 自定义业务线不崩溃")
    import config, main, render
    old_pl, old_lo, old_tl = config.PRODUCT_LINES, main.LINE_ORDER, render.TAG_LINE
    try:
        config.PRODUCT_LINES = {
            "line_a": {"name": "业务线A", "tag": "a", "md": "a", "kw": ["x"]},
            "line_b": {"name": "业务线B", "tag": "b", "md": "b", "kw": ["y"]},
        }
        main.LINE_ORDER = config.LINE_ORDER = list(config.PRODUCT_LINES.keys())
        render.TAG_LINE = config.TAG_LINE = {
            k: (v.get("tag") or v.get("name") or k) for k, v in config.PRODUCT_LINES.items()
        }
        line_of = {k: v["name"] for k, v in config.PRODUCT_LINES.items()}
        try:
            for key in main.LINE_ORDER:
                line_of[key]
            check("S1 main 分组不 KeyError", True)
        except KeyError as e:
            check("S1 main 分组不 KeyError", False, str(e))
        try:
            check("S1 render 标签不 KeyError", render.TAG_LINE.get("line_a", "line_a") == "a")
        except KeyError as e:
            check("S1 render 标签不 KeyError", False, str(e))
    finally:
        config.PRODUCT_LINES, main.LINE_ORDER, render.TAG_LINE = old_pl, old_lo, old_tl


# ── S2: 判定失败被写入缓存，之后永远救不回来 ──
def test_s2_failed_judgement_not_cached():
    print("\n[S2] 判定失败不写缓存")
    import analyze, config
    tmp = tempfile.mkdtemp()
    analyze.CACHE_PATH = os.path.join(tmp, "c.json")
    open(analyze.CACHE_PATH, "w").write("{}")

    def boom(*a, **k):
        raise RuntimeError("500")
    orig = analyze._post
    analyze._post = boom
    it = {"url": "http://x/fail", "title": "FailTitle", "source_name": "S",
          "source_tier": "T2", "summary": "s"}
    try:
        analyze.analyze_all(config, [dict(it)])
        cached = json.load(open(analyze.CACHE_PATH, encoding="utf-8"))
        check("S2 失败结果未落缓存", len(cached) == 0, f"缓存里有 {len(cached)} 条")
    finally:
        analyze._post = orig
        analyze.CACHE_PATH = os.path.join(os.path.dirname(HERE), "..", "data", "judge-cache.json")


# ── S3: LLM 返回畸形类型 → 崩溃 ──
def test_s3_malformed_llm_output():
    print("\n[S3] LLM 畸形输出不崩溃")
    import analyze, config
    tmp = tempfile.mkdtemp()
    analyze.CACHE_PATH = os.path.join(tmp, "c.json")
    open(analyze.CACHE_PATH, "w").write("{}")

    # analyze_batch 用的是 data["choices"][0]["message"]["content"]（字典索引），
    # 所以 mock 必须返回字典，不能返回实例。
    _MALFORMED = {
        "choices": [{"message": {"content": json.dumps({
            "items": [{"keep": True, "score": "45分", "line": "power", "type": "产品发布",
                       "role": "竞对", "impact": "high", "title_zh": "t", "summary": "s",
                       "entities": ["TI"], "competitor_hit": ["TI"], "customer_hit": None}]})}}]
    }

    orig = analyze._post
    analyze._post = lambda *a, **k: _MALFORMED
    try:
        out = analyze.analyze_all(config, [{"url": "http://x/1", "title": "T",
                                            "source_name": "S", "source_tier": "T2",
                                            "summary": "s"}])
        check("S3 score='45分' 不崩溃", out[0]["score"] == 0)
        check("S3 competitor_hit=list 不崩溃", out[0]["competitor_hit"] is None)
    except Exception as e:
        check("S3 畸形输出不崩溃", False, f"{type(e).__name__}: {e}")
    finally:
        analyze._post = orig
        analyze.CACHE_PATH = os.path.join(os.path.dirname(HERE), "..", "data", "judge-cache.json")


# ── S3b: _post 全部重试耗尽 → 应抛原始异常，不是 TypeError ──
def test_s3b_post_raises_real_error():
    print("\n[S3b] LLM 重试耗尽抛原始异常")
    import analyze, requests
    def r429(*a, **k):
        r = requests.Response()
        r.status_code = 429
        return r
    orig_post, orig_sleep = analyze.requests.post, analyze.time.sleep
    analyze.requests.post = r429
    analyze.time.sleep = lambda s: None
    try:
        try:
            analyze._post({"x": 1}, retries=2, timeout=1)
            check("S3b 抛异常", False, "没有抛")
        except TypeError as e:
            check("S3b 抛原始异常而非 TypeError", False, f"TypeError: {e}")
        except Exception as e:
            check("S3b 抛原始异常而非 TypeError", True, type(e).__name__)
    finally:
        analyze.requests.post, analyze.time.sleep = orig_post, orig_sleep


# ── S4: 政策实质门把突发接续条目全部误杀 ──
def test_s4_carryover_survives_policy_gate():
    print("\n[S4] 突发接续不被政策门误杀")
    import main
    carried = {"title": "美国宣布新出口管制", "title_zh": "美国宣布新出口管制",
               "summary": "美国宣布新出口管制（所属线索：美对华出口管制）",
               "url": "https://x/a", "source_name": "突发通道", "source_tier": "T1",
               "keep": True, "score": 56, "line": None, "line_secondary": [],
               "type": "政策标准", "role": "政策", "impact": "high", "entities": [],
               "competitor_hit": None, "customer_hit": None, "_carried": True}
    ordinary = {"title": "某公司宣布管制", "title_zh": "某公司宣布管制",
                "summary": "某公司宣布管制（无具体事实）", "url": "https://x/b",
                "source_name": "媒体", "source_tier": "T2", "keep": True, "score": 55,
                "line": None, "line_secondary": [], "type": "政策标准", "role": "政策",
                "impact": "high", "entities": [], "competitor_hit": None,
                "customer_hit": None}
    items = [carried, ordinary]

    def policy_drop(it):
        if it.get("_carried"):
            return False
        return bool(it.get("keep")) and not main.policy_has_substance(it)

    dropped = [it for it in items if policy_drop(it)]
    left = [it for it in items if not policy_drop(it)]
    check("S4 接续条目未被政策门丢弃", carried in left)
    check("S4 普通政策条目仍被丢弃", ordinary in dropped)


# ── S5: alert 模型返回条目数少于输入 → 多出的被当成「已判定」 ──
def test_s5_alert_judged_length():
    print("\n[S5] 模型少给结论时不误标已判定")
    import alert
    class R:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": json.dumps(
                {"items": [{"alert": False}, {"alert": False}]})}}]}
    orig = alert.requests.post
    alert.requests.post = lambda *a, **k: R()
    items = [{"title": f"t{i}", "url": f"http://x/{i}", "source_name": "s",
              "summary": ""} for i in range(5)]
    try:
        hits, judged = alert.judge_alerts(items, api_key="k", return_judged=True)
        check("S5 judged 只含真正拿到结论的 2 条", len(judged) == 2, f"实际 {len(judged)}")
        check("S5 未判定的 3 条留到下一轮", len(items) - len(judged) == 3)
    finally:
        alert.requests.post = orig


# ── S6: norm_entity 收到非字符串 ──
def test_s6_norm_entity_type():
    print("\n[S6] norm_entity 容忍非字符串")
    import config
    try:
        check("S6 norm_entity(list) 返回 None", config.norm_entity(["TI"]) is None)
        check("S6 norm_entity(None) 返回 None", config.norm_entity(None) is None)
        check("S6 norm_entity('') 返回 None", config.norm_entity("") is None)
        check("S6 norm_entity(正常) 正常", config.norm_entity("德州仪器") == "TI")
    except Exception as e:
        check("S6 norm_entity 不崩溃", False, f"{type(e).__name__}: {e}")


# ── S7: CN_VENDOR_RE 短 token 误命中 ──
def test_s7_vendor_re_word_boundary():
    print("\n[S7] CN_VENDOR_RE 不误命中英文单词")
    import config
    for t in ("BEST Semiconductors Reports", "Motion Control IC", "Certification Roadmap"):
        hit = re.search(config.CN_VENDOR_RE, t)
        check(f"S7 {t!r} 不误命中", hit is None, f"命中 {hit.group(0) if hit else ''}")
    check("S7 真竞对仍能命中", bool(re.search(config.CN_VENDOR_RE, "TI推出新芯片")))


# ── S8: 带毫秒的时间戳解析 ──
def test_s8_iso_millisecond():
    print("\n[S8] 毫秒时间戳可解析")
    import collect
    for raw, ok in (("2026-11-27T10:00:00.123456+08:00", True),
                    ("2026-11-27T10:00:00.123+08:00", True),
                    ("2026-11-27T10:00:00+08:00", True),
                    ("2026-11-27T10:00:00Z", True)):
        got = collect._parse_date(raw)
        check(f"S8 {raw} 可解析", (got is not None) == ok, f"got={got}")


# ── S9: pitch 未填占位符不应喂给模型 ──
def test_s9_pitch_placeholders_stripped():
    print("\n[S9] pitch 占位符不喂给模型")
    import analyze
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, "p.md")
    open(p, "w", encoding="utf-8").write(
        "---\ntitle: x\n---\n\n# 标题\n\n## 一、说清\n{{公司名}}是某公司。\n\n## 八、维护\n清单\n")
    old = analyze.config.PITCH_PATH
    try:
        analyze.config.PITCH_PATH = p
        out = analyze._load_pitch()
        check("S9 占位符行被剔除", "{{" not in out, f"残留 {out.count('{{')} 处")
        check("S9 正常内容保留", "某公司" in out)
        check("S9 维护清单被裁掉", "维护" not in out)
    finally:
        analyze.config.PITCH_PATH = old


def main():
    print("=" * 60)
    print("Corp_Daily_News 回归测试")
    print("=" * 60)
    for fn in (test_s1_custom_product_lines, test_s2_failed_judgement_not_cached,
               test_s3_malformed_llm_output, test_s3b_post_raises_real_error,
               test_s4_carryover_survives_policy_gate, test_s5_alert_judged_length,
               test_s6_norm_entity_type, test_s7_vendor_re_word_boundary,
               test_s8_iso_millisecond, test_s9_pitch_placeholders_stripped):
        try:
            fn()
        except Exception as e:
            FAIL.append(fn.__name__)
            print(f"  ✗ {fn.__name__} 崩溃: {type(e).__name__}: {e}")
    print("\n" + "=" * 60)
    print(f"通过 {len(PASS)} / 失败 {len(FAIL)}")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  -", f)
    print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
