// D1 存储层。用 batch 一次提交，减少 subrequest 与往返。
import { KEYWORD_ALIASES } from "./config.js";

function hitTest(text) {
  const t = String(text ?? "").toLowerCase();
  for (const kw of KEYWORD_ALIASES) if (t.includes(kw.toLowerCase())) return kw;
  return null;
}

export function makeSession(uid, uname, roomId, liveTime, title, tags, extraFields, online, cate, area, source) {
  const fields = [];
  if (hitTest(title)) fields.push("title");
  if (hitTest(tags)) fields.push("tags");
  if (hitTest(uname)) fields.push("uname");
  if (extraFields) for (const f of String(extraFields).split(",")) if (f && !fields.includes(f)) fields.push(f);
  return {
    uid: Number(uid), uname: uname || "", room_id: roomId || null, live_time: liveTime,
    title: title || "", tags: tags || "", cate_name: cate || "", area_name: area || "",
    online: Number(online) || 0,
    hit_keyword: hitTest(`${title || ""} ${tags || ""}`),
    hit_fields: [...new Set(fields)].join(","),
    source: source || "search",
  };
}

export async function persist(db, { now, sessions, liveKeys, roomsFound, uidChecked, errors, notes }) {
  const stmts = [];
  const seen = new Set();

  for (const s of sessions) {
    stmts.push(db.prepare(`
      INSERT INTO streamers(uid,uname,room_id,source,first_seen,last_seen)
      VALUES(?,?,?,?,?,?)
      ON CONFLICT(uid) DO UPDATE SET
        uname=CASE WHEN excluded.uname<>'' THEN excluded.uname ELSE streamers.uname END,
        room_id=COALESCE(excluded.room_id, streamers.room_id),
        last_seen=excluded.last_seen
    `).bind(s.uid, s.uname, s.room_id, s.source, now, now));

    stmts.push(db.prepare(`
      INSERT INTO sessions(uid,uname,room_id,live_time,first_seen,last_seen,title,tags,
        cate_name,area_name,peak_online,hit_keyword,hit_fields,source)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(uid,live_time) DO UPDATE SET
        last_seen=excluded.last_seen, end_seen=NULL, title=excluded.title,
        tags=CASE WHEN excluded.tags<>'' THEN excluded.tags ELSE sessions.tags END,
        cate_name=CASE WHEN excluded.cate_name<>'' THEN excluded.cate_name ELSE sessions.cate_name END,
        area_name=CASE WHEN excluded.area_name<>'' THEN excluded.area_name ELSE sessions.area_name END,
        peak_online=MAX(sessions.peak_online, excluded.peak_online),
        hit_keyword=COALESCE(excluded.hit_keyword, sessions.hit_keyword),
        hit_fields=CASE WHEN excluded.hit_fields<>'' THEN excluded.hit_fields ELSE sessions.hit_fields END
    `).bind(s.uid, s.uname, s.room_id, s.live_time, now, now, s.title, s.tags, s.cate_name,
            s.area_name, s.online, s.hit_keyword, s.hit_fields, s.source));

    const sk = `${s.uid}|${s.live_time}`;
    if (!seen.has(sk)) {
      seen.add(sk);
      stmts.push(db.prepare(`
        INSERT INTO snapshots(ts,uid,room_id,title,tags,online,live_time,source)
        VALUES(?,?,?,?,?,?,?,?)
      `).bind(now, s.uid, s.room_id, s.title, s.tags, s.online, s.live_time, s.source));
    }
  }

  // 关闭已下播场次
  const open = await db.prepare("SELECT id,uid,live_time FROM sessions WHERE end_seen IS NULL").all();
  for (const r of open.results || []) {
    if (!liveKeys.has(`${r.uid}|${r.live_time}`)) {
      stmts.push(db.prepare("UPDATE sessions SET end_seen=? WHERE id=?").bind(now, r.id));
    }
  }

  const status = errors.length ? "partial" : "ok";
  stmts.push(db.prepare(`
    INSERT INTO poll_log(ts,status,rooms_found,live_found,uid_checked,detail)
    VALUES(?,?,?,?,?,?)
  `).bind(now, status, roomsFound, liveKeys.size, uidChecked, [...errors, ...notes].join(";")));

  if (stmts.length) await db.batch(stmts);
  return { status, liveCount: liveKeys.size };
}
