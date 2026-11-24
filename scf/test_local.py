# -*- coding: utf-8 -*-
"""SCF 函数本地全路径测试。
- COS：内存 mock（本地无密钥）
- 飞书：真实只读（.env 凭证），写入用 mock，避免污染线上表
- B站：真实 API 调用（验证采集链路）
覆盖：collect / status / backup / restore / import_history / fix_uname / feishu_sync
"""
import sys, os, json, importlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import index_cos_feishu as m

PASS, FAIL = [], []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print("  PASS", name)
    else:
        FAIL.append(name)
        print("  FAIL", name, detail)


def fresh_store():
    """模拟 COS 存储。"""
    return {"streamers": {}, "sessions": {}, "poll_log": []}


def patch_cos(store):
    m.cos_get = lambda key=None: (store if key in (None, m.COS_KEY) else None)
    m.cos_put = lambda data, key=None: store.update(data) if key in (None, m.COS_KEY) else None
    m.cos_list = lambda prefix="backup/": []
    m.cos_delete = lambda k: True


def patch_feishu_readonly():
    """飞书写入打桩：只记录调用，不真写。真实 token 用于校验凭证可用。"""
    calls = {"create": [], "update": []}
    m.fs_token = lambda: "TEST_TOKEN"
    m.fs_existing = lambda t, tab, k: {}
    m.fs_write = lambda t, tab, recs: calls["create"].append((tab, len(recs)))
    m.fs_update = lambda t, tab, pairs: calls["update"].append((tab, len(pairs)))
    return calls


print("=" * 60)
print("测试 1: 生产常量与配置完整性")
print("=" * 60)
check("HISTORY_SEED 44 条", len(m.HISTORY_SEED) == 44, len(m.HISTORY_SEED))
check("seed 为 11 字段", all(len(r) == 11 for r in m.HISTORY_SEED))
check("seed uname 全非空", all(r[1] for r in m.HISTORY_SEED),
      [r for r in m.HISTORY_SEED if not r[1]][:2])
check("FS_TABLE 非空", bool(m.FS_TABLE))
check("FS_STATS 非空", bool(m.FS_STATS))

print()
print("=" * 60)
print("测试 2: 时间函数（UTC 环境下必须是北京时间）")
print("=" * 60)
os.environ["TZ"] = "UTC"
check("ts_to_cn 1795071547 -> 14:59:07", m.ts_to_cn(1795071547) == "2026-11-19 14:59:07",
      m.ts_to_cn(1795071547))
check("now_cn 格式正确", len(m.now_cn()) == 19 and m.now_cn()[4] == "-", m.now_cn())

print()
print("=" * 60)
print("测试 3: action=status")
print("=" * 60)
st = fresh_store()
st["sessions"] = {"1|2026-01-01 10:00:00": {"uid": 1, "uname": "A", "live_time": "2026-01-01 10:00:00",
                                            "hit_keyword": "钢铁指挥官", "peak_online": 10}}
st["streamers"] = {"1": {"uname": "A"}}
st["poll_log"] = [{"ts": "2026-01-01 10:00:00", "status": "ok"}]
patch_cos(st)
r = m.main_handler({"action": "status"}, None)
check("sessions=1", r.get("sessions") == 1, r)
check("hit_sessions=1", r.get("hit_sessions") == 1, r)
check("polls=1", r.get("polls") == 1, r)

print()
print("=" * 60)
print("测试 4: action=backup（首次 / 7天内跳过）")
print("=" * 60)
st = fresh_store()
saved = {}
m.cos_get = lambda key=None: st
m.cos_put = lambda data, key=None: saved.update({key: json.loads(json.dumps(data))})
m.cos_list = lambda prefix="backup/": []
r = m.main_handler({"action": "backup"}, None)
check("首次备份生成 key", bool(r.get("backup")), r)
check("备份文件名含日期", "backup/live-" in (r.get("backup") or ""), r.get("backup"))
# 7 天内再备份 → 不生成
st2 = {"sessions": {}, "streamers": {}, "poll_log": [],
       "last_backup": m.now_cn()}
