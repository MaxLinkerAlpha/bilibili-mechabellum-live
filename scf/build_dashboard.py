# -*- coding: utf-8 -*-
"""读 COS 导出的 data.json → 生成暗色单文件 HTML 看板。
用法: python build_dashboard.py [data.json] [output.html]
"""
import json, sys, os, html
from collections import Counter
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "preview_data.json")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BASE, "dashboard.html")

d = json.load(open(SRC, encoding="utf-8"))
sessions = list(d.get("sessions", {}).values())
streamers = d.get("streamers", {})
polls = d.get("poll_log", [])

sessions.sort(key=lambda s: s.get("live_time") or "", reverse=True)
hits = [s for s in sessions if s.get("hit_keyword")]

# 统计
by_day = Counter((s.get("live_time") or "")[:10] for s in hits)
by_streamer = Counter(s.get("uname") or "?" for s in hits)
days = sorted(by_day)
peak = max((s.get("peak_online") or 0) for s in hits) if hits else 0

# 主播→uid→uname 映射（历史 uname 可能空，用 streamers 补）
def uname(s):
    u = s.get("uname") or ""
    if u:
        return u
    return streamers.get(str(s.get("uid")), {}).get("uname") or f"uid:{s.get('uid')}"

def dur(s):
    a, b = s.get("first_seen"), s.get("end_seen") or s.get("last_seen")
    if not a or not b:
        return "-"
    try:
        m = int((datetime.strptime(b, "%Y-%m-%d %H:%M:%S") - datetime.strptime(a, "%Y-%m-%d %H:%M:%S")).total_seconds() // 60)
        return f"{m//60}h{m%60:02d}m" if m >= 60 else f"{m}m"
    except Exception:
        return "-"

def e(x):
    return html.escape(str(x or ""))

rows = []
for s in hits:
    room = s.get("room_id") or ""
    link = f'https://live.bilibili.com/{room}' if room else ""
    room_cell = f'<a href="{link}" target="_blank">{room}</a>' if link else "-"
    rows.append(
        "<tr>"
        f'<td class="mono">{e(s.get("live_time"))}</td>'
        f'<td>{e(uname(s))}</td>'
        f'<td class="title">{e(s.get("title"))}</td>'
        f'<td><span class="tag">{e(s.get("hit_keyword"))}</span></td>'
        f'<td class="num">{s.get("peak_online") or 0}</td>'
        f'<td class="mono">{dur(s)}</td>'
        f'<td class="mono">{room_cell}</td>'
        "</tr>"
    )

day_bars = []
if days:
    mx = max(by_day.values())
    for day in days:
        pct = by_day[day] / mx * 100
        day_bars.append(f'<div class="bar"><span class="bar-label">{day[5:]}</span><div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%"></div></div><span class="bar-val">{by_day[day]}</span></div>')

top_rows = "".join(
    f'<li><span>{e(n)}</span><b>{c}</b></li>' for n, c in by_streamer.most_common(10)
)

last_poll = polls[-1] if polls else {}
gen_time = datetime.now().strftime("%Y-%m-%d %H:%M")

HTML = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>钢铁指挥官 · B站直播记录看板</title>
<style>
:root{{--bg:#0f1115;--panel:#171a21;--panel2:#1e222b;--line:#2a2f3a;--tx:#e6e8ee;--mut:#9aa3b2;--acc:#5b9dff;--hot:#ff5b7f;--ok:#3ecf8e}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--tx);font:14px/1.6 -apple-system,"Segoe UI",sans-serif}}
.wrap{{max-width:1200px;margin:0 auto;padding:32px 20px 60px}}
h1{{font-size:22px;font-weight:600;margin:0 0 6px}}
.sub{{color:var(--mut);font-size:13px;margin-bottom:28px}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:24px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px}}
.card .v{{font-size:30px;font-weight:600;line-height:1.1}}
.card .k{{color:var(--mut);font-size:12px;margin-top:6px}}
.card.acc .v{{color:var(--acc)}} .card.hot .v{{color:var(--hot)}} .card.ok .v{{color:var(--ok)}}
.grid{{display:grid;grid-template-columns:1.4fr 1fr;gap:20px;margin-bottom:24px}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px}}
.panel h2{{font-size:15px;font-weight:600;margin:0 0 16px}}
.bar{{display:flex;align-items:center;gap:10px;margin:7px 0}}
.bar-label{{width:42px;color:var(--mut);font-size:12px;font-family:ui-monospace,monospace}}
.bar-track{{flex:1;height:8px;background:var(--panel2);border-radius:4px;overflow:hidden}}
.bar-fill{{height:100%;background:var(--acc);border-radius:4px}}
.bar-val{{width:24px;text-align:right;color:var(--mut);font-size:12px}}
ol{{margin:0;padding-left:20px}} ol li{{margin:6px 0;display:flex;justify-content:space-between}} ol li b{{color:var(--acc);font-weight:600}}
input{{width:100%;background:var(--panel2);border:1px solid var(--line);border-radius:8px;color:var(--tx);padding:9px 12px;font-size:13px;margin-bottom:12px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;color:var(--mut);font-weight:500;padding:8px 10px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--panel)}}
td{{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}}
tr:hover td{{background:var(--panel2)}}
.mono{{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:var(--mut)}}
.title{{max-width:340px}}
.num{{text-align:right;color:var(--hot)}}
.tag{{background:rgba(91,157,255,.14);color:var(--acc);padding:1px 7px;border-radius:5px;font-size:11px}}
a{{color:var(--acc);text-decoration:none}} a:hover{{text-decoration:underline}}
.foot{{color:var(--mut);font-size:12px;margin-top:20px;text-align:center}}
@media(max-width:800px){{.cards{{grid-template-columns:repeat(2,1fr)}}.grid{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap">
<h1>钢铁指挥官 · B站直播记录看板</h1>
<div class="sub">数据来源：腾讯云 SCF + COS · 生成于 {gen_time} · 全部北京时间(UTC+8)</div>

<div class="cards">
<div class="card acc"><div class="v">{len(hits)}</div><div class="k">命中关键词场次</div></div>
<div class="card"><div class="v">{len(sessions)}</div><div class="k">总记录场次</div></div>
<div class="card"><div class="v">{len(streamers)}</div><div class="k">追踪主播数</div></div>
<div class="card hot"><div class="v">{peak:,}</div><div class="k">单场峰值人气</div></div>
</div>

<div class="grid">
<div class="panel"><h2>每日命中场次</h2>{''.join(day_bars) if day_bars else '<div style="color:var(--mut)">暂无数据</div>'}</div>
<div class="panel"><h2>主播场次 TOP 10</h2><ol>{top_rows if top_rows else '<li>暂无</li>'}</ol></div>
</div>

<div class="panel">
<h2>命中关键词的直播场次</h2>
<input id="q" placeholder="筛选主播 / 标题 / 日期…" oninput="filt()">
<table><thead><tr><th>开播时间</th><th>主播</th><th>标题</th><th>命中</th><th>峰值</th><th>时长</th><th>直播间</th></tr></thead>
<tbody id="tb">{''.join(rows)}</tbody></table>
</div>
<div class="foot">最后采集：{e(last_poll.get('ts'))} · 状态 {e(last_poll.get('status'))}</div>
</div>
<script>
function filt(){{var q=document.getElementById('q').value.toLowerCase();var rs=document.querySelectorAll('#tb tr');rs.forEach(function(r){{r.style.display=r.innerText.toLowerCase().indexOf(q)>-1?'':'none'}})}}
</script></body></html>"""

open(OUT, "w", encoding="utf-8").write(HTML)
print("看板生成:", OUT)
print(f"命中 {len(hits)} 场 / 总 {len(sessions)} 场 / {len(streamers)} 主播")
