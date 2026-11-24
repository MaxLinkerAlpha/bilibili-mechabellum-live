// 与 Python 版 config.py 保持同一口径

export const KEYWORD = "钢铁指挥官";

// 别名用于命中判定（标题/标签/昵称文本），不用于搜索（避免噪音）
export const KEYWORD_ALIASES = ["钢铁指挥官", "钢指", "Mechabellum"];

// 强制追踪的 uid：官方号/重点主播，即使标题不含关键词也记录
export const WHITELIST_UIDS = [
  3494349981616217, // 钢铁指挥官官方
];

export const MAX_TRACK_UIDS = 150;
export const SEARCH_PAGES = 1;
export const ENABLE_VIDEO_DISCOVERY = true;
export const VIDEO_SEARCH_PAGES = 2;

export const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";

// 北京时间：B站返回的 live_time 是 UTC+8 字符串，unix 时间戳必须显式 +8 转换。
// 不能用系统本地时区——Worker 跑在 UTC，会把同一场拆成两条。
const CN_OFFSET_MS = 8 * 60 * 60 * 1000;
export function nowCN() {
  return new Date(Date.now() + CN_OFFSET_MS).toISOString().slice(0, 19).replace("T", " ");
}
export function tsToCN(sec) {
  if (!sec || !Number.isFinite(Number(sec))) return "";
  return new Date(Number(sec) * 1000 + CN_OFFSET_MS).toISOString().slice(0, 19).replace("T", " ");
}
