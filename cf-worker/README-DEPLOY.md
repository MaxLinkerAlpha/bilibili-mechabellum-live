# Cloudflare Worker 部署清单

代码已全部写好并本地验证通过（抓到 2 场真实直播、时区/去重/命中判定/打包/迁移 SQL 全 PASS）。
**只剩 Cloudflare 账号相关步骤必须 Max 本人做**——我不能替你登录账号或创建云资源。

## 你需要做的（约 10 分钟）

### 1. 注册 / 登录 Cloudflare（免费，无需信用卡）
https://dash.cloudflare.com/sign-up
有账号直接登录。

### 2. 本机登录 wrangler
在 `cf-worker` 目录打开终端：
```bash
cd C:\Users\GameRiver20250501\Downloads\linshi2\bilibili_live_monitor\cf-worker
npx wrangler login
```
会弹浏览器授权，点允许。（wrangler 已装好，不用重装）

### 3. 创建 D1 数据库
```bash
npx wrangler d1 create mechabellum-live
```
**把输出的 `database_id` 复制给我**，我填进 `wrangler.toml`（现在是占位符）。

### 4. 其余我来
拿到 database_id 后我完成：建表 → 导入 44 场历史 → 部署 Worker → 触发首轮验证 → 报告结果。

---

## 之后你要做的没有了

部署完成后：
- Cloudflare 每 5 分钟自动采集，**不依赖你的电脑**
- 看报表：打开 `https://mechabellum-live-recorder.<你的子域>.workers.dev/`
- 或 `/status` 看运行状态、`/sessions.csv` 下载明细、`/run` 手动跑一轮
- 国内访问 workers.dev 若不通，可在 CF 后台给 Worker 绑一个自有域名（可选，不影响采集本身）

## 免费额度（够用，不会收费）
| 资源 | 额度 | 我们的用量 |
|---|---|---|
| Workers 请求 | 100,000/天 | ~288/天（每5分钟） |
| Cron Triggers | 5/账号 | 1 |
| D1 写 | 100,000 行/天 | 每轮约 10 行 → ~3,000/天 |
| D1 存储 | 5 GB | 几十 KB |
| CPU | 10 ms/次 | 网络等待不计，实测逻辑很轻 |

无需信用卡，不会超出免费层。

## 我现在已完成的部分（供核对）

| 项 | 状态 |
|---|---|
| Worker 采集逻辑（双通道 + 视频发现 + 北京时间） | ✅ `src/` |
| D1 表结构 | ✅ `schema.sql` |
| 44 场历史迁移 SQL | ✅ `seed.sql`（242 条） |
| 本地逻辑测试 | ✅ PASS（真实抓到 2 场） |
| 打包验证 | ✅ 15 KB / gzip 5 KB |
| 部署配置 | ⚠️ `wrangler.toml` 待填 database_id |

## 合规
只调 B站公开 Web 接口，不登录、不破解签名、不碰 SESSDATA 或个人信息。数据仅内部运营统计。

## 一个提醒
迁移到 Worker 后，GitHub 仓库那套 Actions 仍在跑（每 6.6 小时）。建议**停掉它**避免两边重复写。等你确认 Worker 稳定后我再帮你禁用 GitHub workflow（改文件提交即可，不删仓库）。
