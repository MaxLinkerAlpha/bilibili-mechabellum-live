# -*- coding: utf-8 -*-
"""SQLite 存储层：主播维度 + 场次维度 + 每次轮询快照。"""
import sqlite3, os, json
from config import DB_PATH, DATA_DIR

SCHEMA = """
-- DELETE 模式：数据全部落在单个 .db 文件，便于 GitHub Actions commit 回仓库。
-- WAL 会把最新数据留在 -wal 旁文件，CI 里容易漏提交。
PRAGMA journal_mode=DELETE;
PRAGMA foreign_keys=ON;

-- 主播表：一个 uid 一行，记录来源与累计信息
CREATE TABLE IF NOT EXISTS streamers (
    uid INTEGER PRIMARY KEY,
    uname TEXT NOT NULL DEFAULT '',
    room_id INTEGER,
    source TEXT NOT NULL DEFAULT 'search',   -- search / whitelist / video
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    live_count INTEGER NOT NULL DEFAULT 0,   -- 累计观测到的开播场次数
    note TEXT
);

-- 场次表：一次开播一行。唯一键 (uid, live_time)
-- live_time 是 ISO 字符串（搜索接口）或 unix 时间戳（批量接口），统一转成 ISO 文本
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid INTEGER NOT NULL,
    uname TEXT NOT NULL DEFAULT '',
    room_id INTEGER,
    live_time TEXT NOT NULL,                 -- 开播时间 ISO 'YYYY-MM-DD HH:MM:SS'
    first_seen TEXT NOT NULL,                -- 首次观测到该场的时间
    last_seen TEXT NOT NULL,                 -- 最后一次观测到该场的时间
    end_seen TEXT,                           -- 观测到已下播的时间（可能为空）
    title TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    cate_name TEXT NOT NULL DEFAULT '',
    area_name TEXT NOT NULL DEFAULT '',
    peak_online INTEGER NOT NULL DEFAULT 0,
    hit_keyword TEXT,                        -- 命中的关键词
    hit_fields TEXT NOT NULL DEFAULT '',     -- title / tags / uname / whitelist
    source TEXT NOT NULL DEFAULT 'search',   -- search / whitelist
    UNIQUE(uid, live_time)
);
CREATE INDEX IF NOT EXISTS idx_sessions_uid ON sessions(uid);
CREATE INDEX IF NOT EXISTS idx_sessions_time ON sessions(live_time);
CREATE INDEX IF NOT EXISTS idx_sessions_hit ON sessions(hit_keyword);

-- 轮询日志：每轮一行，便于确认 24h 是否一直在跑
CREATE TABLE IF NOT EXISTS poll_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    status TEXT NOT NULL,                    -- ok / partial / fail
    rooms_found INTEGER DEFAULT 0,
    live_found INTEGER DEFAULT 0,
    uid_checked INTEGER DEFAULT 0,
    detail TEXT NOT NULL DEFAULT ''
);

-- 原始快照表（可选审计）：每次观测到在播写一条
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    uid INTEGER NOT NULL,
    room_id INTEGER,
    title TEXT,
    tags TEXT,
    online INTEGER,
    live_time TEXT,
    source TEXT
);
CREATE INDEX IF NOT EXISTS idx_snap_ts ON snapshots(ts);
"""


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_streamer(conn, uid, uname, room_id, source, now):
    if not uid:
        return
    conn.execute("""
        INSERT INTO streamers(uid, uname, room_id, source, first_seen, last_seen)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(uid) DO UPDATE SET
            uname=CASE WHEN excluded.uname<>'' THEN excluded.uname ELSE streamers.uname END,
            room_id=COALESCE(excluded.room_id, streamers.room_id),
            last_seen=excluded.last_seen,
            source=CASE WHEN streamers.source='search' THEN streamers.source ELSE excluded.source END
    """, (int(uid), uname or '', room_id, source, now, now))


def upsert_session(conn, s, now):
    """s: dict with uid, uname, room_id, live_time, title, tags, cate_name, area_name,
    online, hit_keyword, hit_fields, source"""
    conn.execute("""
        INSERT INTO sessions(uid, uname, room_id, live_time, first_seen, last_seen,
                             title, tags, cate_name, area_name, peak_online,
                             hit_keyword, hit_fields, source)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(uid, live_time) DO UPDATE SET
            last_seen=excluded.last_seen,
            end_seen=NULL,
            title=excluded.title,
            tags=CASE WHEN excluded.tags<>'' THEN excluded.tags ELSE sessions.tags END,
            cate_name=CASE WHEN excluded.cate_name<>'' THEN excluded.cate_name ELSE sessions.cate_name END,
            area_name=CASE WHEN excluded.area_name<>'' THEN excluded.area_name ELSE sessions.area_name END,
            peak_online=MAX(sessions.peak_online, excluded.peak_online),
            hit_keyword=COALESCE(excluded.hit_keyword, sessions.hit_keyword),
            hit_fields=CASE WHEN excluded.hit_fields<>'' THEN excluded.hit_fields ELSE sessions.hit_fields END
    """, (
        int(s['uid']), s.get('uname', ''), s.get('room_id'), s['live_time'], now, now,
        s.get('title', ''), s.get('tags', ''), s.get('cate_name', ''), s.get('area_name', ''),
        int(s.get('online') or 0), s.get('hit_keyword'), s.get('hit_fields', ''), s.get('source', 'search')
    ))


def close_finished_sessions(conn, live_keys, now):
    """把所有不在本轮在播集合里的、尚未结束的场次标记 end_seen。"""
    rows = conn.execute("SELECT id, uid, live_time FROM sessions WHERE end_seen IS NULL").fetchall()
    n = 0
    for r in rows:
        key = (int(r['uid']), r['live_time'])
        if key not in live_keys:
            conn.execute("UPDATE sessions SET end_seen=? WHERE id=?", (now, r['id']))
            n += 1
    return n


def add_snapshot(conn, ts, uid, room_id, title, tags, online, live_time, source):
    conn.execute("""INSERT INTO snapshots(ts, uid, room_id, title, tags, online, live_time, source)
                    VALUES(?,?,?,?,?,?,?,?)""",
                 (ts, int(uid), room_id, title, tags, online, live_time, source))


def add_poll_log(conn, ts, status, rooms_found, live_found, uid_checked, detail):
    conn.execute("""INSERT INTO poll_log(ts, status, rooms_found, live_found, uid_checked, detail)
                    VALUES(?,?,?,?,?,?)""",
                 (ts, status, rooms_found, live_found, uid_checked, detail))


def prune(conn, days):
    conn.execute("DELETE FROM snapshots WHERE ts < datetime('now', ?)", (f'-{days} days',))
    conn.execute("DELETE FROM poll_log WHERE ts < datetime('now', ?)", (f'-{days} days',))
