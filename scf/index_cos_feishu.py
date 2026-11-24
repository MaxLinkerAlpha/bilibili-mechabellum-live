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
from collections import defaultdict
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


# GitHub 时代历史场次（2026-11-19 ~ 11-24，44 场）
# 格式: [uid, room, live_time, title, hit, peak, first, last, end, source]
HISTORY_SEED = [[398972864, 21770362, '2026-11-19 14:59:07', '钢铁指挥官：寄术主播在线挨揍', '钢铁指挥官', 1094, '2026-11-19 15:10:18', '2026-11-19 15:34:56', '2026-11-20 00:45:14', 'search'], [167128185, 12904683, '2026-11-19 14:26:10', '人美声甜顶分主播！【钢铁指挥官】', '钢铁指挥官', 4418, '2026-11-19 15:10:18', '2026-11-19 15:34:56', '2026-11-20 00:45:14', 'search'], [398972864, 21770362, '2026-11-19 21:58:08', '钢铁指挥官：寄术主播在线挨揍', '钢铁指挥官', 1351, '2026-11-20 00:45:14', '2026-11-20 00:45:14', '2026-11-20 07:16:11', 'search'], [25306757, 6821921, '2026-11-19 23:25:57', '【钢铁指挥官】欧耶扫射欧洲老乡', '钢铁指挥官', 373, '2026-11-20 00:45:14', '2026-11-20 00:45:14', '2026-11-20 07:16:11', 'search'], [93390885, 1854709973, '2026-11-20 00:04:04', '帮助钢铁指挥官吸收萌新', '钢铁指挥官', 25, '2026-11-20 00:45:14', '2026-11-20 00:45:14', '2026-11-20 07:16:11', 'search'], [1976241812, 1879009590, '2026-11-19 20:37:50', '钢铁指挥官自动观战', '钢铁指挥官', 196, '2026-11-20 00:45:14', '2026-11-20 00:45:14', '2026-11-20 07:16:11', 'search'], [2385470, 132822, '2026-11-20 00:34:51', '钢铁指挥官', '钢铁指挥官', 15, '2026-11-20 00:45:14', '2026-11-20 00:45:14', '2026-11-20 07:16:11', 'search'], [470646453, 1829184936, '2026-11-20 06:27:26', '钢铁指挥官', '钢铁指挥官', 433, '2026-11-20 07:16:11', '2026-11-20 12:03:40', '2026-11-20 20:47:10', 'search'], [1976241812, 1879009590, '2026-11-20 20:01:40', '钢铁指挥官自动观战', '钢铁指挥官', 288, '2026-11-20 20:47:10', '2026-11-20 20:47:10', '2026-11-21 04:48:31', 'search'], [167128185, 12904683, '2026-11-20 19:15:16', '炼狱轮椅奥斯曼！【帝国时代4】', '钢铁指挥官', 5930, '2026-11-20 20:47:10', '2026-11-20 20:47:10', '2026-11-21 04:48:31', 'search'], [3546718723377322, 1730465904, '2026-11-20 19:05:28', '史诗机甲之星际指挥官', None, 653, '2026-11-20 20:47:10', '2026-11-20 20:47:10', '2026-11-21 04:48:31', 'search'], [21869937, 64458, '2026-11-20 19:54:18', '战舰世界X红色警戒3日冕mod联动，黑鸡船长开船！', None, 44709, '2026-11-20 20:47:10', '2026-11-20 20:47:10', '2026-11-21 04:48:31', 'search'], [327529508, 12439210, '2026-11-21 02:15:43', '远征肝合约', None, 32, '2026-11-21 04:48:31', '2026-11-21 04:48:31', '2026-11-21 09:50:10', 'search'], [470646453, 1829184936, '2026-11-21 09:25:45', '钢铁指挥官', '钢铁指挥官', 495, '2026-11-21 09:50:10', '2026-11-21 09:50:10', '2026-11-21 16:53:57', 'search'], [398972864, 21770362, '2026-11-21 14:42:20', '钢铁指挥官：寄术主播在线挨揍', '钢铁指挥官', 1435, '2026-11-21 16:53:57', '2026-11-21 16:53:57', '2026-11-22 00:36:44', 'search'], [490865688, 1856652141, '2026-11-21 15:10:40', '堂堂上分!', '钢铁指挥官', 267, '2026-11-21 16:53:57', '2026-11-21 16:53:57', '2026-11-22 00:36:44', 'search'], [1846270454, 1791696969, '2026-11-21 16:06:10', '钢铁指挥官', '钢铁指挥官', 11, '2026-11-21 16:53:57', '2026-11-21 16:53:57', '2026-11-22 00:36:44', 'search'], [167128185, 12904683, '2026-11-21 14:25:14', '卫戍协议！【明日方舟】', '钢铁指挥官', 6190, '2026-11-21 16:53:57', '2026-11-21 16:53:57', '2026-11-22 00:36:44', 'search'], [2531280, 3720038, '2026-11-21 16:14:31', '海克斯大乱斗真好玩', '钢铁指挥官', 10, '2026-11-21 16:53:57', '2026-11-21 16:53:57', '2026-11-22 00:36:44', 'search'], [845921, 10525, '2026-11-21 14:32:10', '我已经哈气改造了！肯定能上黑洞！', None, 2846, '2026-11-21 16:53:57', '2026-11-21 16:53:57', '2026-11-22 00:36:44', 'search'], [93390885, 1854709973, '2026-11-21 13:34:57', '帕鲁-双人成行', None, 18, '2026-11-21 16:53:57', '2026-11-21 16:53:57', '2026-11-22 00:36:44', 'search'], [444746395, 25418636, '2026-11-21 20:49:23', '【钢铁指挥官】熔炉杯半决赛', '钢铁指挥官', 4813, '2026-11-22 00:36:44', '2026-11-22 00:36:44', '2026-11-22 05:53:03', 'search'], [398972864, 21770362, '2026-11-21 21:41:42', '钢铁指挥官：寄术主播在线挨揍', '钢铁指挥官', 1022, '2026-11-22 00:36:44', '2026-11-22 00:36:44', '2026-11-22 05:53:03', 'search'], [315107988, 11761461, '2026-11-21 22:53:12', '深夜打打钢，久违单排', '钢铁指挥官', 12, '2026-11-22 00:36:44', '2026-11-22 00:36:44', '2026-11-22 05:53:03', 'search'], [2385470, 132822, '2026-11-21 18:12:40', '钢铁指挥官', '钢铁指挥官', 26, '2026-11-22 00:36:44', '2026-11-22 00:36:44', '2026-11-22 05:53:03', 'search'], [421203213, 25328014, '2026-11-21 19:59:03', '跟观众粉丝一起组队玩游戏大厅团建喵', None, 2985, '2026-11-22 00:36:44', '2026-11-22 00:36:44', '2026-11-22 05:53:03', 'search'], [327529508, 12439210, '2026-11-22 02:53:55', '听老歌，打远征，肝合约~', None, 38, '2026-11-22 05:53:03', '2026-11-22 05:53:03', '2026-11-22 09:52:35', 'search'], [470646453, 1829184936, '2026-11-22 06:02:47', '钢铁指挥官', '钢铁指挥官', 412, '2026-11-22 09:52:35', '2026-11-22 09:52:35', '2026-11-22 17:13:35', 'search'], [167128185, 12904683, '2026-11-22 14:26:41', '人类最大的恐惧！【杀戮尖塔2】', '钢铁指挥官', 5875, '2026-11-22 17:13:35', '2026-11-22 17:13:35', '2026-11-23 01:13:36', 'search'], [89138016, 15006768, '2026-11-22 17:10:33', '猛猛播吃鸡 有感觉吗', None, 83, '2026-11-22 17:13:35', '2026-11-22 17:13:35', '2026-11-23 01:13:36', 'search'], [20168554, 10511337, '2026-11-23 00:09:15', '钢铁指挥官 低分段菜鸡互啄', '钢铁指挥官', 21, '2026-11-23 01:13:36', '2026-11-23 01:13:36', '2026-11-23 06:30:13', 'search'], [17257723, 26136956, '2026-11-22 21:05:14', '先玩这个再玩那个 6ω9', None, 200, '2026-11-23 01:13:36', '2026-11-23 01:13:36', '2026-11-23 06:30:13', 'search'], [470646453, 1829184936, '2026-11-23 07:10:25', '钢铁指挥官', '钢铁指挥官', 336, '2026-11-23 11:02:34', '2026-11-23 11:02:34', '2026-11-23 20:18:08', 'search'], [444746395, 25418636, '2026-11-23 19:58:28', '【钢铁指挥官】刚杯，201群雄内战', '钢铁指挥官', 2087, '2026-11-23 20:18:08', '2026-11-23 20:18:08', '2026-11-24 08:05:54', 'search'], [773870, 1358233, '2026-11-23 18:10:22', '我是炸鱼王', '钢铁指挥官', 1097, '2026-11-23 20:18:08', '2026-11-23 20:18:08', '2026-11-24 08:05:54', 'search'], [490865688, 1856652141, '2026-11-23 18:26:54', '我理解woot了', '钢铁指挥官', 283, '2026-11-23 20:18:08', '2026-11-23 20:18:08', '2026-11-24 08:05:54', 'search'], [11492924, 2524118, '2026-11-23 19:31:01', '玩！！！！', '钢铁指挥官', 112, '2026-11-23 20:18:08', '2026-11-23 20:18:08', '2026-11-24 08:05:54', 'search'], [167128185, 12904683, '2026-11-23 19:24:59', '亚顿之矛被寡妇雷炸下来了！【星际争霸2】', '钢铁指挥官', 4277, '2026-11-23 20:18:08', '2026-11-23 20:18:08', '2026-11-24 08:05:54', 'search'], [3546718723377322, 1730465904, '2026-11-23 18:31:34', '史诗机甲之星际指挥官', None, 543, '2026-11-23 20:18:08', '2026-11-23 20:18:08', '2026-11-24 08:05:54', 'search'], [421203213, 25328014, '2026-11-23 19:55:06', '本周突变暗地破坏克哈图带观众粉丝过突变', None, 3837, '2026-11-23 20:18:08', '2026-11-23 20:18:08', '2026-11-24 08:05:54', 'search'], [11219102, 897698, '2026-11-23 19:19:49', '断箭 波罗的海指挥所', None, 3193, '2026-11-23 20:18:08', '2026-11-23 20:18:08', '2026-11-24 08:05:54', 'search'], [845921, 10525, '2026-11-23 20:13:30', '呐呐！我要当水下君子！', None, 1388, '2026-11-23 20:18:08', '2026-11-23 20:18:08', '2026-11-24 08:05:54', 'search'], [388060087, 32108122, '2026-11-23 19:09:12', 'OW冲刺翡翠支援，目前白金四；有想一起玩的可以一起来', None, 8, '2026-11-23 20:18:08', '2026-11-23 20:18:08', '2026-11-24 08:05:54', 'search'], [1976241812, 1879009590, '2026-11-24 05:58:04', '钢铁指挥官自动观战', '钢铁指挥官', 198, '2026-11-24 08:05:54', '2026-11-24 08:05:54', None, 'search']]

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

    # 飞书同步：每周一次（>=7天）。COS 是权威数据源，飞书只做周更协作看板。
    # 绝大多数轮次只采集不碰飞书，天然规避超时。
    FS_SYNC_DAYS = 7
    fs_result = None
    last_fs = data.get("last_feishu_sync") or ""
    need_sync = True
    if last_fs:
        try:
            d0 = datetime.strptime(last_fs, "%Y-%m-%d %H:%M:%S")
            d1 = datetime.strptime(now, "%Y-%m-%d %H:%M:%S")
            need_sync = (d1 - d0).days >= FS_SYNC_DAYS
        except Exception:
            need_sync = True
    if need_sync:
        try:
            fs_result = feishu_sync(data)
            data["last_feishu_sync"] = now
            try:
                cos_put(data)
            except Exception:
                pass
            notes.append("feishu:" + str(fs_result.get("sessions_created", 0)))
            print("FEISHU_SYNC_DONE", json.dumps(fs_result, ensure_ascii=False))
        except Exception as e:
            notes.append("feishu_fail:" + repr(e)[:80])
            print("FEISHU_SYNC_FAIL", repr(e))
    else:
        notes.append("feishu:skip")

    result = {"ts": now, "status": status, "rooms_found": len(rooms),
              "live_count": len(live_keys), "uid_checked": len(pool),
              "sessions_total": len(sessions_by_key), "streamers_total": len(streamers),
              "backup": backup_done, "feishu": fs_result, "errors": errors, "notes": notes}
    print("RESULT " + json.dumps(result, ensure_ascii=False))
    for k, s in sessions_by_key.items():
        if s.get("hit_keyword"):
            print("HIT " + json.dumps({"live_time": s["live_time"], "uname": s["uname"],
                "title": s["title"], "hit": s["hit_keyword"], "peak": s.get("peak_online", 0),
                "room": s["room_id"]}, ensure_ascii=False))
    return result


