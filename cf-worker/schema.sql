CREATE TABLE IF NOT EXISTS streamers (
  uid INTEGER PRIMARY KEY,
  uname TEXT NOT NULL DEFAULT '',
  room_id INTEGER,
  source TEXT NOT NULL DEFAULT 'search',
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  live_count INTEGER NOT NULL DEFAULT 0,
  note TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  uid INTEGER NOT NULL,
  uname TEXT NOT NULL DEFAULT '',
  room_id INTEGER,
  live_time TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  end_seen TEXT,
  title TEXT NOT NULL DEFAULT '',
  tags TEXT NOT NULL DEFAULT '',
  cate_name TEXT NOT NULL DEFAULT '',
  area_name TEXT NOT NULL DEFAULT '',
  peak_online INTEGER NOT NULL DEFAULT 0,
  hit_keyword TEXT,
  hit_fields TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'search',
  UNIQUE(uid, live_time)
);
CREATE INDEX IF NOT EXISTS idx_sessions_uid ON sessions(uid);
CREATE INDEX IF NOT EXISTS idx_sessions_time ON sessions(live_time);
CREATE INDEX IF NOT EXISTS idx_sessions_hit ON sessions(hit_keyword);

CREATE TABLE IF NOT EXISTS poll_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  status TEXT NOT NULL,
  rooms_found INTEGER DEFAULT 0,
  live_found INTEGER DEFAULT 0,
  uid_checked INTEGER DEFAULT 0,
  detail TEXT NOT NULL DEFAULT ''
);

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
