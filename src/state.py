"""增量状态层：SQLite

作用：
1. seen_urls —— 已见过的 URL（防重复判定）
2. http_cache —— 每个信源的 ETag / Last-Modified（条件请求，304 不花流量）
3. alerts —— 已推送的突发（防重复打扰）
4. runs —— 运行记录（供幂等重试与告警判断）

单文件 SQLite，无外部依赖。
"""
import os
import sqlite3
import time
from contextlib import contextmanager

import config

DB_PATH = config.DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_urls (
  url_key     TEXT PRIMARY KEY,
  url         TEXT NOT NULL,
  title       TEXT,
  source_id   TEXT,
  first_seen  INTEGER NOT NULL,
  judged      INTEGER NOT NULL DEFAULT 0,
  alerted     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS seen_first ON seen_urls (first_seen DESC);

CREATE TABLE IF NOT EXISTS http_cache (
  source_id     TEXT PRIMARY KEY,
  etag          TEXT,
  last_modified TEXT,
  updated_at    INTEGER
);

CREATE TABLE IF NOT EXISTS alerts (
  url_key   TEXT PRIMARY KEY,
  sent_at   INTEGER NOT NULL,
  rule      TEXT,
  title     TEXT
);

CREATE TABLE IF NOT EXISTS runs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  kind        TEXT NOT NULL,
  started_at  INTEGER NOT NULL,
  finished_at INTEGER,
  ok          INTEGER,
  note        TEXT
);
CREATE INDEX IF NOT EXISTS runs_kind ON runs (kind, started_at DESC);