def _status():
    d = cos_get()
    hits = [s for s in d.get("sessions", {}).values() if s.get("hit_keyword")]
    return {
        "sessions": len(d.get("sessions", {})),
        "streamers": len(d.get("streamers", {})),
        "polls": len(d.get("poll_log", [])),
        "hit_sessions": len(hits),
        "last_poll": d.get("poll_log", [])[-1] if d.get("poll_log") else None,
        "last_backup": d.get("last_backup"),
        "backups": cos_list(BACKUP_PREFIX),
    }


def import_history():
    """把 GitHub 时代 44 场历史并入 COS（幂等）。"""
    d = cos_get()
    sessions = d.setdefault("sessions", {})
    added = 0
    for row in HISTORY_SEED:
        uid, room, lt, title, hit, peak, first, last, end, source = row
        k = f"{uid}|{lt}"
        if k in sessions:
            sessions[k]["peak_online"] = max(sessions[k].get("peak_online", 0), peak or 0)
            continue
        sessions[k] = {
            "uid": uid, "room_id": room, "live_time": lt, "title": title,
            "hit_keyword": hit, "hit_fields": "title" if hit else "",
            "peak_online": peak or 0, "first_seen": first, "last_seen": last,
            "end_seen": end, "source": source, "uname": "", "tags": "",
        }
        added += 1
    cos_put(d)
    return {"imported": added, "sessions_total": len(sessions)}


