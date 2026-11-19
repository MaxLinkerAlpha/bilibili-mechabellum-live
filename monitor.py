# -*- coding: utf-8 -*-
"""
B站「钢铁指挥官」直播间/主播 24h 记录器。

双通道：
  A. 关键词搜索 search_type=live  ->  发现当前在播 + 用户名命中
  B. get_status_info_by_uids      ->  追踪已知主播（含白名单/视频发现的UP）的每一场开播

仅用免费公开接口，不登录、不破解签名、不碰个人信息。
用法见 README.md。
"""
import argparse, http.cookiejar, json, os, random, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

# B站返回的 live_time 字符串是北京时间(UTC+8)。批量接口给的是 unix 时间戳，
# 必须用固定 +8 转换，否则在 UTC 环境的 GitHub Actions 上会把同一场拆成两条。
CN_TZ = timezone(timedelta(hours=8))

import config as C
import db

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

TAG_RE = re.compile(r"<[^>]+>")


def clean(s):
    return TAG_RE.sub("", s or "").strip()


def now_iso():
    return datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


def ts_to_iso(t):
    try:
        return datetime.fromtimestamp(int(t), CN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


class Bili:
    """带 cookie 的轻量 HTTP 客户端，启动时拿 buvid3 降低风控概率。"""

    def __init__(self, gap=C.REQUEST_GAP):
        self.gap = gap
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self._last = 0.0
        self.bootstrap()

    def _wait(self):
        d = self.gap - (time.time() - self._last)
        if d > 0:
            time.sleep(d + random.uniform(0, 0.25))
        self._last = time.time()

    def bootstrap(self):
        self._wait()
        req = urllib.request.Request("https://www.bilibili.com/", headers={"User-Agent": UA})
        try:
            self.op.open(req, timeout=20).read(1024)
        except Exception:
            pass

    def get(self, url, params=None, referer="https://www.bilibili.com/", retries=3):
        u = url + ("?" + urllib.parse.urlencode(params) if params else "")
        for i in range(retries):
            self._wait()
            req = urllib.request.Request(u, headers={
                "User-Agent": UA, "Referer": referer,
                "Accept": "application/json, text/plain, */*",
            })
            try:
                with self.op.open(req, timeout=25) as r:
                    return json.loads(r.read().decode("utf-8", "replace"))
            except Exception as e:
                if i == retries - 1:
                    return {"code": -1, "message": repr(e)}
                time.sleep(2 ** i + random.uniform(0, 1))
        return {"code": -1, "message": "unreachable"}

    def post(self, url, payload, referer="https://live.bilibili.com/", retries=3):
        body = json.dumps(payload).encode("utf-8")
        for i in range(retries):
            self._wait()
            req = urllib.request.Request(url, data=body, headers={
                "User-Agent": UA, "Referer": referer,
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
            })
            try:
                with self.op.open(req, timeout=25) as r:
                    return json.loads(r.read().decode("utf-8", "replace"))
            except Exception as e:
                if i == retries - 1:
                    return {"code": -1, "message": repr(e)}
                time.sleep(2 ** i + random.uniform(0, 1))
        return {"code": -1, "message": "unreachable"}


def hit_test(text, alias=None):
    """返回命中的关键词与字段串。"""
    alias = alias or C.KEYWORD_ALIASES
    t = text or ""
    for kw in alias:
        if kw.lower() in t.lower():
            return kw
    return None


def search_live(bili, keyword, pages=None):
    """关键词搜索：返回 (live_rooms, live_users)。"""
    pages = pages or C.SEARCH_PAGES
    rooms, users = [], []
    for p in range(1, pages + 1):
        d = bili.get("https://api.bilibili.com/x/web-interface/search/type",
                     {"search_type": "live", "keyword": keyword, "page": p},
                     referer="https://search.bilibili.com/")
        if d.get("code") != 0:
            return rooms, users, d.get("message", "")
        res = (d.get("data") or {}).get("result") or {}
        rooms += res.get("live_room") or []
        users += res.get("live_user") or []
        n = ((d.get("data") or {}).get("pageinfo") or {}).get("live_room", {}).get("numPages", 1)
        if p >= n:
            break
    return rooms, users, ""


def search_video_authors(bili, keyword, pages=None):
    """视频搜索：近期做该游戏的 UP 主 mid，用于扩充追踪池。"""
    pages = pages or C.VIDEO_SEARCH_PAGES
    authors = []
    for p in range(1, pages + 1):
        d = bili.get("https://api.bilibili.com/x/web-interface/search/type",
                     {"search_type": "video", "keyword": keyword, "page": p},
                     referer="https://search.bilibili.com/")
        if d.get("code") != 0:
            break
        for v in ((d.get("data") or {}).get("result") or []):
            mid, name = v.get("mid"), v.get("author")
            if mid:
                authors.append((int(mid), name or ""))
    return authors


def bulk_status(bili, uids):
    """批量查 UID 当前直播状态。uids: list[int]"""
    out = {}
    uids = list(dict.fromkeys(int(x) for x in uids if x))
    for i in range(0, len(uids), 50):
        batch = uids[i:i + 50]
        d = bili.post("https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids",
                      {"uids": batch})
        if d.get("code") != 0:
            continue
        out.update((d.get("data") or {}))
    return out


def make_session(uid, uname, room_id, live_time_iso, title, tags, fields_hit,
                 online, cate="", area="", source="search"):
    kw = hit_test(f"{title} {tags}")
    fields = []
    if hit_test(title):
        fields.append("title")
    if hit_test(tags):
        fields.append("tags")
    if hit_test(uname):
        fields.append("uname")
    if fields_hit:
        fields += [x for x in fields_hit.split(",") if x]
    return {
        "uid": uid, "uname": uname, "room_id": room_id,
        "live_time": live_time_iso, "title": title, "tags": tags,
        "cate_name": cate, "area_name": area, "online": online or 0,
        "hit_keyword": kw, "hit_fields": ",".join(dict.fromkeys(fields)),
        "source": source,
    }


def poll(bili, conn, verbose=True):
    now = now_iso()
    notes = []
    errors = []
    live_keys = set()
    sessions = []
    authors = []

    # --- 通道 A：关键词搜索 ---
    rooms, users, err = search_live(bili, C.KEYWORD)
    if err:
        errors.append(f"search:{err}")
    for x in rooms:
        if int(x.get("live_status") or 0) != 1:
            continue
        uid = x.get("uid")
        lt = x.get("live_time") or ""
        s = make_session(uid, clean(x.get("uname")), x.get("roomid"), lt,
                         clean(x.get("title")), clean(x.get("tags")),
                         ",".join(x.get("hit_columns") or []),
                         x.get("online"), x.get("cate_name", ""), "", "search")
        if not s["live_time"]:
            continue
        sessions.append(s)
        live_keys.add((int(uid), lt))
        db.upsert_streamer(conn, uid, s["uname"], x.get("roomid"), "search", now)
    for x in users:
        uid = x.get("uid")
        if uid:
            db.upsert_streamer(conn, uid, clean(x.get("uname")), x.get("roomid"), "search", now)

    # --- 通道 B：批量状态追踪已知主播 ---
    # 排序：白名单 > search 命中 > video 发现，保证达到上限时优先追踪强相关主播
    known = [r[0] for r in conn.execute(
        "SELECT uid FROM streamers ORDER BY CASE source WHEN 'search' THEN 0 "
        "WHEN 'whitelist' THEN 0 ELSE 1 END, last_seen DESC").fetchall()]
    wl = [int(u) for u in C.WHITELIST_UIDS]
    pool = list(dict.fromkeys(wl + known))[:C.MAX_TRACK_UIDS]
    states = bulk_status(bili, pool)

    for uid, st in states.items():
        uid = int(uid)
        if int(st.get("live_status") or 0) != 1:
            continue
        lt = ts_to_iso(st.get("live_time")) or now
        in_wl = uid in wl
        s = make_session(
            uid, clean(st.get("uname")), st.get("room_id"), lt,
            clean(st.get("title")), clean(st.get("tags")),
            "whitelist" if in_wl else "",
            st.get("online"), st.get("area_v2_parent_name", ""),
            st.get("area_v2_name", ""),
            "whitelist" if in_wl else "search",
        )
        sessions.append(s)
        live_keys.add((uid, lt))
        db.upsert_streamer(conn, uid, s["uname"], st.get("room_id"),
                           "whitelist" if in_wl else "search", now)

    # --- 视频发现：扩充追踪池（低频，每 10 轮一次，减少风控） ---
    last_vid = conn.execute("SELECT MAX(id) FROM poll_log").fetchone()[0] or 0
    if C.ENABLE_VIDEO_DISCOVERY and last_vid % 10 == 0:
        authors = search_video_authors(bili, C.KEYWORD)
        for mid, name in authors:
            db.upsert_streamer(conn, mid, name, None, "video", now)
        notes.append(f"video_authors:{len(authors)}")

    # --- 落库：场次去重 upsert + 结束标记 ---
    for s in sessions:
        db.upsert_session(conn, s, now)
        db.add_snapshot(conn, now, s["uid"], s["room_id"], s["title"], s["tags"],
                        s["online"], s["live_time"], s["source"])
    closed = db.close_finished_sessions(conn, live_keys, now)
    live_count = len(live_keys)   # 去重后的真实在播场次数

    # 硬失败保护：连续 3 轮接口报错才告警（单轮 412 属正常波动，凌晨零在播属正常）
    status = "ok" if not errors else "partial"
    if errors:
        recent = conn.execute(
            "SELECT status FROM poll_log ORDER BY id DESC LIMIT 2").fetchall()
        if len(recent) == 2 and all(r["status"] == "partial" for r in recent):
            status = "fail"
            errors.append("连续3轮接口报错，请检查风控/接口")
    detail = ";".join(errors + notes)
    db.add_poll_log(conn, now, status, len(rooms), live_count, len(pool), detail)
    conn.commit()

    if verbose:
        print(f"[{now}] {status} 搜索房间={len(rooms)} 去重在播={live_count} "
              f"追踪UID={len(pool)} 视频发现={len(authors)} 结束场次={closed}")
    return {"rooms": len(rooms), "live": live_count, "uids": len(pool),
            "closed": closed, "errors": errors, "notes": notes, "status": status}


def cmd_collect(args):
    conn = db.connect()
    bili = Bili()
    if args.once:
        status = poll(bili, conn)["status"]
        conn.close()
        # CI 用：连续失败返回非0，让 Actions 标红告警
        sys.exit(1 if status == "fail" else 0)
    print(f"启动 24h 采集：关键词={C.KEYWORD} 间隔={C.POLL_INTERVAL}s Ctrl+C 停止")
    n = 0
    try:
        while True:
            try:
                r = poll(bili, conn)
                n += 1
                if n % 10 == 0:
                    db.prune(conn, C.LOG_RETENTION_DAYS)
                    conn.commit()
            except Exception as e:
                print(f"[{now_iso()}] 轮次异常: {e!r}", file=sys.stderr)
                db.add_poll_log(conn, now_iso(), "fail", 0, 0, 0, repr(e)[:200])
                conn.commit()
            time.sleep(C.POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="B站钢铁指挥官直播记录器")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("collect", help="采集（默认常驻）")
    p.add_argument("--once", action="store_true", help="只跑一轮")
    p.set_defaults(func=cmd_collect)
    a = ap.parse_args()
    if not hasattr(a, "func"):
        ap.print_help()
    else:
        a.func(a)
