# -*- coding: utf-8 -*-
"""把本地 SQLite 的 streamers/sessions/poll_log/snapshots 导出成 D1 可执行 INSERT SQL。
用法: python scripts/export_sqlite_to_d1.py [sqlite路径] [输出sql路径]
"""
import sqlite3, sys, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "..", "data", "live.db")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BASE, "seed.sql")

TABLES = {
    "streamers": ["uid", "uname", "room_id", "source", "first_seen", "last_seen", "live_count", "note"],
    "sessions": ["id", "uid", "uname", "room_id", "live_time", "first_seen", "last_seen", "end_seen",
                 "title", "tags", "cate_name", "area_name", "peak_online", "hit_keyword", "hit_fields", "source"],
    "poll_log": ["id", "ts", "status", "rooms_found", "live_found", "uid_checked", "detail"],
    "snapshots": ["id", "ts", "uid", "room_id", "title", "tags", "online", "live_time", "source"],
}

def q(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"

conn = sqlite3.connect(SRC)
conn.row_factory = sqlite3.Row
lines = ["-- 从本地 SQLite 迁移到 Cloudflare D1，由 export_sqlite_to_d1.py 生成", ""]
counts = {}
for table, cols in TABLES.items():
    rows = conn.execute(f"SELECT {','.join(cols)} FROM {table}").fetchall()
    counts[table] = len(rows)
    lines.append(f"-- {table}: {len(rows)} rows")
    for r in rows:
        vals = ",".join(q(r[c]) for c in cols)
        lines.append(f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({vals});")
    lines.append("")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("导出完成:", OUT)
print("行数:", counts)
