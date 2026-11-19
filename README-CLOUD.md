# B站钢铁指挥官直播记录器 · 云端版（GitHub Actions）

**不依赖你的电脑。GitHub 云服务器每 5 分钟自动跑一次，数据存在仓库里。**

## 工作原理

```
GitHub 云服务器
  └─ 每5分钟触发 record.yml
       ├─ 拉取仓库（含上次的 live.db）
       ├─ python monitor.py collect --once   ← 采集一轮
       ├─ python query.py export --fixed      ← 导出报表
       └─ git commit & push                   ← 数据回写仓库
```

你在任何设备打开 GitHub 仓库就能看数据，电脑关机不影响。

## 数据在哪看

| 文件 | 内容 |
|---|---|
| `output/钢指直播汇总_latest.md` | **主报表**：命中关键词的场次，含开播时间/主播/标题/峰值人气/直播间链接 |
| `output/sessions_latest.csv` | 所有场次明细（含未命中但被追踪的主播） |
| `output/streamers_latest.csv` | 所有追踪到的主播 |
| `data/live.db` | SQLite 原始库（可用本地 `query.py` 分析） |
| Actions 运行记录 | 每轮日志，点开 Tasks 标签看 |

## 时间口径

所有时间统一为**北京时间 (UTC+8)**。B站返回的开播时间是北京时间；github runner 是 UTC，脚本已用固定 +8 转换（不要用系统本地时区，否则同一场会被拆成两条）。

## 改配置

编辑 `config.py` 后提交，下次运行生效：

- `KEYWORD` 主关键词
- `KEYWORD_ALIASES` 别名（钢指/Mechabellum）
- `WHITELIST_UIDS` 强制追踪的 uid
- `POLL_INTERVAL` 本机常驻才用；云端频率由 `.github/workflows/record.yml` 的 `cron` 决定

改采样频率：编辑 `record.yml` 里的 `cron`。注意 GitHub Actions **最小 5 分钟**，且高峰期可能延迟几分钟到一小时——但对「记录开播时间」无影响，因为时间取自 B站返回的 `live_time`。

## 手动测试

Actions 标签 → 「记录B站钢铁指挥官直播」→ Run workflow → 立即跑一轮。
跑完看 output 文件是否更新、是否有新 commit。

## 故障判断

| 现象 | 原因 / 处理 |
|---|---|
| Actions 连续红色 | 看日志。若连续 3 轮 `接口报错`，多半是 B站 412 风控 |
| 长时间无 commit | 没有新数据时工作流不提交（正常）；或仓库 60 天无活动被 GitHub 自动停用定时任务——手动触发一次即可恢复 |
| 数据突然为 0 | 检查是否接口改版；`query.py` 有空库导出保护 |
| 调度延迟 | GitHub 免费 runner 高峰期正常现象，不影响数据正确性 |

## 风控建议

云端 IP 是 GitHub 数据中心 IP，B站 可能比家庭宽带更容易 412。若频繁失败：
- 把 `config.py` 的 `REQUEST_GAP` 从 1.2 调到 2~3
- 把 workflow cron 从每 5 分钟改成每 10~15 分钟（`- cron: '7-58/10 * * * *'`）
- 采样变稀会略降覆盖，但开播时间取自 B站，单场数据仍准确

## 合规

只调 B站 免费公开 Web 接口，不登录、不破解签名、不碰 SESSDATA 或个人信息。数据仅内部运营统计，控制频率、不过度请求，遵守 B站服务条款。

## 本机可选（不推荐作为主力）

电脑开着时可 `python monitor.py collect` 前台常驻；但云端版已覆盖，本机跑反而可能与云端重复采集同一份数据——不要两边同时跑同一个数据库。
