"""日报定时运行（幂等 + 重试 + 告警）

规则（Marcus 定，2026-11-24）：
  - 07:00 启动
  - 内存/磁盘不足等可恢复错误 → 幂等重试 3 次（退避）
  - 08:00 仍未成功 → 飞书告警

幂等：同一天成功发过就不再发（查 runs 表）。
可恢复错误：内存不足、磁盘不足、网络失败、模型 5xx/429。
不可恢复错误：配置错误、模板错误 —— 直接告警，不重试。
"""
import os
import shutil
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import state

import config

BJ = timezone(timedelta(hours=8))
OPEN_ID = config.FEISHU_OPEN_ID
MAX_TRIES = 3
BACKOFF = [60, 180, 300]  # 秒

# 门槛
MIN_DISK_GB = 0.5      # 磁盘至少 500MB
MIN_MEM_MB = 250       # 可用内存至少 250MB


def check_resources():
    """返回 (ok, msg)。磁盘或内存不足视为可恢复。"""
    total, used, free = shutil.disk_usage("/")
    free_gb = free / (1024 ** 3)
    mem = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            mem[k.strip()] = int(v.split()[0]) // 1024  # MB
    avail_mb = mem.get("MemAvailable", 0)

    problems = []
    if free_gb < MIN_DISK_GB:
        problems.append(f"磁盘仅剩 {free_gb:.2f}GB（需 >{MIN_DISK_GB}GB）")
    if avail_mb < MIN_MEM_MB:
        problems.append(f"可用内存仅 {avail_mb}MB（需 >{MIN_MEM_MB}MB）")
    if problems:
        return False, "；".join(problems)
    return True, f"磁盘 {free_gb:.1f}GB / 内存 {avail_mb}MB"


def already_sent(day):
    """今天是否已成功发过日报。"""
    with state.conn() as c:
        r = c.execute(
            "SELECT COUNT(*) n FROM runs WHERE kind='daily' AND ok=1 "
            "AND note LIKE ? AND note NOT LIKE '%[DRY]%'",
            (f"%{day}%",)).fetchone()
        return (r["n"] or 0) > 0


def notify(text):
    """飞书告警。失败不抛（告警失败不能反过来搞崩流程）。"""
    try:
        import alert
        alert.send_text(OPEN_ID, text)
        print("  已发飞书告警")
        return True
    except Exception as e:
        print(f"  ! 告警发送失败: {type(e).__name__} {e}")
        return False


def is_recoverable(err_text):
    """判断是否可重试。"""
    kw = ["MemoryError", "No space left", "ENOSPC", "Timeout", "Connection",
          "HTTPError", "502", "503", "429", "500", "Read timed out",
          "Temporary failure", "reset by peer"]
    return any(k in err_text for k in kw)


def run_once(day, send=True):
    """跑一次日报。返回 (ok, note)。"""
    import main as pipeline
    s = pipeline.run(send=send, day=day)
    if not s.get("kept"):
        return False, f"{day} 无条目入刊（可能是抓取全失败）"
    return True, (f"{day} kept={s['kept']} clusters={s['clusters']} "
                  f"top5={len(s['top5'])}")


def check_mode():
    """08:00 兜底：若今天仍未有成功的日报，则告警。"""
    now = datetime.now(BJ)
    day = now.strftime("%Y-%m-%d")
    print(f"=== 日报兜底检查 {day} {now.strftime('%H:%M:%S')} ===")
    if already_sent(day):
        print("  今日日报已成功发送，无需告警")
        return 0

    # 查最近一次失败原因
    with state.conn() as c:
        r = c.execute("SELECT started_at, note FROM runs WHERE kind='daily' "
                      "ORDER BY id DESC LIMIT 1").fetchone()
    last = ""
    if r:
        ts = datetime.fromtimestamp(r["started_at"], BJ).strftime("%H:%M")
        last = f"{ts} {r['note'] or ''}"
    print(f"  未成功。最后记录：{last}")

    msg = (f"**{config.REPORT_NAME}日报未送达**\n\n"
           f"日期：{day}\n"
           f"当前时间：{now.strftime('%H:%M')}\n\n"
           f"定时已重试，仍未成功。\n\n"
           f"**最后错误**\n<font color=\"grey\">{(last or '无记录')[:300]}</font>\n\n"
           f"日志：`{config.LOG_DIR}/daily.log`")
    notify(msg)
    return 1


def main():
    if "--check" in sys.argv:
        return check_mode()
    send = "--dry" not in sys.argv
    now = datetime.now(BJ)
    day = now.strftime("%Y-%m-%d")
    print(f"=== 日报 {day} 启动 {now.strftime('%H:%M:%S')} ===")

    if send and already_sent(day):
        print(f"  今日日报已成功发送过，跳过（幂等）")
        return 0

    last_err = ""
    for attempt in range(1, MAX_TRIES + 1):
        run_id = state.start_run("daily")
        print(f"\n--- 第 {attempt}/{MAX_TRIES} 次尝试 ---")

        ok_res, res_msg = check_resources()
        if not ok_res:
            print(f"  资源不足：{res_msg}")
            state.finish_run(run_id, False, f"resource: {res_msg}")
            last_err = f"资源不足：{res_msg}"
        else:
            print(f"  资源检查通过：{res_msg}")
            try:
                ok, note = run_once(day, send=send)
                state.finish_run(run_id, ok, ("[DRY] " if not send else "") + note)
                if ok:
                    print(f"  ✓ 完成：{note}")
                    return 0
                last_err = note
                print(f"  ✗ 失败：{note}")
            except Exception as e:
                tb = traceback.format_exc()
                last_err = f"{type(e).__name__}: {e}"
                state.finish_run(run_id, False, last_err)
                print(f"  ✗ 异常：{last_err}")
                print(tb[-400:])
                if not is_recoverable(tb):
                    print("  不可恢复错误，终止重试")
                    break

        if attempt < MAX_TRIES:
            wait = BACKOFF[min(attempt - 1, len(BACKOFF) - 1)]
            print(f"  等待 {wait}s 后重试")
            time.sleep(wait)

    # 全部失败 → 告警
    now2 = datetime.now(BJ)
    msg = (f"**{config.REPORT_NAME}日报失败**\n\n"
           f"日期：{day}\n"
           f"时间：{now2.strftime('%H:%M')}\n"
           f"重试：{MAX_TRIES} 次均未成功\n\n"
           f"**最后错误**\n<font color=\"grey\">{last_err[:300]}</font>\n\n"
           f"日志：`{config.LOG_DIR}/daily.log`")
    print(f"\n!! 全部失败，发告警")
    notify(msg)
    return 1


if __name__ == "__main__":
    state.init()
    sys.exit(main())
