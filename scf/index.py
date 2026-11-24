# -*- coding: utf-8 -*-
"""
腾讯云 SCF · B站钢铁指挥官直播记录器（香港/内地地域均可，推荐内地）。

采集逻辑与 Cloudflare Worker 版一致：
  A 关键词搜索 live_room（当前在播）
  B 批量 UID 状态（追踪已知主播）
  C 视频搜索扩充追踪池（每10轮一次）

存储：写本文件同目录的 data.json（SCF 挂载 COS 后可持久化；不挂载则仅日志输出）。
时间统一北京时间 UTC+8。仅用标准库，无需 pip install。
"""
import json, urllib.request, urllib.parse, http.cookiejar, re, time, os
from datetime import datetime, timezone, timedelta

# ---------- 配置 ----------
KEYWORD = "钢铁指挥官"
ALIASES = ["钢铁指挥官", "钢指", "Mechabellum"]
WHITELIST_UIDS = [3494349981616217]  # 官方号
MAX_TRACK_UIDS = 150
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
CN_TZ = timezone(timedelta(hours=8))
DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")

_cookie = None


def now_cn():
    return datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


def ts_to_cn(sec):
    try:
        return datetime.fromtimestamp(int(sec), CN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def clean(s):
    return re.sub(r"<[^>]+>", "", str(s or "")).strip()


def hit_test(text):
    t = str(text or "").lower()
    for kw in ALIASES:
        if kw.lower() in t:
            return kw
    return None


# ---------- HTTP ----------
def _opener():
    global _cookie
    if _cookie is None:
        jar = http.cookiejar.CookieJar()
        _cookie = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        try:
            _cookie.open(urllib.request.Request("https://www.bilibili.com/", headers={"User-Agent": UA}), timeout=15).read(512)
        except Exception:
            pass
    return _cookie


def api(url, params=None, referer="https://www.bilibili.com/", method="GET", body=None, retries=3):
    u = url + ("?" + urllib.parse.urlencode(params) if params else "")
    headers = {
        "User-Agent": UA, "Referer": referer,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body).encode("utf-8")
    op = _opener()
    for i in range(retries):
        try:
            req = urllib.request.Request(u, data=payload, headers=headers, method=method)
            with op.open(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            if i == retries - 1:
                return {"code": -1, "message": repr(e)}
            time.sleep(1.2 * (i + 1))
    return {"code": -1, "message": "unreachable"}


def search_live(keyword=KEYWORD, pages=1):
    rooms, users = [], []
    for p in range(1, pages + 1):
        d = api("https://api.bilibili.com/x/web-interface/search/type",
                {"search_type": "live", "keyword": keyword, "page": p},
                referer="https://search.bilibili.com/")
        if d.get("code") != 0:
            return rooms, users, d.get("message", "")
        res = (d.get("data") or {}).get("result") or {}
        rooms += res.get("live_room") or []
        users += res.get("live_user") or []
        np_ = ((d.get("data") or {}).get("pageinfo") or {}).get("live_room", {}).get("numPages", 1)
        if p >= np_:
            break
    return rooms, users, ""


def bulk_status(uids):
    out = {}
    uniq = list(dict.fromkeys(int(x) for x in uids if x))
    for i in range(0, len(uniq), 50):
        d = api("https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids",
                method="POST", body={"uids": uniq[i:i + 50]},
                referer="https://live.bilibili.com/")
        if d.get("code") != 0:
            continue
        out.update(d.get("data") or {})
    return out


def search_video_authors(keyword=KEYWORD, pages=2):
    authors = []
    for p in range(1, pages + 1):
        d = api("https://api.bilibili.com/x/web-interface/search/type",
                {"search_type": "video", "keyword": keyword, "page": p},
                referer="https://search.bilibili.com/")
        if d.get("code") != 0:
            break
        for v in ((d.get("data") or {}).get("result") or []):
            if v.get("mid"):
                authors.append({"uid": int(v["mid"]), "uname": clean(v.get("author"))})
    return authors


# ---------- 存储 ----------
def load_data():
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"streamers": {}, "sessions": {}, "poll_log": []}


def save_data(d):
    try:
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print("save failed:", repr(e))


def make_session(uid, uname, room_id, live_time, title, tags, extra, online, source="search"):
    fields = []
    for k, v in (("title", title), ("tags", tags), ("uname", uname)):
        if hit_test(v):
            fields.append(k)
    for f in str(extra or "").split(","):
        if f and f not in fields:
            fields.append(f)
    return {
        "uid": int(uid), "uname": uname, "room_id": room_id, "live_time": live_time,
        "title": title, "tags": tags, "online": int(online or 0),
        "hit_keyword": hit_test(f"{title} {tags}"),
        "hit_fields": ",".join(dict.fromkeys(fields)),
        "source": source, "last_seen": now_cn(),
    }


# ---------- 主逻辑 ----------
def collect():
    now = now_cn()
    data = load_data()
    sessions_by_key = data.setdefault("sessions", {})
    streamers = data.setdefault("streamers", {})
    errors, notes = [], []
    live_keys = set()
    rooms, users, authors = [], [], []

    # A 通道
    try:
        rooms, users, err = search_live()
        if err:
            errors.append("search:" + str(err)[:80])
        for x in rooms:
            if int(x.get("live_status") or 0) != 1 or not x.get("live_time"):
                continue
            s = make_session(x.get("uid"), clean(x.get("uname")), x.get("roomid"),
                             x.get("live_time"), clean(x.get("title")), clean(x.get("tags")),
                             ",".join(x.get("hit_columns") or []), x.get("online"), "search")
            live_keys.add(f"{s['uid']}|{s['live_time']}")
            old = sessions_by_key.get(f"{s['uid']}|{s['live_time']}")
            s["peak_online"] = max(s["online"], (old or {}).get("peak_online", 0))
            s["first_seen"] = (old or {}).get("first_seen", now)
            sessions_by_key[f"{s['uid']}|{s['live_time']}"] = s
        for u in users:
            if u.get("uid"):
                streamers[str(int(u["uid"]))] = {"uname": clean(u.get("uname")),
                                                  "room_id": u.get("roomid"), "source": "search"}
    except Exception as e:
        errors.append("A:" + repr(e)[:80])

    # B 通道
    pool = []
    try:
        known = [int(k) for k in streamers.keys()]
        pool = list(dict.fromkeys(WHITELIST_UIDS + known))[:MAX_TRACK_UIDS]
        states = bulk_status(pool)
        for uid, st in states.items():
            if int(st.get("live_status") or 0) != 1:
                continue
            lt = ts_to_cn(st.get("live_time")) or now
            in_wl = int(uid) in WHITELIST_UIDS
            s = make_session(uid, clean(st.get("uname")), st.get("room_id"), lt,
                             clean(st.get("title")), clean(st.get("tags")),
                             "whitelist" if in_wl else "", st.get("online"),
                             "whitelist" if in_wl else "search")
            live_keys.add(f"{s['uid']}|{s['live_time']}")
            old = sessions_by_key.get(f"{s['uid']}|{s['live_time']}")
            s["peak_online"] = max(s["online"], (old or {}).get("peak_online", 0))
            s["first_seen"] = (old or {}).get("first_seen", now)
            sessions_by_key[f"{s['uid']}|{s['live_time']}"] = s
            streamers[str(int(uid))] = {"uname": s["uname"], "room_id": st.get("room_id"),
                                        "source": "whitelist" if in_wl else "search"}
    except Exception as e:
        errors.append("B:" + repr(e)[:80])

    # C 通道：每10轮
    try:
        if len(data.get("poll_log", [])) % 10 == 0:
            authors = search_video_authors()
            for a in authors:
                streamers.setdefault(str(a["uid"]), {"uname": a["uname"], "room_id": None, "source": "video"})
            notes.append(f"video:{len(authors)}")
    except Exception as e:
        notes.append("C:" + repr(e)[:60])

    # 关闭已下播
    for k, s in sessions_by_key.items():
        if k not in live_keys and not s.get("end_seen"):
            s["end_seen"] = now

    status = "ok" if not errors else "partial"
    data.setdefault("poll_log", []).append({
        "ts": now, "status": status, "rooms": len(rooms), "live": len(live_keys),
        "uids": len(pool), "detail": ";".join(errors + notes),
    })
    # 日志只留最近 500 轮
    data["poll_log"] = data["poll_log"][-500:]
    save_data(data)

    result = {
        "ts": now, "status": status, "rooms_found": len(rooms),
        "live_count": len(live_keys), "uid_checked": len(pool),
        "sessions_total": len(sessions_by_key), "streamers_total": len(streamers),
        "errors": errors, "notes": notes,
    }
    print("RESULT " + json.dumps(result, ensure_ascii=False))
    # 命中关键词的场次单独打印，便于 CLS 日志检索
    for k, s in sessions_by_key.items():
        if s.get("hit_keyword"):
            print("HIT " + json.dumps({
                "live_time": s["live_time"], "uname": s["uname"], "title": s["title"],
                "hit": s["hit_keyword"], "peak": s.get("peak_online", 0),
                "room": s["room_id"],
            }, ensure_ascii=False))
    return result


def main_handler(event, context):
    """SCF 入口。event 可为定时触发器的空字典。"""
    return collect()


if __name__ == "__main__":
    collect()
