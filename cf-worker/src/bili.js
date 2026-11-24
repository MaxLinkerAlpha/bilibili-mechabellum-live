// B站公开接口封装。不登录、不破解签名、不碰 SESSDATA。
import { UA, KEYWORD, SEARCH_PAGES, VIDEO_SEARCH_PAGES } from "./config.js";

function clean(s) {
  return String(s ?? "").replace(/<[^>]+>/g, "").trim();
}

async function api(url, { params, referer = "https://www.bilibili.com/", method = "GET", body, retries = 3 } = {}) {
  let u = url;
  if (params) {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null) q.set(k, String(v));
    u += "?" + q.toString();
  }
  const headers = {
    "User-Agent": UA,
    Referer: referer,
    Origin: new URL(referer).origin,
    Accept: "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Sec-Fetch-Site": "same-site",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Cache-Control": "no-cache",
  };
  // 带匿名 buvid3（getBuvid 每轮先跑）。数据中心 IP 无 cookie 极易 412。
  if (cachedBuvid) headers["Cookie"] = cachedBuvid;
  let payload;
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  for (let i = 0; i < retries; i++) {
    const r = await fetch(u, { method, headers, body: payload, cf: { cacheTtl: 0 } });
    if (r.ok) return await r.json();
    if (i === retries - 1) throw new Error(`HTTP ${r.status}`);
    // 412/429 风控退避。sleep 不算 CPU 时间（网络等待），免费额度内可用。
    await new Promise((res) => setTimeout(res, 1200 * (i + 1)));
  }
}

// 启动时取匿名 buvid3，降低 412 风控概率（Worker 无状态，每轮取一次）
let cachedBuvid = null;
async function getBuvid() {
  if (cachedBuvid) return cachedBuvid;
  try {
    const r = await fetch("https://www.bilibili.com/", {
      headers: { "User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9" },
    });
    // Workers 的 headers.get('set-cookie') 会把多个 cookie 合并成一行
    const sc = r.headers.get("set-cookie") || "";
    const parts = [];
    for (const name of ["buvid3", "b_nut", "buvid4", "_uuid"]) {
      const m = sc.match(new RegExp(name + "=([^;]+)"));
      if (m) parts.push(`${name}=${m[1]}`);
    }
    cachedBuvid = parts.join("; ");
  } catch {
    cachedBuvid = "";
  }
  return cachedBuvid;
}

function cookieHeader() {
  return cachedBuvid || "";
}

// 关键词搜索直播：返回 { rooms, users }
export async function searchLive(keyword = KEYWORD) {
  const rooms = [], users = [];
  for (let p = 1; p <= SEARCH_PAGES; p++) {
    const d = await api("https://api.bilibili.com/x/web-interface/search/type", {
      params: { search_type: "live", keyword, page: p },
      referer: "https://search.bilibili.com/",
    });
    if (d.code !== 0) throw new Error(`search live code ${d.code}`);
    const res = d.data?.result || {};
    rooms.push(...(res.live_room || []));
    users.push(...(res.live_user || []));
    const np = d.data?.pageinfo?.live_room?.numPages || 1;
    if (p >= np) break;
  }
  return { rooms, users };
}

// 批量 UID 状态：POST，一次最多 50 个
export async function bulkStatus(uids) {
  const out = {};
  const uniq = [...new Set(uids.map((x) => Number(x)).filter(Boolean))];
  for (let i = 0; i < uniq.length; i += 50) {
    const d = await api("https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids", {
      method: "POST",
      body: { uids: uniq.slice(i, i + 50) },
      referer: "https://live.bilibili.com/",
    });
    if (d.code !== 0) continue;
    Object.assign(out, d.data || {});
  }
  return out;
}

// 视频搜索：近期做该游戏的 UP 主，扩充追踪池
export async function searchVideoAuthors(keyword = KEYWORD) {
  const authors = [];
  for (let p = 1; p <= VIDEO_SEARCH_PAGES; p++) {
    const d = await api("https://api.bilibili.com/x/web-interface/search/type", {
      params: { search_type: "video", keyword, page: p },
      referer: "https://search.bilibili.com/",
    });
    if (d.code !== 0) break;
    for (const v of d.data?.result || []) {
      if (v.mid) authors.push({ uid: Number(v.mid), uname: clean(v.author) });
    }
  }
  return authors;
}

export async function initSession() {
  await getBuvid();
}

export { clean };
