# 飞书协作看板 · 已完成配置

## 做好的东西

**多维表格**：https://feishu.cn/base/W6GibvSbTatW40sdx5icUJNrneg
- 表1「直播场次」：44 场历史 + SCF 实时采集，字段含开播时间/主播/标题/命中关键词/峰值人气/直播间/场次ID
- 表2「主播统计」：24 个主播的直播次数/命中场次/最高人气/最近开播（每次同步自动重算）

**仪表盘（可直接发同事）**：
```
https://nwcg0ef2w70.feishu.cn/share/base/dashboard/shrcnMTifZyIGsw9vB0qYppDg3f
```
- 总直播场次（指标卡）
- 主播直播次数排行（排行榜）
- 命中关键词场次（指标卡）
- 主播最高人气（柱状图）
- 每日直播趋势（折线图）
- 分享范围：组织内（tenant）

## 自动化更新（待你最后一步）

代码已写好：`scf/index_cos_feishu.py`
- **飞书每 7 天同步一次**（COS 是权威数据源，飞书只做周更协作看板）
- 每轮 SCF 采集照常每 5 分钟，但绝大多数轮次**不碰飞书**（日志 `feishu:skip`），天然规避超时
- 距上次同步 ≥7 天才执行；失败不影响采集主流程，日志记 `FEISHU_SYNC_FAIL`
- 手动立即刷新：测试事件传 `{"action": "feishu_sync"}`
- 修补历史场次空主播名：测试事件传 `{"action": "fix_uname"}`（修完再跑 feishu_sync 刷新飞书）

## 已知修复记录
历史 44 场首次导入时漏了 uname 字段，导致飞书表主播名空白。已修复：
- HISTORY_SEED 现在带 uname（11 字段）
- `fix_uname` 动作可修补 COS 里已存在的空 uname 场次

**你需要做**：

0. ⚠️ **先把执行超时调到 60 秒**——默认 3 秒必然超时。
   函数配置 → 编辑 → 「执行超时时间」填 **60** → 保存

1. SCF 环境变量**再加两个**（用 .env 里那对飞书凭证）：
   | key | value |
   |---|---|
   | `FEISHU_APP_ID` | 你 .env 里的 app id |
   | `FEISHU_APP_SECRET` | 你 .env 里的 app secret |

2. 把 `scf/index_cos_feishu.py` 全部内容贴进 SCF 代码框 → 部署

3. 测试（SCF 测试事件传 `{}` 或任意），看日志：
   ```
   RESULT {..., "feishu": {"sessions_created": N, ...}, ...}
   ```
   有 `feishu` 字段且无 `FEISHU_SYNC_FAIL` = 成功

之后每 5 分钟：采集 → COS → 飞书，全自动。同事打开上面的仪表盘链接就能看到实时数据。

## 安全
- 飞书凭证只在 SCF 环境变量和本地 .env（已 gitignore），不进代码库
- 分享范围 tenant，仅组织内同事可见
- 机器人（自建应用）身份操作，不用连接器

## 本地同步脚本（备用）
`feishu/sync_to_bitable.py` 可手动跑：`python sync_to_bitable.py <data.json>`
读本地 JSON → 同步飞书。凭证从 .env 读。
