# B站「钢铁指挥官」直播记录器

24 小时自动记录**播过钢铁指挥官的主播**、**每场直播的开播时间**，只数据、不录像。

## 一句话原理

B站没有「按游戏名查历史直播」的接口。所以本工具用两个免费接口组合，从现在起**持续观测**并入库：

| 通道   | 接口                                           | 拿到什么                               |
| ---- | -------------------------------------------- | ---------------------------------- |
| A 发现 | `search/type?search_type=live&keyword=钢铁指挥官` | 此刻正在播的房间、主播、标题、标签、开播时间、命中字段        |
| B 追踪 | `room/v1/Room/get_status_info_by_uids`       | 按 UID 批量查开播状态，覆盖「标题没写关键词但在播该游戏」的情况 |
| C 扩充 | `search/type?search_type=video`              | 近期发钢指视频的 UP 主，加进追踪池                |

场次以 `(主播uid, 开播时间)` 唯一标识，每 5 分钟一轮，重复观测只更新峰值人气，**不会重复计数**。

## 能拿到 / 拿不到

**能拿到**（免费）：主播 uid/昵称、直播间号、开播时间、结束观测时间、标题、标签、分区、峰值人气、命中关键词与字段、历史归档。

**拿不到**：实时弹幕/礼物/收益（不需要）、开播前的历史（工具只能从启动时刻开始积累）、观众画像（付费平台才有）。

> 关键限制：**B站不提供历史回溯**。工具装得越早，数据越全。今天装，今天起算。

## 快速开始

```bash
# 单轮测试
python monitor.py collect --once

# 常驻（前台窗口，关掉即停）
python monitor.py collect

# 或双击 start_forever.bat（崩溃后自动重启）

# 或注册 Windows 计划任务（推荐，每5分钟一轮，最抗崩溃）
# 右键 register_task.ps1 -> 用 PowerShell 运行
```

计划任务管理：

```powershell
Get-ScheduledTask -TaskName BiliMechabellumLiveRecorder
Unregister-ScheduledTask -TaskName BiliMechabellumLiveRecorder -Confirm:$false
```

## 查询与导出

```bash
python query.py status                       # 运行状态、是否停摆
python query.py sessions --hit-only          # 只看命中关键词的场次
python query.py sessions -k 钢指             # 按关键词筛
python query.py sessions --since "2026-11-19 00:00:00"
python query.py streamers                    # 所有追踪到的主播
python query.py export                       # 导出 CSV + Markdown 到 output/
```

## 配置（config.py）

- `KEYWORD`：搜索主关键词，默认「钢铁指挥官」
- `KEYWORD_ALIASES`：命中判定用的别名（钢指 / Mechabellum）
- `WHITELIST_UIDS`：强制追踪的 uid（官方号、重点主播）——即使标题不写关键词也记录
- `POLL_INTERVAL`：轮询间隔（秒），默认 300
- `MAX_TRACK_UIDS`：追踪池上限，默认 150，防止触发风控
- `ENABLE_VIDEO_DISCOVERY`：是否用视频搜索扩充追踪池

## 数据位置

```
data/live.db        SQLite 库（streamers / sessions / snapshots / poll_log）
output/*.csv        导出文件（UTF-8 BOM，Excel 可直接开）
output/*.md         汇总报告
```

## 风控与合规

- 只调公开 Web 接口，不登录、不破解 WBI 签名、不碰Cookie 中的 SESSDATA。
- 启动时访问首页取匿名 `buvid3`，请求间隔 ≥1.2s，412/429 自动退避重试。
- 若 `query.py status` 显示「疑似停摆: 是」或连续多轮 `partial/fail`，多半是触发风控，把 `REQUEST_GAP` 调到 2~3 秒、间隔调大到 600 秒。
- 数据仅用于内部运营统计；遵守 B站服务条款，控制频率，不过度请求。

## 已知边界

- `hit_fields=title/tags` 的场次是**强证据**（标题或标签明确写了关键词）。
- `source=whitelist` 且无 `hit_keyword` 的场次：主播在白名单里但本场标题没写关键词，**可能是也可能不是**在播该游戏，需人工看标题判断——这是免费方案的固有不确定性。
- 主播中途改标题会导致同一场 `title` 被更新为最新值（峰值人气不受影响）。