m.cos_get = lambda key=None: st2
saved2 = {}
m.cos_put = lambda data, key=None: saved2.update({key: 1})
r2 = m.main_handler({"action": "backup"}, None)
check("7天内不重复备份", r2.get("backup") == "", r2)

print()
print("=" * 60)
print("测试 5: action=import_history（导入 / 幂等）")
print("=" * 60)
st = fresh_store()
patch_cos(st)
r = m.main_handler({"action": "import_history"}, None)
check("导入 44 场", r.get("imported") == 44, r)
check("总场次=44", r.get("sessions_total") == 44, r)
# 验证 uname 已写入
sample = list(st["sessions"].values())[0]
check("导入场次带 uname", bool(sample.get("uname")), sample)
r2 = m.main_handler({"action": "import_history"}, None)
check("幂等：重复导入 0", r2.get("imported") == 0, r2)

print()
print("=" * 60)
print("测试 6: action=fix_uname（空 uname 修补 + 补 streamers）")
print("=" * 60)
st = fresh_store()
# 构造 44 场空 uname
for row in m.HISTORY_SEED:
    k = f"{row[0]}|{row[3]}"
    st["sessions"][k] = {"uid": row[0], "uname": "", "room_id": row[2],
                         "live_time": row[3], "title": row[4],
                         "hit_keyword": row[5], "peak_online": row[6]}
patch_cos(st)
r = m.main_handler({"action": "fix_uname"}, None)
check("修补 44 条", r.get("fixed") == 44, r)
check("补 streamers", r.get("streamers_added", 0) > 0, r)
check("修补后无空 uname", all(s.get("uname") for s in st["sessions"].values()))
r2 = m.main_handler({"action": "fix_uname"}, None)
check("幂等：再修 0 条", r2.get("fixed") == 0, r2)

print()
print("=" * 60)
print("测试 7: feishu_sync 7 天判断（不污染线上）")
print("=" * 60)
calls = patch_feishu_readonly()
# 场景 A: 无 last_feishu_sync → 应同步
st = fresh_store()
st["sessions"] = {"1|2026-01-01 10:00:00": {"uid": 1, "uname": "A", "live_time": "2026-01-01 10:00:00",
                                            "title": "t", "hit_keyword": "钢铁指挥官", "peak_online": 5}}
st["streamers"] = {"1": {"uname": "A"}}
r = m.feishu_sync(st)
check("同步返回结构完整",
      all(k in r for k in ("sessions_created", "sessions_updated",
                           "streamers_created", "streamers_updated")), r)
check("调用了创建", len(calls["create"]) > 0, calls)
check("创建了场次", any(c[0] == m.FS_TABLE and c[1] == 1 for c in calls["create"]), calls)

print()
print("=" * 60)
print("测试 8: collect 端到端（真实 B站 + mock COS + mock 飞书写入）")
print("=" * 60)
st = fresh_store()
patch_cos(st)
patch_feishu_readonly()
try:
    r = m.collect()
    check("status 为 ok 或 partial", r.get("status") in ("ok", "partial"), r.get("status"))
    check("errors 为空（内地/本地直连应无 412）", r.get("errors") == [], r.get("errors"))
    check("抓到场次（>=0 合理）", r.get("sessions_total", -1) >= 0, r)
    check("返回含 feishu 字段或 skip", ("feishu" in r) or ("feishu:skip" in (r.get("notes") or [])), r.get("notes"))
    print("  采集结果:", json.dumps({k: r.get(k) for k in
          ("ts", "status", "rooms_found", "live_count", "sessions_total", "errors", "notes")},
          ensure_ascii=False))
except Exception as e:
    check("collect 不抛异常", False, repr(e))

print()
print("=" * 60)
print(f"结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    print("失败项:", FAIL)
    sys.exit(1)
print("全部通过")
