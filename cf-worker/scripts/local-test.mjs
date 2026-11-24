// 本地逻辑测试：用内存 mock 模拟 D1 + 真实 B站 API，验证 collect / 报表 / CSV。
// 不启动 workerd，绕开 Windows 上 wrangler dev 的 email-store DO 问题。
// 用法: node scripts/local-test.mjs
import { KEYWORD, WHITELIST_UIDS } from "../src/config.js";
import { initSession, searchLive, bulkStatus, clean } from "../src/bili.js";
import { makeSession, persist } from "../src/store.js";

// ---- mock D1 ----
function makeMockDB() {
  const rows = { streamers: new Map(), sessions: new Map(), poll_log: [], snapshots: [] };
  const parse = (sql, args) => {
    if (/INSERT INTO streamers/i.test(sql)) {
      const [uid, uname, room_id, source, first, last] = args;
      const old = rows.streamers.get(uid);
      rows.streamers.set(uid, { uid, uname: uname || old?.uname || "", room_id: room_id ?? old?.room_id, source, first_seen: first, last_seen: last });
    } else if (/INSERT INTO sessions/i.test(sql)) {
      const [uid, uname, room_id, live_time, first, last, title, tags, cate, area, online, hit_kw, hit_fields, source] = args;
      const k = `${uid}|${live_time}`;
      const old = rows.sessions.get(k);
      rows.sessions.set(k, { uid, uname, room_id, live_time, first_seen: first, last_seen: last,
        title, tags: tags || old?.tags || "", cate_name: cate || old?.cate_name || "",
        area_name: area || old?.area_name || "", peak_online: Math.max(online, old?.peak_online || 0),
        hit_keyword: hit_kw || old?.hit_keyword, hit_fields: hit_fields || old?.hit_fields,
        source, end_seen: null, id: old?.id || rows.sessions.size + 1 });
    } else if (/UPDATE sessions SET end_seen/i.test(sql)) {
      const [ts, id] = args;
      for (const r of rows.sessions.values()) if (r.id === id) r.end_seen = ts;
    } else if (/INSERT INTO snapshots/i.test(sql)) {
      rows.snapshots.push({ ts: args[0], uid: args[1], title: args[3] });
    } else if (/INSERT INTO poll_log/i.test(sql)) {
      rows.poll_log.push({ ts: args[0], status: args[1], rooms: args[2], live: args[3], uids: args[4], detail: args[5] });
    }
  };
  return {
    prepare(sql) {
      return {
        bind(...args) { return { _sql: sql, _args: args }; },
        async all() {
          if (/SELECT id,uid,live_time FROM sessions/i.test(sql)) {
            return { results: [...rows.sessions.values()].filter((r) => !r.end_seen).map((r) => ({ id: r.id, uid: r.uid, live_time: r.live_time })) };
          }
          if (/SELECT uid FROM streamers/i.test(sql)) {
            return { results: [...rows.streamers.values()].map((r) => ({ uid: r.uid })) };
          }
          if (/SELECT COUNT\(\*\) AS n FROM poll_log/i.test(sql)) return { results: [{ n: rows.poll_log.length }] };
          return { results: [] };
        },
        async first() {
          if (/COUNT\(\*\) AS n FROM poll_log/i.test(sql)) return { n: rows.poll_log.length };
          return null;
        },
      };
    },
    async batch(stmts) { for (const s of stmts) parse(s._sql, s._args); return []; },
    _rows: rows,
  };
}

async function main() {
  console.log("[1] 取 buvid3");
  await initSession();
  console.log("[2] A通道: 关键词搜索");
  const { rooms, users } = await searchLive(KEYWORD);
  console.log(`   live_room=${rooms.length} live_user=${users.length}`);
  for (const r of rooms) console.log("   ", r.roomid, clean(r.uname), clean(r.title).slice(0, 40), r.live_time);

  console.log("[3] B通道: 批量状态");
  const db = makeMockDB();
  const now = new Date(Date.now() + 8 * 3600e3).toISOString().slice(0, 19).replace("T", " ");
  for (const u of users) {
    db.batch([db.prepare("INSERT INTO streamers VALUES(?,?,?,?,?,?)").bind(Number(u.uid), clean(u.uname), u.roomid, "search", now, now)]);
  }
  const pool = [...new Set([...WHITELIST_UIDS, ...[...db._rows.streamers.keys()]])].slice(0, 150);
  const states = await bulkStatus(pool);
  console.log("   状态返回 UID 数:", Object.keys(states).length, "在播:", Object.values(states).filter((s) => Number(s.live_status) === 1).length);

  const sessions = [], liveKeys = new Set();
  for (const r of rooms) {
    if (Number(r.live_status) !== 1 || !r.live_time) continue;
    const s = makeSession(r.uid, clean(r.uname), r.roomid, r.live_time, clean(r.title), clean(r.tags), (r.hit_columns || []).join(","), r.online, r.cate_name || "", "", "search");
    sessions.push(s); liveKeys.add(`${s.uid}|${s.live_time}`);
  }
  for (const [uid, st] of Object.entries(states)) {
    if (Number(st.live_status) !== 1) continue;
    const lt = new Date(Number(st.live_time) * 1000 + 8 * 3600e3).toISOString().slice(0, 19).replace("T", " ");
    const s = makeSession(uid, clean(st.uname), st.room_id, lt, clean(st.title), clean(st.tags),
      WHITELIST_UIDS.includes(Number(uid)) ? "whitelist" : "", st.online, st.area_v2_parent_name || "", st.area_v2_name || "", "search");
    sessions.push(s); liveKeys.add(`${s.uid}|${s.live_time}`);
  }
  console.log("[4] 去重后场次:", liveKeys.size, "原始:", sessions.length);

  const res = await persist(db, { now, sessions, liveKeys, roomsFound: rooms.length, uidChecked: pool.length, errors: [], notes: [] });
  console.log("[5] 落库:", JSON.stringify(res));
  console.log("   sessions表:", db._rows.sessions.size, "poll_log:", db._rows.poll_log.length);
  console.log("\n=== 场次明细 ===");
  for (const r of db._rows.sessions.values()) {
    console.log(`   ${r.live_time} | ${r.uname} | hit=${r.hit_keyword} | peak=${r.peak_online} | ${r.title.slice(0, 30)}`);
  }

  // 断言
  const ok = db._rows.sessions.size === liveKeys.size && db._rows.poll_log.length === 1 &&
    [...db._rows.sessions.values()].every((r) => r.hit_keyword);
  console.log("\n本地逻辑测试:", ok ? "PASS" : "FAIL");
  if (!ok) process.exit(1);
}
main().catch((e) => { console.error("测试失败:", e); process.exit(1); });
