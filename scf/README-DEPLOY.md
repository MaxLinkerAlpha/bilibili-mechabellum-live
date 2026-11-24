# 腾讯云 SCF 部署清单（COS 持久化版）

## 已完成验证
- ✅ 内地广州地域 **不触发 412**（云端实测 `status: ok`，errors 空，抓到 3 场）
- ✅ 采集逻辑、去重、北京时间、命中判定 —— 全部通过
- ✅ COS 签名 v5 算法 —— 用腾讯云官方示例验证 HttpString SHA1 完全匹配
- ✅ 单次 1.3~1.6 秒 / 12MB 内存 —— 免费额度绰绰有余

## 你要做的（约 5 分钟）

### 1. 建 COS 存储桶
打开：https://console.cloud.tencent.com/cos/bucket
- 点「创建存储桶」
- 地域：**公有云园区-中国-广州**（必须与 SCF 同地域，走内网，最稳）
- 名称：`bili-live-record`（系统自动加 APPID 后缀，你的完整桶名是 **`bili-live-record-1322089290`**）
- **数据冗余策略：选「单 AZ 存储」**（不要选多 AZ——那个额外收费，我们不需要）
- 访问权限：**私有读写**
- 版本控制：**关闭**（我们用自己写的周备份，不用它的计费版本控制）
- 服务端加密：不加密（可选）
- 其他默认

建好后记下：**桶名 `bili-live-record-1322089290`** 和 **地域 `ap-guangzhou`**。

> 若按之前截图选了「多 AZ 存储」，建议重建或忽略——多 AZ 只是多副本，会产生存储容量费用，本项目数据量极小（几十 KB），但没必要花这个钱。

### 2. 拿 API 密钥
打开：https://console.cloud.tencent.com/cam/capi
- 若无密钥，点「新建密钥」
- 记下 **SecretId** 和 **SecretKey**

> 安全：这是你的主账号密钥。更稳妥做法是建一个子账号，只给 COS 读写权限，用子账号密钥。但个人自用场景主账号密钥也可接受。密钥只填在 SCF 环境变量，不进任何代码文件。

### 3. SCF 配环境变量
函数详情页 → 「函数配置」→「编辑」→ 环境变量，加 4 个：

| key | value |
|---|---|
| `COS_SECRET_ID` | 你的 SecretId |
| `COS_SECRET_KEY` | 你的 SecretKey |
| `COS_BUCKET` | 桶名（如 bili-live-1300000000） |
| `COS_REGION` | ap-guangzhou |

保存。

### 4. 换代码
把 `scf/index_cos.py` 全部内容复制 → 粘贴到函数代码框 → 覆盖 → 部署。

文件位置：
```
C:\Users\GameRiver20250501\Downloads\linshi2\bilibili_live_monitor\scf\index_cos.py
```

### 5. 测试
函数详情页 →「测试」→ 运行。

**成功标志**：
```
RESULT {"status": "ok", "errors": [], ...}
```
且**没有** `COS_READ_FAIL` / `COS_WRITE_FAIL`。

第一次跑：COS 里 data.json 不存在，代码自动初始化空库。

### 6. 配定时触发（每5分钟）
函数详情页 →「触发管理」→「创建触发器」：
- 触发方式：**定时触发**
- 名称：`every5min`
- Cron 表达式：`0 */5 * * * * *`（注意是 **7 位**，秒在首位）
  - 含义：每小时第 0 分、5 分、10 分… 的 0 秒触发
- 启用：是

> SCF 定时用 7 位 cron（秒 分 时 日 月 周 年），`0 */5 * * * * *` = 每5分钟。

## 每周自动备份（防抹掉）

代码已内置，**无需额外配置**：
- 每次采集后检查，距上次备份 ≥7 天，自动写一份独立快照到 `backup/live-YYYYMMDD.json`
- **永久保留所有备份，不清理**——从今往后每一份都在（按 Max 要求）
- 备份是独立文件——即使主 `data.json` 被覆盖/误删，备份仍在
- 主库的直播数据（sessions / streamers）**全量保留不删**；只截运行日志 poll_log 到最近 1000 条（不影响直播数据）

**手动触发备份**（SCF 测试事件传）：
```json
{"action": "backup"}
```

**应急恢复**（主数据坏了，从备份还原——测试事件传）：
```json
{"action": "restore"}
```
或指定某份：`{"action": "restore", "key": "backup/live-20260115.json"}`

备份状态在 RESULT 日志的 `backup` 字段可见（有值=本次做了备份）。

## 数据怎么看

- 主数据：COS 桶 `data.json`
- 备份：COS 桶 `backup/` 目录下，每周一份
- 看数据：COS 控制台打开桶 → 点文件 → 在线查看/下载
- 我后续可写静态 HTML 看板（读 COS JSON）

## 免费额度
- SCF：前3月每月100万次调用 + 100万GBs；之后基础包每月50万次（上月全0则不扣费）
- COS：标准存储首年 50GB 免费；请求次数免费额度充足
- 本用途每天 288 次调用、数据几十 KB —— **完全免费**

## 合规
只调 B站公开 Web 接口，不登录、不破解签名、不碰 SESSDATA。控制频率（5分钟），遵守服务条款。

## 下一步（等验证通过后我做）
- 写 COS 数据 → HTML 看板
- 迁移 GitHub 时代 44 场历史到 COS（可选）
- 确认稳定后停用 GitHub Actions（避免重复）
