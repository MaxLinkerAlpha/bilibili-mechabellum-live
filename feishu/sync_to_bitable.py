# -*- coding: utf-8 -*-
"""读 COS 导出的 data.json → 全量同步到飞书多维表格（按场次ID去重，新增+更新峰值）。
凭证从 .env 读，配置从 bitable_config.json 读，均不硬编码。
用法: python sync_to_bitable.py [data.json路径]
"""
import os, sys, json, urllib.request, urllib.parse, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ENV_PATH = os.path.join(ROOT, ".env")
CFG_PATH = os.path.join(HERE, "bitable_config.json")
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "data.json")


def load_env():
    d = {}
    for line in open(ENV_PATH, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


env = load_env()
cfg = json.load(open(CFG_PATH, encoding="utf-8"))
APP_TOKEN = cfg["app_token"]
TABLE_ID = cfg["table_id"]
FIELD = {f["name"]: f["field_id"] for f in cfg["fields"]}
PRIMARY = "文本"  # 主字段名（飞书强制保留），用作场次主键；API 用字段名作 key

BASE = "https://open.feishu.cn/open-apis"


def call(path, method="GET", body=None, token=None, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    h = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        h["Authorization"] = "Bearer " + token
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


t = call("/auth/v3/tenant_access_token/internal", method="POST",
         body={"app_id": env["FEISHU_APP_ID"], "app_secret": env["FEISHU_APP_SECRET"]})["tenant_access_token"]

# 读现有记录，建 场次ID -> record_id 映射
existing = {}
offset = 0
while True:
    r = call(f"/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records",
             token=t, params={"page_size": 500, "offset": offset})
    items = r.get("data", {}).get("items", [])
    for it in items:
        key = (it.get("fields") or {}).get("场次ID") or (it.get("fields") or {}).get("文本")
        if key:
            existing[str(key)] = it["record_id"]
    if not r.get("data", {}).get("has_more"):
        break
    offset += len(items)
print("现有记录:", len(existing))

# 读采集数据
d = json.load(open(DATA, encoding="utf-8"))
sessions = list(d.get("sessions", {}).values())
streamers = d.get("streamers", {})
print("采集场次:", len(sessions))


def ts_ms(s):
    try:
        return int(datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp() * 1000)
    except Exception:
        return None


def uname(s):
    return s.get("uname") or streamers.get(str(s.get("uid")), {}).get("uname") or f"uid:{s.get('uid')}"


def fields_of(s):
    key = f"{s.get('uid')}|{s.get('live_time')}"
    room = s.get("room_id")
    return {
        PRIMARY: key,
        "开播时间": ts_ms(s.get("live_time")) or 0,
        "主播": uname(s),
        "标题": s.get("title") or "",
        "命中关键词": s.get("hit_keyword") or "",
        "峰值人气": s.get("peak_online") or 0,
        "直播间": f"https://live.bilibili.com/{room}" if room else "",
        "场次ID": key,
        "观测时长": (s.get("end_seen") or s.get("last_seen") or ""),
    }

to_create, to_update = [], {}
for s in sessions:
    key = f"{s.get("uid")}|{s.get("live_time")}"
    f = fields_of(s)
    if key in existing:
        to_update[existing[key]] = f
    else:
        to_create.append(f)

print("新增:", len(to_create), "更新:", len(to_update))

# 分批新增（每批<=200）
for i in range(0, len(to_create), 200):
    batch = to_create[i:i + 200]
    r = call(f"/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/batch_create",
             method="POST", body={"records": [{"fields": f} for f in batch]}, token=t)
    if r.get("code") != 0:
        print("新增失败:", r.get("msg"))
    else:
        print("新增成功:", len(batch))
    time.sleep(0.3)

# 分批更新（更新峰值/标题等）
items = list(to_update.items())
for i in range(0, len(items), 200):
    batch = items[i:i + 200]
    r = call(f"/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/batch_update",
             method="POST",
             body={"records": [{"record_id": rid, "fields": f} for rid, f in batch]}, token=t)
    if r.get("code") != 0:
        print("更新失败:", r.get("msg"))
    else:
        print("更新成功:", len(batch))
    time.sleep(0.3)

# ---- 重算主播统计表 ----
STABLE = cfg.get("stats_table_id")
if STABLE:
    from collections import defaultdict
    stat = defaultdict(lambda: {"total": 0, "hit": 0, "peak": 0, "last": ""})
    for s in sessions:
        name = uname(s)
        st = stat[name]
        st["total"] += 1
        if s.get("hit_keyword"):
            st["hit"] += 1
        st["peak"] = max(st["peak"], s.get("peak_online") or 0)
        lt = s.get("live_time") or ""
        if lt > st["last"]:
            st["last"] = lt

    # 拉现有统计记录，按主播名去重
    # 统计表主字段名（建表时飞书默认给“多行文本”，与场次表的“文本”不同）
    STAT_PRIMARY = cfg.get("stats_primary", "多行文本")
    exist_stat = {}
    offset = 0
    while True:
        r = call(f"/bitable/v1/apps/{APP_TOKEN}/tables/{STABLE}/records",
                 token=t, params={"page_size": 500, "offset": offset})
        items = r.get("data", {}).get("items", [])
        for it in items:
            nm = (it.get("fields") or {}).get(STAT_PRIMARY)
            if nm:
                exist_stat[str(nm)] = it["record_id"]
        if not r.get("data", {}).get("has_more"):
            break
        offset += len(items)

    # 按直播场次降序写入（排行）
    ranked = sorted(stat.items(), key=lambda kv: -kv[1]["total"])
    s_create, s_update = [], {}
    for name, v in ranked:
        f = {STAT_PRIMARY: name, "直播场次": v["total"], "命中场次": v["hit"],
             "最高人气": v["peak"], "最近开播": v["last"]}
        if name in exist_stat:
            s_update[exist_stat[name]] = f
        else:
            s_create.append(f)
    print("统计表 新增:", len(s_create), "更新:", len(s_update))
    for i in range(0, len(s_create), 200):
        batch = s_create[i:i + 200]
        r = call(f"/bitable/v1/apps/{APP_TOKEN}/tables/{STABLE}/records/batch_create",
                 method="POST", body={"records": [{"fields": f} for f in batch]}, token=t)
        print("统计新增:", r.get("code"), r.get("msg"))
        time.sleep(0.3)
    items = list(s_update.items())
    for i in range(0, len(items), 200):
        batch = items[i:i + 200]
        r = call(f"/bitable/v1/apps/{APP_TOKEN}/tables/{STABLE}/records/batch_update",
                 method="POST",
                 body={"records": [{"record_id": rid, "fields": f} for rid, f in batch]}, token=t)
        print("统计更新:", r.get("code"), r.get("msg"))
        time.sleep(0.3)

print("同步完成")
