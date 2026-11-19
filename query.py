# -*- coding: utf-8 -*-
"""查询与导出：python query.py [sessions|streamers|status|export]"""
import argparse, csv, os, sqlite3, sys
import config as C
import db

OUT_DIR = os.path.join(C.BASE_DIR, "output")


def fmt_duration(a, b):
    from datetime import datetime
    try:
        s = datetime.strptime(a, "%Y-%m-%d %H:%M:%S")
        e = datetime.strptime(b, "%Y-%m-%d %H:%M:%S")
        m = int((e - s).total_seconds() // 60)
        return f"{m//60}h{m%60:02d}m" if m >= 60 else f"{m}m"
    except Exception:
        return "-"


def q_sessions(conn, args):
    sql = "SELECT * FROM sessions WHERE 1=1"
    p = []
    if args.keyword:
        sql += " AND (hit_keyword LIKE ? OR title LIKE ? OR tags LIKE ?)"
        p += [f"%{args.keyword}%"] * 3
    if args.uid:
        sql += " AND uid=?"
        p.append(args.uid)
    if args.since:
        sql += " AND live_time>=?"
        p.append(args.since)
    if args.hit_only:
        sql += " AND hit_keyword IS NOT NULL AND hit_keyword<>''"
    sql += " ORDER BY live_time DESC LIMIT ?"
    p.append(args.limit)
    rows = conn.execute(sql, p).fetchall()
    if not rows:
        print("无数据")
        return rows
    print(f"{'开播时间':<20} {'主播':<18} {'命中':<14} {'峰值':>7} {'时长':>8} 标题")
    print("-" * 110)
    for r in rows:
        dur = fmt_duration(r["live_time"], r["end_seen"] or r["last_seen"]) if r["end_seen"] else "进行中"
        print(f"{r['live_time']:<20} {(r['uname'] or '')[:16]:<18} "
              f"{(r['hit_keyword'] or '-')[:12]:<14} {r['peak_online']:>7} {dur:>8} "
              f"{(r['title'] or '')[:40]}")
    print(f"\n共 {len(rows)} 场")
    return rows


def q_streamers(conn, args):
    rows = conn.execute("""
        SELECT s.*, (SELECT COUNT(*) FROM sessions x WHERE x.uid=s.uid) AS n_sessions
        FROM streamers s ORDER BY n_sessions DESC, last_seen DESC LIMIT ?
    """, (args.limit,)).fetchall()
    if not rows:
        print("无数据")
        return rows
    print(f"{'uid':<18} {'主播':<20} {'来源':<10} {'场次':>5} {'直播间':>12} 最近出现")
    print("-" * 95)
    for r in rows:
        print(f"{str(r['uid']):<18} {(r['uname'] or '')[:18]:<20} {r['source']:<10} "
              f"{r['n_sessions']:>5} {str(r['room_id'] or '-'):>12} {r['last_seen']}")
    print(f"\n共 {len(rows)} 个主播")
    return rows


def q_status(conn, args):
    n_poll = conn.execute("SELECT COUNT(*) FROM poll_log").fetchone()[0]
    last = conn.execute("SELECT * FROM poll_log ORDER BY id DESC LIMIT 1").fetchone()
    print(f"数据库: {C.DB_PATH}")
    print(f"轮询轮次: {n_poll}")
    if last:
        print(f"最后一轮: {last['ts']} 状态={last['status']} "
              f"搜索房间={last['rooms_found']} 在播={last['live_found']} 追踪UID={last['uid_checked']}")
    print(f"主播总数: {conn.execute('SELECT COUNT(*) FROM streamers').fetchone()[0]}")
    print(f"场次总数: {conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]}")
    from datetime import datetime, timedelta
    threshold = (datetime.now() - timedelta(minutes=C.POLL_INTERVAL * 3 + 120)).strftime("%Y-%m-%d %H:%M:%S")
    stale = conn.execute("SELECT COUNT(*) FROM poll_log WHERE ts<?", (threshold,)).fetchone()[0]
    print(f"疑似停摆(最后一轮早于阈值): {'是' if last and last['ts'] < threshold else '否'}")


def q_export(conn, args):
    os.makedirs(OUT_DIR, exist_ok=True)
    import datetime as dt
    # --fixed: CI 固定文件名覆盖，便于 git 只提交变化
    tag = "latest" if getattr(args, "fixed", False) else dt.datetime.now().strftime("%Y%m%d_%H%M")

    # 空结果保护：库里没有任何场次且不是明确要求，拒绝导出（防止接口改版后静默清空）
    n = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    if n == 0 and not getattr(args, "force", False):
        print("拒绝导出：场次表为空。确认无误可加 --force")
        return

    f1 = os.path.join(OUT_DIR, f"sessions_{tag}.csv")
    rows = conn.execute("SELECT * FROM sessions ORDER BY live_time DESC").fetchall()
    with open(f1, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["开播时间", "主播", "uid", "直播间", "标题", "命中关键词", "命中字段",
                    "峰值人气", "首次观测", "最后观测", "下播观测", "来源"])
        for r in rows:
            w.writerow([r["live_time"], r["uname"], r["uid"], r["room_id"], r["title"],
                        r["hit_keyword"] or "", r["hit_fields"], r["peak_online"],
                        r["first_seen"], r["last_seen"], r["end_seen"] or "", r["source"]])

    f2 = os.path.join(OUT_DIR, f"streamers_{tag}.csv")
    rows = conn.execute("""
        SELECT s.*, (SELECT COUNT(*) FROM sessions x WHERE x.uid=s.uid) AS n
        FROM streamers s ORDER BY n DESC, last_seen DESC
    """).fetchall()
    with open(f2, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["uid", "主播", "直播间", "来源", "首次发现", "最近出现", "场次数", "备注"])
        for r in rows:
            w.writerow([r["uid"], r["uname"], r["room_id"] or "", r["source"],
                        r["first_seen"], r["last_seen"], r["n"], r["note"] or ""])

    # Markdown 汇总（高亮命中关键词的场次）
    f3 = os.path.join(OUT_DIR, f"钢指直播汇总_{tag}.md")
    hits = conn.execute("""
        SELECT * FROM sessions WHERE hit_keyword IS NOT NULL AND hit_keyword<>''
        ORDER BY live_time DESC
    """).fetchall()
    all_s = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    with open(f3, "w", encoding="utf-8") as f:
        f.write(f"# 钢铁指挥官 B站直播记录（截至 {dt.datetime.now():%Y-%m-%d %H:%M}）\n\n")
        f.write(f"- 累计场次：**{all_s}**\n")
        f.write(f"- 明确命中关键词场次：**{len(hits)}**\n")
        f.write(f"- 追踪主播数：**{conn.execute('SELECT COUNT(*) FROM streamers').fetchone()[0]}**\n\n")
        f.write("## 命中关键词的场次\n\n")
        f.write("| 开播时间 | 主播 | 标题 | 命中 | 峰值人气 | 直播间 |\n")
        f.write("|---|---|---|---|---:|---|\n")
        for r in hits:
            title = (r["title"] or "").replace("|", "\\|")
            f.write(f"| {r['live_time']} | {r['uname']} | {title} | {r['hit_keyword']} "
                    f"| {r['peak_online']} | https://live.bilibili.com/{r['room_id']} |\n")
    print(f"已导出:\n  {f1}\n  {f2}\n  {f3}")


def main():
    ap = argparse.ArgumentParser(description="查询钢指直播记录")
    sub = ap.add_subparsers(dest="cmd")

    ps = sub.add_parser("sessions", help="查看场次")
    ps.add_argument("--keyword", "-k")
    ps.add_argument("--uid", type=int)
    ps.add_argument("--since", help="'YYYY-MM-DD HH:MM:SS'")
    ps.add_argument("--hit-only", action="store_true", help="只看命中关键词的")
    ps.add_argument("--limit", type=int, default=50)
    ps.set_defaults(func=q_sessions)

    pu = sub.add_parser("streamers", help="查看主播")
    pu.add_argument("--limit", type=int, default=50)
    pu.set_defaults(func=q_streamers)

    st = sub.add_parser("status", help="运行状态")
    st.set_defaults(func=q_status)

    ex = sub.add_parser("export", help="导出 CSV/Markdown")
    ex.add_argument("--fixed", action="store_true", help="固定文件名 latest，供CI覆盖")
    ex.add_argument("--force", action="store_true", help="空库也导出")
    ex.set_defaults(func=q_export)

    a = ap.parse_args()
    conn = db.connect()
    if not hasattr(a, "func"):
        ap.print_help()
    else:
        a.func(conn, a)
    conn.close()


if __name__ == "__main__":
    main()