# ---------- 飞书多维表格同步 ----------
FS_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FS_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
FS_TOKEN = "W6GibvSbTatW40sdx5icUJNrneg"
FS_TABLE = "tbloZEq73EUyRD96"
FS_STATS = "tblzkQQj1zM45FYF"
FS_BASE = "https://open.feishu.cn/open-apis"
_fs_token = None
_fs_token_exp = 0


def fs_api(path, method="GET", body=None, token=None, params=None):
    url = FS_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    h = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        h["Authorization"] = "Bearer " + token
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def fs_token():
    global _fs_token, _fs_token_exp
    if _fs_token and time.time() < _fs_token_exp:
        return _fs_token
    if not (FS_APP_ID and FS_APP_SECRET):
        raise RuntimeError("FEISHU_APP_ID / FEISHU_APP_SECRET 未配置")
    r = fs_api("/auth/v3/tenant_access_token/internal", "POST",
               {"app_id": FS_APP_ID, "app_secret": FS_APP_SECRET})
    if r.get("code") != 0:
        raise RuntimeError("feishu token: " + str(r.get("msg")))
    _fs_token = r["tenant_access_token"]
    _fs_token_exp = time.time() + r.get("expire", 7200) - 60
    return _fs_token


def fs_existing(token, table, key_field):
    out, offset = {}, 0
    while True:
        r = fs_api(f"/bitable/v1/apps/{FS_TOKEN}/tables/{table}/records",
                   token=token, params={"page_size": 500, "offset": offset})
        items = r.get("data", {}).get("items", [])
        for it in items:
            v = (it.get("fields") or {}).get(key_field)
            if v:
                out[str(v)] = it["record_id"]
        if not r.get("data", {}).get("has_more"):
            break
        offset += len(items)
    return out


