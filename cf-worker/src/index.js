// B站钢铁指挥官直播记录器 · Cloudflare Worker
// Cron 每5分钟：采集一轮写 D1；HTTP：报表/status/手动触发
import { KEYWORD, WHITELIST_UIDS, MAX_TRACK_UIDS, ENABLE_VIDEO_DISCOVERY, nowCN, tsToCN } from "./config.js";
import { initSession, searchLive, bulkStatus, searchVideoAuthors, clean } from "./bili.js";
import { makeSession, persist } from "./store.js";

async function collect(env) {
  const db = env.DB;
  const now = nowCN();
  await initSession();
  const sessions = [];
  const liveKeys = new Set();
  const errors = [];
  const notes = [];
  let roomsFound = 0;
  let authors = [];

  // A 通道：关键词搜索
  try {
    const { rooms, users } = await searchLive(KEYWORD);
    roomsFound = rooms.length;
    for (const x of rooms) {
      if (Number(x.live_status) !== 1 || !x.live_time) continue;
      const s = makeSession(x.uid, clean(x.uname), x.roomid, x.live_time,
        clean(x.title), clean(x.tags), (x.hit_columns || []).join(","),
        x.online, x.cate_name || "", "", "search");
      sessions.push(s);
      liveKeys.add(`${s.uid}|${s.live_time}`);
    }
    // 用户名命中（live_user）入库，走 batch
    if (users.length) {
      const us = users.filter((u) => u.uid).map((u) =>
        db.prepare(`INSERT INTO streamers(uid,uname,room_id,source,first_seen,last_seen)
          VALUES(?,?,?,?,?,?) ON CONFLICT(uid) DO UPDATE SET
          uname=CASE WHEN excluded.uname<>'' THEN excluded.uname ELSE streamers.uname END,
          room_id=COALESCE(excluded.room_id, streamers.room_id), last_seen=excluded.last_seen`)
          .bind(Number(u.uid), clean(u.uname), u.roomid, "search", now, now));
      await db.batch(us);
    }
  } catch (e) {
    errors.push("search:" + String(e.message || e));
  }

  // B 通道：批量状态追踪
  let pool = [];
  try {
    const known = await db.prepare(`SELECT uid FROM streamers
      ORDER BY CASE source WHEN 'search' THEN 0 WHEN 'whitelist' THEN 0 ELSE 1 END,
      last_seen DESC LIMIT ?`).bind(MAX_TRACK_UIDS).all();
    pool = [...new Set([...WHITELIST_UIDS, ...(known.results || []).map((r) => Number(r.uid))])]
      .slice(0, MAX_TRACK_UIDS);
    const states = await bulkStatus(pool);
    for (const [uid, st] of Object.entries(states)) {
      if (Number(st.live_status) !== 1) continue;
      const lt = tsToCN(st.live_time) || now;
      const inWl = WHITELIST_UIDS.includes(Number(uid));
      const s = makeSession(uid, clean(st.uname), st.room_id, lt,
        clean(st.title), clean(st.tags), inWl ? "whitelist" : "",
        st.online, st.area_v2_parent_name || "", st.area_v2_name || "",
        inWl ? "whitelist" : "search");
      sessions.push(s);
      liveKeys.add(`${s.uid}|${s.live_time}`);
    }
  } catch (e) {
    errors.push("status:" + String(e.message || e));
  }

  // C 通道：视频发现（每10轮一次，降低请求）
  try {
    const n = await db.prepare("SELECT COUNT(*) AS n FROM poll_log").first();
    if (ENABLE_VIDEO_DISCOVERY && (n?.n || 0) % 10 === 0) {
      authors = await searchVideoAuthors(KEYWORD);
      if (authors.length) {
        await db.batch(authors.map((a) =>
          db.prepare(`INSERT INTO streamers(uid,uname,room_id,source,first_seen,last_seen)
            VALUES(?,?,?,?,?,?) ON CONFLICT(uid) DO UPDATE SET last_seen=excluded.last_seen`)
            .bind(a.uid, a.uname, null, "video", now, now)));
      }
      notes.push("video:" + authors.length);
    }
  } catch (e) {
    notes.push("video_err:" + String(e.message || e).slice(0, 60));
  }

  const res = await persist(db, { now, sessions, liveKeys, roomsFound,
    uidChecked: pool.length, errors, notes });
  return { ...res, now, authors: authors.length };
}

