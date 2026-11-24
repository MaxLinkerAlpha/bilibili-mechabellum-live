# -*- coding: utf-8 -*-
"""用 .env 里的飞书自建应用凭证，创建直播记录多维表格 + 字段。
凭证从 .env 读取，不硬编码、不打印明文。
用法: python setup_bitable.py
"""
import os, json, urllib.request, urllib.parse

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
OUT_CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bitable_config.json")


def load_env():
    d = {}
    for line in open(ENV_PATH, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


env = load_env()
APP_ID = env.get("FEISHU_APP_ID")
APP_SECRET = env.get("FEISHU_APP_SECRET")
if not (APP_ID and APP_SECRET):
    raise SystemExit("缺少 FEISHU_APP_ID / FEISHU_APP_SECRET")

BASE = "https://open.feishu.cn/open-apis"


def call(path, method="GET", body=None, token=None, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


# 1. tenant_access_token
r = call("/auth/v3/tenant_access_token/internal", method="POST",
         body={"app_id": APP_ID, "app_secret": APP_SECRET})
if r.get("code") != 0:
    raise SystemExit("token 失败: " + str(r))
TOKEN = r["tenant_access_token"]

# 2. 创建多维表格（App）。当前用户需要有云文档空间权限。
# 用 bitable app 创建接口；失败时给出手工回退指引。
app_body = {
    "name": "钢铁指挥官 · B站直播记录看板",
    "folder_token": "",   # 空=根目录
}
r = call("/bitable/v1/apps", method="POST", body=app_body, token=TOKEN)
if r.get("code") != 0:
    print("AUTO_CREATE_FAIL:", r.get("code"), r.get("msg"))
    print("请手工在飞书新建多维表格，把 URL 发我。")
    raise SystemExit(1)

app_token = r["data"]["app"]["app_token"]
print("创建多维表格成功, app_token:", app_token)

# 3. 默认表改名
r = call(f"/bitable/v1/apps/{app_token}/tables", token=TOKEN)
tables = r.get("data", {}).get("items", [])
if not tables:
    raise SystemExit("无默认表")
table_id = tables[0]["table_id"]
call(f"/bitable/v1/apps/{app_token}/tables/{table_id}", method="PATCH",
     body={"name": "直播场次"}, token=TOKEN)

# 4. 删默认字段，建我们的字段
r = call(f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields", token=TOKEN)
for f in r.get("data", {}).get("items", []):
    call(f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{f['field_id']}",
         method="DELETE", token=TOKEN)

fields = [
    {"field_name": "开播时间", "type": 5, "ui_type": "DateTime", "property": {"date_format": "yyyy-MM-dd HH:mm"}},  # DateTime
    {"field_name": "主播", "type": 1},          # Text
    {"field_name": "标题", "type": 1},
    {"field_name": "命中关键词", "type": 1},
    {"field_name": "峰值人气", "type": 2},      # Number
    {"field_name": "直播间", "type": 1},
    {"field_name": "场次ID", "type": 1},        # uid|live_time 唯一定位
    {"field_name": "观测时长", "type": 1},
]
created = []
for f in fields:
    rr = call(f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
              method="POST", body=f, token=TOKEN)
    if rr.get("code") == 0:
        created.append({"name": f["field_name"], "field_id": rr["data"]["field"]["field_id"]})
    else:
        print("字段创建失败:", f["field_name"], rr.get("msg"))

cfg = {"app_token": app_token, "table_id": table_id, "fields": created}
with open(OUT_CFG, "w", encoding="utf-8") as fp:
    json.dump(cfg, fp, ensure_ascii=False, indent=2)
print("配置已保存:", OUT_CFG)
print("字段:", [c["name"] for c in created])
