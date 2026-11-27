"""突发即时轮询（每 10 分钟一次）

流程：
  1. 对 11 个源做条件请求（ETag / If-Modified-Since）
  2. 304 → 直接跳过，0 成本
  3. 200 → 与 state 里的已见 URL 比对，只有新 URL 进下一步
  4. LLM 判定是否突发（只判新条目）
  5. 命中 → 飞书推送；已推过的不再推

单独跑一次：python3 poll.py
常驻循环：python3 poll.py --loop 600
"""
import os
import sys
import time
import traceback
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import alert
import collect
import config
import dedup
import main
import state

OPEN_ID = config.FEISHU_OPEN_ID
INTERVAL = 600  # 10 分钟


def _find_dup(h, subj, topic, recent):
    """24 小时内是否已推过同一事件 / 同一线索。

    两道判定，任一命中即冷却：
      1. topic 相同 —— 模型给的稳定线索标签。政策性新闻（出口管制、关税）
         抽不出实体、字面又千差万别，只能靠这一层。
      2. 同事件 —— 主体交集 + 标题字面相似（dedup.same_event），兜住
         模型 topic 给得不一致的漏网。
    """
    if topic:
        for prev in recent:
            if (prev.get("topic") or "").strip() == topic:
                return {**prev, "by": "topic"}
    for prev in recent:
        if dedup.same_event(subj, h.get("headline") or "",
                            prev.get("subject"), prev.get("headline") or ""):
            return {**prev, "by": "event"}
    return None


def one_round(verbose=True, dry=False):
    """跑一轮。返回 {'new': n, 'alerts': n, 'pushed': n, 'errors': n, ...}

    关键顺序（2026-11-26 修）：先判定、后登记。
    原流程是 state.mark_seen() 先标已见再判定，导致
      ① judge_alerts 内部 max_n 截断的余量
      ② 判定抛错的那一批
    全部永久沉底 —— 标记为已见但从未判定，下一轮不会再进来。
    实测已静默丢失 25 条，含纳芯微并购、锴威特收购两条 A 类。
    """
    t0 = time.time()
    res = collect.collect_all(config.SOURCES, verbose=verbose, use_cache=True)

    raw_new = []
    errors = 0
    not_mod = 0
    for r in res:
        if not r["ok"]:
            errors += 1
            continue
        if r.get("not_modified"):
            not_mod += 1
            continue
        raw_new.extend(r["items"])

    fresh = main.dedupe_url(raw_new) if raw_new else []
    fresh = state.filter_unseen(fresh)

    summary = {"new": len(fresh), "alerts": 0, "pushed": 0, "errors": errors,
               "not_modified": not_mod, "deferred": 0, "cooldown": 0,
               "ms": int((time.time() - t0) * 1000)}

    if not fresh:
        if verbose:
            print(f"  本轮无新条目（304={not_mod}, 错误={errors}, {summary['ms']}ms）")
        return summary

    if verbose:
        print(f"  新条目 {len(fresh)} 条，进入突发判定")

    hits, judged = alert.judge_alerts(fresh, api_key=os.environ.get("DEEPSEEK_API_KEY"),
                                     return_judged=True)
    summary["alerts"] = len(hits)

    # 判定过的才登记为已见；未判定的留在下一轮（不写 seen_urls）
    if len(judged) < len(fresh):
        summary["deferred"] = len(fresh) - len(judged)
        if verbose:
            print(f"    本轮只判定 {len(judged)}/{len(fresh)} 条，"
                  f"余 {summary['deferred']} 条留到下一轮")
    if not dry:
        state.mark_seen(judged, None)

    # 事件级冷却：同一事件 24 小时内只推第一条（SPEC §0.2 去重红线）
    recent = state.recent_alerts(hours=24)
    for h in hits:
        it = h["item"]
        if state.already_alerted(it.get("url")):
            if verbose:
                print(f"    跳过（已推送过）：{h['headline'][:30]}")
            continue
        subj = dedup.subject_key(it)
        topic = (h.get("topic") or "").strip()
        dup = _find_dup(h, subj, topic, recent)
        if dup:
            summary["cooldown"] += 1
            if verbose:
                ts = datetime.fromtimestamp(dup["sent_at"]).strftime("%m-%d %H:%M")
                why = "同线索" if dup.get("by") == "topic" else "同事件"
                print(f"    冷却（{why}，已于 {ts} 推过 "
                      f"「{(dup.get('topic') or dup['headline'])[:16]}」）："
                      f"{h['headline'][:24]}")
            state.mark_judged(it.get("url"))
            continue
        if dry:
            summary["pushed"] += 1
            recent.append({"url_key": it.get("url"), "headline": h.get("headline") or "",
                           "subject": subj, "topic": topic,
                           "sent_at": int(time.time())})
            if verbose:
                print(f"    [DRY] 会推送：{h['headline'][:44]}")
            continue
        ok = alert.push(h, OPEN_ID)
        if ok:
            state.record_alert(it.get("url"), h.get("rule") or "",
                               it.get("title", ""), headline=h.get("headline"),
                               detail=h.get("detail"), urgency=h.get("urgency"),
                               subject=subj, source_id=it.get("source_id"),
                               topic=topic)
            state.mark_judged(it.get("url"))
            summary["pushed"] += 1
            recent.append({"url_key": it.get("url"), "headline": h.get("headline") or "",
                           "subject": subj, "topic": topic,
                           "sent_at": int(time.time())})
            # 多推几条时间隔一下，避免飞书限流
            time.sleep(1.5)

    return summary


def tick(verbose=True, dry=False):
    """跑一轮并写入 runs 记录（cron 走这里，保证可观测）。"""
    if dry:
        return one_round(verbose=verbose, dry=True)
    run_id = state.start_run("poll")
    try:
        s = one_round(verbose=verbose)
        state.finish_run(
            run_id, True,
            f"new={s['new']} alerts={s['alerts']} pushed={s['pushed']} "
            f"cool={s['cooldown']} defer={s['deferred']}")
        return s
    except Exception as e:
        tb = traceback.format_exc()
        state.finish_run(run_id, False, f"{type(e).__name__}: {e}")
        print(f"  !! 本轮异常：{type(e).__name__}: {e}")
        print(tb[-500:])
        raise


def loop(interval=INTERVAL):
    """常驻循环。单轮失败不退出。"""
    print(f"=== 突发轮询启动，间隔 {interval}s ===")
    while True:
        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{started}] 轮询")
        try:
            s = tick(verbose=True)
            print(f"  完成：新 {s['new']} / 命中 {s['alerts']} / 推送 {s['pushed']} "
                  f"/ 冷却 {s['cooldown']} / 顺延 {s['deferred']} ({s['ms']}ms)")
        except Exception:
            pass
        time.sleep(interval)


if __name__ == "__main__":
    state.init()
    if "--loop" in sys.argv:
        i = sys.argv.index("--loop")
        iv = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else INTERVAL
        loop(iv)
    elif "--dry" in sys.argv:
        s = tick(verbose=True, dry=True)
        print(s)
    else:
        s = tick(verbose=True)
        print(s)