-- 日报已刊出条目（跨天去重唯一依据）
-- 与 seen_urls 分离：seen_urls 由 poll 每 10 分钟写入，不能当作「已发过」的证据
CREATE TABLE IF NOT EXISTS daily_items (
  url_key   TEXT PRIMARY KEY,
  day       TEXT NOT NULL,
  title     TEXT,
  subject   TEXT,
  source_id TEXT,
  sent_at   INTEGER NOT NULL,
  is_baseline INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS daily_day ON daily_items (day);
"""


@contextmanager
def conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(daily_items)")}
        if "is_baseline" not in cols:
            c.execute("ALTER TABLE daily_items ADD COLUMN "
                      "is_baseline INTEGER NOT NULL DEFAULT 0")
        # 突发表补审计字段：过去只存 rule/title，事后无法复盘「当时怎么判的」
        acols = {r["name"] for r in c.execute("PRAGMA table_info(alerts)")}
        for col, decl in (("subject", "TEXT"), ("headline", "TEXT"),
                          ("detail", "TEXT"), ("urgency", "TEXT"),
                          ("source_id", "TEXT"), ("topic", "TEXT")):
            if col not in acols:
                c.execute(f"ALTER TABLE alerts ADD COLUMN {col} {decl}")


def url_key(url):
    import re
    u = (url or "").strip().lower()
    u = re.sub(r"[?#].*$", "", u)
    u = re.sub(r"^https?://(www\.)?", "", u)
    return u.rstrip("/")


def is_seen(url):
    with conn() as c:
        return c.execute("SELECT 1 FROM seen_urls WHERE url_key=?",
                         (url_key(url),)).fetchone() is not None


def mark_seen(items, source_id=None):
    """批量登记。返回真正新增的条目。"""
    now = int(time.time())
    new_items = []
    with conn() as c:
        for it in items:
            k = url_key(it.get("url"))
            if not k:
                continue
            row = c.execute("SELECT 1 FROM seen_urls WHERE url_key=?", (k,)).fetchone()
            if row:
                continue
            c.execute("INSERT INTO seen_urls (url_key,url,title,source_id,first_seen) "
                      "VALUES (?,?,?,?,?)",
                      (k, it.get("url", ""), it.get("title", "")[:200],
                       source_id or it.get("source_id"), now))
            new_items.append(it)
    return new_items


def mark_judged(url):
    with conn() as c:
        c.execute("UPDATE seen_urls SET judged=1 WHERE url_key=?", (url_key(url),))


def filter_unseen(items):
    """返回尚未见过的条目，但不写入 seen_urls。

    与 mark_seen 的区别：判定失败时不能把条目吞掉。原流程是「先标已见、
    再判定」，一旦判定抛错或批次被截断，那些条目永远不会重来。
    """
    if not items:
        return []
    keys = [url_key(it.get("url")) for it in items]
    keys = [k for k in keys if k]
    if not keys:
        return []
    with conn() as c:
        seen = set()
        for i in range(0, len(keys), 400):
            chunk = keys[i:i + 400]
            q = "SELECT url_key FROM seen_urls WHERE url_key IN (%s)" %                 ",".join("?" * len(chunk))
            seen.update(r["url_key"] for r in c.execute(q, chunk))
    return [it for it in items if url_key(it.get("url")) not in seen]


def recent_alerts(hours=24):
    """最近 N 小时已推送的突发，用于事件级冷却。"""
    import json
    with conn() as c:
        rows = c.execute(
            "SELECT url_key,title,headline,rule,urgency,subject,source_id,"
            "topic,sent_at FROM alerts WHERE sent_at >= ? ORDER BY sent_at DESC",
            (int(time.time()) - hours * 3600,)).fetchall()
    out = []
    for r in rows:
        try:
            subj = set(json.loads(r["subject"] or "[]"))
        except Exception:
            subj = set()
        out.append({"url_key": r["url_key"], "title": r["title"] or "",
                    "headline": r["headline"] or r["title"] or "",
                    "rule": r["rule"], "urgency": r["urgency"],
                    "subject": subj, "source_id": r["source_id"],
                    "topic": r["topic"], "sent_at": r["sent_at"]})
    return out


def already_alerted(url):
    with conn() as c:
        return c.execute("SELECT 1 FROM alerts WHERE url_key=?",
                         (url_key(url),)).fetchone() is not None


def record_alert(url, rule, title, headline=None, detail=None,
                 urgency=None, subject=None, source_id=None, topic=None):
    import json
    subj = json.dumps(sorted(subject), ensure_ascii=False) if subject else None
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO alerts "
                  "(url_key,sent_at,rule,title,headline,detail,urgency,subject,"
                  "source_id,topic) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (url_key(url), int(time.time()), rule, (title or "")[:200],
                   (headline or "")[:200], (detail or "")[:400],
                   urgency, subj, source_id, (topic or "")[:60] or None))
        c.execute("UPDATE seen_urls SET alerted=1 WHERE url_key=?", (url_key(url),))


def get_http(source_id):
    with conn() as c:
        r = c.execute("SELECT etag,last_modified FROM http_cache WHERE source_id=?",
                      (source_id,)).fetchone()
        return (r["etag"], r["last_modified"]) if r else (None, None)


def set_http(source_id, etag, last_modified):
    with conn() as c:
        c.execute("INSERT INTO http_cache (source_id,etag,last_modified,updated_at) "
                  "VALUES (?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET "
                  "etag=excluded.etag, last_modified=excluded.last_modified, "
                  "updated_at=excluded.updated_at",
                  (source_id, etag, last_modified, int(time.time())))


def start_run(kind):
    with conn() as c:
        cur = c.execute("INSERT INTO runs (kind,started_at) VALUES (?,?)",
                        (kind, int(time.time())))
        return cur.lastrowid


def finish_run(run_id, ok, note=""):
    with conn() as c:
        c.execute("UPDATE runs SET finished_at=?,ok=?,note=? WHERE id=?",
                  (int(time.time()), 1 if ok else 0, (note or "")[:500], run_id))


def recent_failures(kind, since_ts):
    with conn() as c:
        r = c.execute("SELECT COUNT(*) n FROM runs WHERE kind=? AND started_at>=? "
                      "AND ok=0", (kind, since_ts)).fetchone()
        return r["n"] if r else 0


def stats():
    with conn() as c:
        out = {}
        for t in ("seen_urls", "alerts", "runs"):
            out[t] = c.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"]
        out["seen_24h"] = c.execute(
            "SELECT COUNT(*) n FROM seen_urls WHERE first_seen>=?",
            (int(time.time()) - 86400,)).fetchone()["n"]
        return out



# ── 日报历史（跨天去重）─────────────────────────────────────────────────
def daily_history(before_day, days=7):
    """before_day 之前 days 天内已刊出条目 [{day,title,subject:set}]。"""
    import json
    with conn() as c:
        rows = c.execute(
            "SELECT url_key,day,title,subject FROM daily_items "
            "WHERE (day < ? AND day >= date(?, ?)) OR is_baseline=1 "
            "ORDER BY day DESC",
            (before_day, before_day, f"-{days} days")).fetchall()
    out = []
    for r in rows:
        try:
            subj = set(json.loads(r["subject"] or "[]"))
        except Exception:
            subj = set()
        out.append({"url_key": r["url_key"], "day": r["day"],
                    "title": r["title"] or "", "subject": subj})
    return out


def daily_has(url):
    with conn() as c:
        return c.execute("SELECT 1 FROM daily_items WHERE url_key=?",
                         (url_key(url),)).fetchone() is not None


def record_daily(items, day, baseline=False):
    """登记当日刊出条目（先清同日旧记录，保证幂等）。

    baseline=True 用于新建信源的首次基线：这些条目从未刊出过，但属于
    历史存量，必须在「装库那一刻」就标记为已见，否则首期会把官网全部
    历史新品一次性灌进日报。
    """
    import json
    now = int(time.time())
    with conn() as c:
        if baseline:
            c.execute("DELETE FROM daily_items WHERE is_baseline=1")
        else:
            c.execute("DELETE FROM daily_items WHERE day=? AND is_baseline=0", (day,))
        for it in items:
            k = url_key(it.get("url"))
            if not k:
                continue
            c.execute(
                "INSERT OR REPLACE INTO daily_items "
                "(url_key,day,title,subject,source_id,sent_at,is_baseline) "
                "VALUES (?,?,?,?,?,?,?)",
                (k, day, (it.get("title_zh") or it.get("title") or "")[:200],
                 json.dumps(sorted(it.get("_subject") or []), ensure_ascii=False),
                 it.get("source_id"), now, 1 if baseline else 0))

if __name__ == "__main__":
    init()
    print(stats())
