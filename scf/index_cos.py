# -*- coding: utf-8 -*-
"""
腾讯云 SCF · B站钢铁指挥官直播记录器 —— COS 持久化版。

采集：双通道（关键词搜索 + 批量UID状态），与验证通过的同源。
存储：腾讯云 COS（SCF 同地域内网，最稳）。密钥从环境变量读，不进代码。
时间：统一北京时间 UTC+8。

SCF 环境变量（控制台配置，不要写进代码）：
  COS_SECRET_ID   = 你的 SecretId
  COS_SECRET_KEY  = 你的 SecretKey
  COS_BUCKET      = 桶名，如 bili-live-1300000000
  COS_REGION      = ap-guangzhou
  COS_KEY         = data.json（可选，默认 data.json）

仅用标准库。
"""
import json, urllib.request, urllib.parse, http.cookiejar, re, time, os, hmac, hashlib
from datetime import datetime, timezone, timedelta

# ---------- 配置 ----------
KEYWORD = "钢铁指挥官"
ALIASES = ["钢铁指挥官", "钢指", "Mechabellum"]
WHITELIST_UIDS = [3494349981616217]
MAX_TRACK_UIDS = 150
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
CN_TZ = timezone(timedelta(hours=8))

# COS 凭证：从环境变量读，缺失直接抛错（不做默认兜底，符合安全规范）
COS_SECRET_ID = os.environ.get("COS_SECRET_ID", "")
COS_SECRET_KEY = os.environ.get("COS_SECRET_KEY", "")
COS_BUCKET = os.environ.get("COS_BUCKET", "")
COS_REGION = os.environ.get("COS_REGION", "ap-guangzhou")
COS_KEY = os.environ.get("COS_KEY", "data.json")

_cookie = None


# ---------- 工具 ----------
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


# ---------- COS 签名 v5（只签 host）----------
def _cos_auth(method, uri, host, expires=600):
    if not (COS_SECRET_ID and COS_SECRET_KEY):
        raise RuntimeError("COS_SECRET_ID / COS_SECRET_KEY 未配置")
    now = int(time.time())
    key_time = f"{now};{now + expires}"
    sign_key = hmac.new(COS_SECRET_KEY.encode("utf-8"), key_time.encode("utf-8"), hashlib.sha1).hexdigest()
    header_list = "host"
    http_headers = "host=" + urllib.parse.quote(host, safe="")
    http_string = f"{method.lower()}\n{uri}\n\n{http_headers}\n"
    sha1_http = hashlib.sha1(http_string.encode("utf-8")).hexdigest()
    string_to_sign = f"sha1\n{key_time}\n{sha1_http}\n"
    signature = hmac.new(sign_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).hexdigest()
    return (f"q-sign-algorithm=sha1&q-ak={COS_SECRET_ID}&q-sign-time={key_time}"
            f"&q-key-time={key_time}&q-header-list={header_list}&q-url-param-list=&q-signature={signature}")


def _cos_url(key=None):
    # 内网域名（SCF 与 COS 同地域时走内网，更快更稳）
    key = key or COS_KEY
    host = f"{COS_BUCKET}.cos.{COS_REGION}.myqcloud.com"
    return host, f"https://{host}/{key}"


def cos_get(key=None):
    key = key or COS_KEY
    host, url = _cos_url(key)
    uri = "/" + key
    req = urllib.request.Request(url, headers={
        "Host": host, "Authorization": _cos_auth("get", uri, host),
    }, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None if key != COS_KEY else {"streamers": {}, "sessions": {}, "poll_log": []}
        raise
    except json.JSONDecodeError:
        return None if key != COS_KEY else {"streamers": {}, "sessions": {}, "poll_log": []}


def cos_put(data, key=None):
    key = key or COS_KEY
    host, url = _cos_url(key)
    uri = "/" + key
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Host": host, "Authorization": _cos_auth("put", uri, host),
        "Content-Type": "application/json",
    }, method="PUT")
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status == 200


def cos_list(prefix="backup/"):
    """列出指定前缀的对象，返回 key 列表。"""
    host = f"{COS_BUCKET}.cos.{COS_REGION}.myqcloud.com"
    params = {"prefix": prefix, "max-keys": "1000"}
    query = urllib.parse.urlencode(params)
    url = f"https://{host}/?{query}"
    # 签名需含参数
    now = int(time.time())
    key_time = f"{now};{now + 600}"
    sign_key = hmac.new(COS_SECRET_KEY.encode(), key_time.encode(), hashlib.sha1).hexdigest()
    keys = sorted(params.keys())
    url_param_list = ";".join(keys)
    http_params = "&".join(f"{k}={urllib.parse.quote(str(params[k]), safe='')}" for k in keys)
    http_headers = "host=" + urllib.parse.quote(host, safe="")
    http_string = f"get\n/\n{http_params}\n{http_headers}\n"
    sha1_http = hashlib.sha1(http_string.encode()).hexdigest()
    string_to_sign = f"sha1\n{key_time}\n{sha1_http}\n"
    signature = hmac.new(sign_key.encode(), string_to_sign.encode(), hashlib.sha1).hexdigest()
    auth = (f"q-sign-algorithm=sha1&q-ak={COS_SECRET_ID}&q-sign-time={key_time}"
            f"&q-key-time={key_time}&q-header-list=host&q-url-param-list={url_param_list}"
            f"&q-signature={signature}")
    req = urllib.request.Request(url, headers={"Host": host, "Authorization": auth}, method="GET")
    with urllib.request.urlopen(req, timeout=15) as r:
        xml = r.read().decode("utf-8", "replace")
    return re.findall(r"<Key>([^<]+)</Key>", xml)