// 报表：命中关键词的场次
async function reportMd(db) {
  const hits = await db.prepare(`SELECT live_time,uname,title,hit_keyword,peak_online,room_id
    FROM sessions WHERE hit_keyword IS NOT NULL AND hit_keyword<>'' ORDER BY live_time DESC LIMIT 200`).all();
  const all = await db.prepare("SELECT COUNT(*) AS n FROM sessions").first();
  const st = await db.prepare("SELECT COUNT(*) AS n FROM streamers").first();
  const last = await db.prepare("SELECT ts,status FROM poll_log ORDER BY id DESC LIMIT 1").first();
  const lines = [
    `# 钢铁指挥官 B站直播记录（截至 ${nowCN()}）`, "",
    `- 累计场次：**${all?.n || 0}**`,
    `- 明确命中关键词：**${(hits.results || []).length}**`,
    `- 追踪主播：**${st?.n || 0}**`,
    `- 最后一轮：**${last?.ts || "-"}** (${last?.status || "-"})`, "",
    "## 命中关键词的场次", "",
    "| 开播时间 | 主播 | 标题 | 命中 | 峰值 | 直播间 |",
    "|---|---|---|---|---:|---|",
  ];
  for (const r of hits.results || []) {
    const title = String(r.title || "").replace(/\|/g, "\\|").slice(0, 60);
    lines.push(`| ${r.live_time} | ${r.uname} | ${title} | ${r.hit_keyword} | ${r.peak_online} | https://live.bilibili.com/${r.room_id} |`);
  }
  return lines.join("\n");
}

function csvEscape(v) {
  const s = String(v ?? "");
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

async function sessionsCsv(db) {
  const rows = await db.prepare(`SELECT live_time,uname,uid,room_id,title,hit_keyword,hit_fields,
    peak_online,first_seen,last_seen,end_seen,source FROM sessions ORDER BY live_time DESC`).all();
  const head = ["开播时间", "主播", "uid", "直播间", "标题", "命中关键词", "命中字段", "峰值人气", "首次观测", "最后观测", "下播观测", "来源"];
  const keys = ["live_time", "uname", "uid", "room_id", "title", "hit_keyword", "hit_fields", "peak_online", "first_seen", "last_seen", "end_seen", "source"];
  const out = [head.join(",")];
  for (const r of rows.results || []) out.push(keys.map((k) => csvEscape(r[k])).join(","));
  return "\ufeff" + out.join("\n");
}

async function statusJson(db) {
  const polls = await db.prepare("SELECT COUNT(*) AS n FROM poll_log").first();
  const last = await db.prepare("SELECT * FROM poll_log ORDER BY id DESC LIMIT 1").first();
  const sessions = await db.prepare("SELECT COUNT(*) AS n FROM sessions").first();
  const streamers = await db.prepare("SELECT COUNT(*) AS n FROM streamers").first();
  return { ok: true, now: nowCN(), polls: polls?.n, sessions: sessions?.n,
    streamers: streamers?.n, last };
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(collect(env).then((r) => {
      console.log(JSON.stringify({ cron: true, ...r }));
    }).catch((e) => {
      console.error("collect failed:", e);
    }));
  },

  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;
    try {
      if (path === "/" || path === "/report") {
        return new Response(await reportMd(env.DB), {
          headers: { "Content-Type": "text/markdown; charset=utf-8" },
        });
      }
      if (path === "/sessions.csv") {
        return new Response(await sessionsCsv(env.DB), {
          headers: { "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": "attachment; filename=sessions.csv" },
        });
      }
      if (path === "/status") {
        return new Response(JSON.stringify(await statusJson(env.DB), null, 2), {
          headers: { "Content-Type": "application/json; charset=utf-8" },
        });
      }
      if (path === "/run") {
        const r = await collect(env);
        return new Response(JSON.stringify(r), { headers: { "Content-Type": "application/json" } });
      }
      return new Response("Not found. Try /report /sessions.csv /status /run", { status: 404 });
    } catch (e) {
      return new Response("Error: " + String(e.message || e), { status: 500 });
    }
  },
};
