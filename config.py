# -*- coding: utf-8 -*-
"""配置。关键词、间隔、命中规则集中在此。"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "live.db")

# 主关键词（搜索用）
KEYWORD = "钢铁指挥官"

# 同义词/别名（用于标题/标签文本命中判定；搜索时也会用主词+别名分别搜）
KEYWORD_ALIASES = ["钢铁指挥官", "钢指", "Mechabellum"]

# 白名单 uid：这些主播即使标题不含关键词也会被追踪（官方号/合作主播/重点观察对象）
# 每轮会用 get_status_info_by_uids 批量查他们的开播状态
WHITELIST_UIDS = [
    3494349981616217,  # 钢铁指挥官官方（搜索命中，作为锚点）
]

# 轮询间隔（秒）。24h 常驻时每 5 分钟一轮 ≈ 288 轮/天
POLL_INTERVAL = 300

# 请求间隔（秒），避免 412 风控
REQUEST_GAP = 1.2

# 搜索是否翻页（关键词搜索结果通常只有个位数，翻页意义不大）
SEARCH_PAGES = 1

# 视频搜索扩充白名单：抓近期发布钢指视频的 UP 主，作为候选主播追踪
# 关掉可设为 False
ENABLE_VIDEO_DISCOVERY = True
VIDEO_SEARCH_PAGES = 2   # 每页 20 条，取前 40 条的 UP 主

# 一轮里最多追踪多少个 uid（防止白名单无限膨胀触发风控）
MAX_TRACK_UIDS = 150

# log 保留天数
LOG_RETENTION_DAYS = 90