def cos_delete(key):
    host = f"{COS_BUCKET}.cos.{COS_REGION}.myqcloud.com"
    url = f"https://{host}/{key}"
    req = urllib.request.Request(url, headers={
        "Host": host, "Authorization": _cos_auth("delete", "/" + key, host),
    }, method="DELETE")
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status in (200, 204)


BACKUP_PREFIX = "backup/"
# 不设上限、不清理：用户要求永久保留从今往后所有备份
BACKUP_INTERVAL_DAYS = 7


def weekly_backup(data, now_str):
    """距上次备份 >=7 天则写独立快照，并清理超过 8 份的旧备份。返回本次备份 key 或空串。"""
    last = data.get("last_backup") or ""
    try:
        if last:
            d0 = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
            d1 = datetime.strptime(now_str, "%Y-%m-%d %H:%M:%S")
            if (d1 - d0).days < BACKUP_INTERVAL_DAYS:
                return ""
    except Exception:
        pass  # 时间解析失败则强制备份一次

    date_tag = now_str[:10].replace("-", "")
    key = f"{BACKUP_PREFIX}live-{date_tag}.json"
    cos_put(data, key=key)
    data["last_backup"] = now_str
    # 主库也记一笔，避免 isolate 重置后重复备份
    try:
        cos_put(data)
    except Exception:
        pass
    print("BACKUP_DONE", key)
    # 永久保留所有备份，不清理
    return key


def restore_from_backup(key=None):
    """手动恢复：从指定备份（默认最新）读数据并写回主库。供运维用。"""
    if not key:
        keys = sorted(cos_list(BACKUP_PREFIX))
        if not keys:
            raise RuntimeError("无备份")
        key = keys[-1]
    data = cos_get(key=key)
    if not data:
        raise RuntimeError("备份读取为空: " + key)
    cos_put(data)
    return {"restored_from": key, "sessions": len(data.get("sessions", {}))}


# ---------- B站 HTTP ----------
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
    headers = {"User-Agent": UA, "Referer": referer,
               "Accept": "application/json, text/plain, */*", "Accept-Language": "zh-CN,zh;q=0.9"}
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


def make_session(uid, uname, room_id, live_time, title, tags, extra, online, source="search"):
    fields = []
    for k, v in (("title", title), ("tags", tags), ("uname", uname)):
        if hit_test(v):
            fields.append(k)
    for f in str(extra or "").split(","):
        if f and f not in fields:
            fields.append(f)
    return {"uid": int(uid), "uname": uname, "room_id": room_id, "live_time": live_time,
            "title": title, "tags": tags, "online": int(online or 0),
            "hit_keyword": hit_test(f"{title} {tags}"),
            "hit_fields": ",".join(dict.fromkeys(fields)),
            "source": source, "last_seen": now_cn()}


# ---------- 主逻辑 ----------
def collect():
    now = now_cn()
    errors, notes = [], []
    live_keys = set()
    rooms, users, authors = [], [], []

    # 读 COS 历史
    try:
        data = cos_get()
    except Exception as e:
        print("COS_READ_FAIL", repr(e))
        # 读失败不空跑覆盖：直接失败退出，保护已有数据
        raise

    sessions_by_key = data.setdefault("sessions", {})
    streamers = data.setdefault("streamers", {})

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
            k = f"{s['uid']}|{s['live_time']}"
            live_keys.add(k)
            old = sessions_by_key.get(k)
            s["peak_online"] = max(s["online"], (old or {}).get("peak_online", 0))
            s["first_seen"] = (old or {}).get("first_seen", now)
            sessions_by_key[k] = s
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
            k = f"{s['uid']}|{s['live_time']}"
            live_keys.add(k)
            old = sessions_by_key.get(k)
            s["peak_online"] = max(s["online"], (old or {}).get("peak_online", 0))
            s["first_seen"] = (old or {}).get("first_seen", now)
            sessions_by_key[k] = s
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
    data["poll_log"] = data["poll_log"][-1000:]

    # 写回 COS
    try:
        cos_put(data)
    except Exception as e:
        print("COS_WRITE_FAIL", repr(e))
        raise

    # 每周快照备份：距上次 >=7 天则写一份独立文件，保留最近 8 份
    backup_done = ""
    try:
        backup_done = weekly_backup(data, now)
        if backup_done:
            notes.append("backup:" + backup_done)
    except Exception as e:
        notes.append("backup_fail:" + repr(e)[:60])
        print("BACKUP_FAIL", repr(e))

    result = {"ts": now, "status": status, "rooms_found": len(rooms),
              "live_count": len(live_keys), "uid_checked": len(pool),
              "sessions_total": len(sessions_by_key), "streamers_total": len(streamers),
              "backup": backup_done, "errors": errors, "notes": notes}
    print("RESULT " + json.dumps(result, ensure_ascii=False))
    for k, s in sessions_by_key.items():
        if s.get("hit_keyword"):
            print("HIT " + json.dumps({"live_time": s["live_time"], "uname": s["uname"],
                "title": s["title"], "hit": s["hit_keyword"], "peak": s.get("peak_online", 0),
                "room": s["room_id"]}, ensure_ascii=False))
    return result


def main_handler(event, context):
    # 手动运维：SCF 测试事件传 {"action":"backup"} 或 {"action":"restore","key":"backup/live-xxx.json"}
    if isinstance(event, dict):
        action = event.get("action")
        if action == "backup":
            data = cos_get()
            return {"backup": weekly_backup(data, now_cn())}
        if action == "restore":
            return restore_from_backup(event.get("key"))
    return collect()


if __name__ == "__main__":
    collect()