def fs_write(token, table, records):
    """records: list of dict(field->value); 已在外部去重。"""
    for i in range(0, len(records), 200):
        batch = records[i:i + 200]
        fs_api(f"/bitable/v1/apps/{FS_TOKEN}/tables/{table}/records/batch_create",
               "POST", {"records": [{"fields": f} for f in batch]}, token=token)
        time.sleep(0.2)


def fs_update(token, table, pairs):
    """pairs: list of (record_id, fields)"""
    for i in range(0, len(pairs), 200):
        batch = pairs[i:i + 200]
        fs_api(f"/bitable/v1/apps/{FS_TOKEN}/tables/{table}/records/batch_update",
               "POST", {"records": [{"record_id": rid, "fields": f} for rid, f in batch]}, token=token)
        time.sleep(0.2)


def feishu_sync(data):
    """把 COS 主库全量同步到飞书：场次表 + 主播统计表。幂等。"""
    token = fs_token()
    sessions = list((data.get("sessions") or {}).values())
    streamers = data.get("streamers") or {}

    def uname(s):
        return s.get("uname") or streamers.get(str(s.get("uid")), {}).get("uname") or f"uid:{s.get('uid')}"

    def ts_ms(s):
        try:
            return int(datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp() * 1000)
        except Exception:
            return 0

    # 场次表
    exist = fs_existing(token, FS_TABLE, "场次ID")
    to_create, to_update = [], []
    for s in sessions:
        key = f"{s.get('uid')}|{s.get('live_time')}"
        room = s.get("room_id")
        f = {
            "文本": key, "开播时间": ts_ms(s.get("live_time")),
            "主播": uname(s), "标题": s.get("title") or "",
            "命中关键词": s.get("hit_keyword") or "",
            "峰值人气": s.get("peak_online") or 0,
            "直播间": f"https://live.bilibili.com/{room}" if room else "",
            "场次ID": key, "观测时长": s.get("end_seen") or s.get("last_seen") or "",
        }
        (to_update if key in exist else to_create).append((exist[key], f) if key in exist else f)
    fs_write(token, FS_TABLE, to_create)
    fs_update(token, FS_TABLE, to_update)

    # 主播统计表
    stat = defaultdict(lambda: {"total": 0, "hit": 0, "peak": 0, "last": ""})
    for s in sessions:
        n = uname(s); v = stat[n]
        v["total"] += 1
        if s.get("hit_keyword"):
            v["hit"] += 1
        v["peak"] = max(v["peak"], s.get("peak_online") or 0)
        lt = s.get("live_time") or ""
        if lt > v["last"]:
            v["last"] = lt
    exist_s = fs_existing(token, FS_STATS, "多行文本")
    sc, su = [], []
    for name, v in sorted(stat.items(), key=lambda kv: -kv[1]["total"]):
        f = {"多行文本": name, "直播场次": v["total"], "命中场次": v["hit"],
             "最高人气": v["peak"], "最近开播": v["last"]}
        (su if name in exist_s else sc).append((exist_s[name], f) if name in exist_s else f)
    fs_write(token, FS_STATS, sc)
    fs_update(token, FS_STATS, su)
    return {"sessions_created": len(to_create), "sessions_updated": len(to_update),
            "streamers_created": len(sc), "streamers_updated": len(su)}


def main_handler(event, context):
    if isinstance(event, dict):
        action = event.get("action")
        if action == "backup":
            data = cos_get()
            return {"backup": weekly_backup(data, now_cn())}
        if action == "restore":
            return restore_from_backup(event.get("key"))
        if action == "status":
            return _status()
        if action == "import_history":
            return import_history()
        if action == "feishu_sync":
            # 手动强制同步到飞书（不用等 7 天）
            data = cos_get()
            r = feishu_sync(data)
            data["last_feishu_sync"] = now_cn()
            cos_put(data)
            return r
    return collect()


if __name__ == "__main__":
    collect()
