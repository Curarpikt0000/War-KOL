#!/usr/bin/env python3
"""世界战区地图（纯 SVG，零依赖、零外部请求）。

为什么自绘不用 geopandas/底图文件：
- 本机无 geopandas，也无现成 world geojson；
- dashboard 是【单文件自包含 HTML】，不能依赖外部 tile 服务（离线/内网要能开）；
- 我们只需要「哪个战区热、往哪个方向走」，不需要精确国界。
故用等距圆柱投影(equirectangular)画简化大陆轮廓 + 战区热点气泡。

★ 坐标是真实经纬度，气泡半径/颜色由真实言论数与方向占比驱动，不是装饰。
"""
import math
from collections import Counter

# 等距圆柱投影：lon[-180,180] → x[0,W]，lat[90,-90] → y[0,H]
W, H = 940, 470


def proj(lon, lat):
    return (lon + 180.0) / 360.0 * W, (90.0 - lat) / 180.0 * H


# 简化大陆轮廓（真实经纬度采样点，够辨认即可）
LANDMASSES = [
    # 北美
    [(-168, 65), (-160, 71), (-140, 70), (-125, 70), (-110, 68), (-95, 72), (-80, 73),
     (-65, 66), (-56, 51), (-66, 45), (-70, 41), (-76, 35), (-81, 25), (-88, 30),
     (-97, 26), (-105, 20), (-115, 30), (-125, 40), (-125, 49), (-135, 58), (-152, 59),
     (-168, 65)],
    # 中美/加勒比
    [(-92, 15), (-84, 10), (-78, 9), (-83, 15), (-88, 18), (-92, 15)],
    # 南美
    [(-81, 8), (-75, 11), (-60, 11), (-51, 0), (-44, -3), (-35, -6), (-38, -13),
     (-48, -25), (-58, -35), (-62, -40), (-65, -45), (-69, -53), (-75, -50),
     (-73, -40), (-71, -30), (-70, -18), (-77, -6), (-81, 8)],
    # 欧洲
    [(-10, 36), (-9, 43), (-2, 48), (2, 51), (8, 54), (12, 55), (18, 55), (22, 56),
     (28, 60), (30, 66), (25, 71), (15, 68), (5, 62), (4, 58), (0, 52), (-5, 48),
     (-2, 43), (3, 42), (10, 44), (14, 41), (16, 38), (12, 38), (8, 39), (0, 39),
     (-6, 36), (-10, 36)],
    # 非洲
    [(-17, 15), (-16, 22), (-10, 27), (0, 32), (10, 34), (20, 32), (32, 31), (34, 28),
     (38, 18), (43, 12), (51, 12), (43, 4), (41, -3), (40, -12), (35, -20), (32, -26),
     (28, -33), (20, -35), (16, -28), (12, -18), (9, -5), (5, 4), (-4, 5), (-12, 8),
     (-17, 15)],
    # 亚洲主体
    [(30, 66), (40, 68), (55, 70), (70, 72), (85, 74), (100, 76), (115, 74), (130, 71),
     (145, 70), (160, 68), (170, 66), (178, 65), (170, 60), (160, 58), (150, 59),
     (142, 54), (135, 48), (130, 42), (126, 37), (122, 30), (118, 24), (110, 20),
     (105, 10), (100, 6), (98, 12), (92, 21), (88, 21), (80, 13), (72, 20), (68, 24),
     (60, 25), (56, 26), (48, 30), (44, 37), (36, 36), (34, 31), (36, 25), (43, 12),
     (51, 12), (43, 4), (41, -3), (40, -12), (35, -20), (32, -26), (28, -33),
     (20, -35), (16, -28), (12, -18), (9, -5), (5, 4), (-4, 5), (-12, 8), (-17, 15),
     (-16, 22), (-10, 27), (0, 32), (10, 34), (20, 32), (32, 31), (34, 28), (38, 18),
     (36, 25), (34, 31), (36, 36), (44, 37), (48, 30), (56, 26), (60, 25), (68, 24),
     (72, 20), (80, 13), (88, 21), (92, 21), (98, 12), (100, 6), (105, 10), (110, 20),
     (118, 24), (122, 30), (126, 37), (130, 42), (135, 48), (142, 54), (150, 59),
     (160, 58), (170, 60), (178, 65), (170, 66), (160, 68), (145, 70), (130, 71),
     (115, 74), (100, 76), (85, 74), (70, 72), (55, 70), (40, 68), (30, 66)],
    # 印度次大陆补形
    [(68, 24), (72, 20), (73, 15), (77, 8), (80, 13), (87, 21), (89, 22), (80, 24),
     (75, 27), (70, 25), (68, 24)],
    # 东南亚群岛
    [(95, 5), (105, 1), (115, -3), (120, -9), (110, -8), (100, -2), (95, 5)],
    [(118, 12), (124, 12), (126, 7), (121, 5), (118, 12)],
    # 澳洲
    [(114, -22), (122, -18), (130, -12), (137, -12), (142, -11), (146, -19),
     (150, -25), (153, -28), (150, -37), (145, -38), (138, -35), (129, -32),
     (120, -34), (115, -34), (114, -22)],
    # 日本
    [(130, 31), (135, 34), (140, 36), (142, 40), (145, 44), (141, 45), (139, 40),
     (136, 36), (132, 34), (130, 31)],
    # 英国 / 爱尔兰
    [(-5, 50), (-3, 54), (-5, 58), (-2, 58), (0, 53), (1, 51), (-5, 50)],
    # 格陵兰
    [(-45, 60), (-30, 68), (-22, 75), (-30, 82), (-50, 82), (-60, 76), (-55, 66),
     (-45, 60)],
]

# 战区锚点（真实经纬度，取冲突核心区）
THEATER_GEO = {
    "俄乌":       (33.5, 48.5),
    "中东":       (44.0, 31.0),
    "印太":       (119.0, 22.5),
    "南亚":       (74.0, 31.0),
    "非洲":       (28.0, 12.0),
    "拉美":       (-66.0, 8.0),
    "军工与战略": (-96.0, 39.0),   # 锚在美国本土：国防预算/产能议题主场
}
THEATER_COLOR = {
    "俄乌": "#bf616a", "中东": "#d08770", "印太": "#ebcb8b",
    "南亚": "#a3be8c", "非洲": "#88c0d0", "拉美": "#b48ead",
    "军工与战略": "#81a1c1",
}
DIR_COLOR = {"升级": "#bf616a", "僵持": "#ebcb8b", "降级": "#a3be8c", "未表态": "#6c757d"}

OCEAN, LAND, COAST = "#1e2429", "#333a42", "#454d57"


def _esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _land_paths():
    out = []
    for poly in LANDMASSES:
        pts = " ".join(f"{proj(lo, la)[0]:.1f},{proj(lo, la)[1]:.1f}" for lo, la in poly)
        out.append(f'<polygon points="{pts}" fill="{LAND}" stroke="{COAST}" '
                   f'stroke-width="0.8" stroke-linejoin="round"/>')
    return "".join(out)


def _graticule():
    g = []
    for lon in range(-180, 181, 30):
        x = proj(lon, 0)[0]
        g.append(f'<line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{H}" '
                 f'stroke="#2a3138" stroke-width="0.5"/>')
    for lat in range(-60, 91, 30):
        y = proj(0, lat)[1]
        g.append(f'<line x1="0" y1="{y:.1f}" x2="{W}" y2="{y:.1f}" '
                 f'stroke="#2a3138" stroke-width="0.5"/>')
    return "".join(g)


def world_map_svg(stmts, period_label="", period_key="month"):
    """stmts: 该时间档位内的言论列表。气泡大小=言论数，颜色=主导方向。

    period_key: day/week/month —— 写进气泡 data-period，前端据此过滤明细列表。
    """
    by_t = {}
    for s in stmts:
        t = s.get("theater")
        if t in THEATER_GEO:
            by_t.setdefault(t, []).append(s)
    if not by_t:
        return (f'<div class="map-empty">{_esc(period_label)}窗口内没有可定位的战区言论。'
                f'<br><span style="font-size:11.5px">'
                f'智库分析非日更，短窗口天然稀疏；且发表日抽取不到的条目'
                f'按纪律留空、不入此图（绝不用抓取日顶替）。'
                f'切到更长档位可看到完整分布。</span></div>')

    maxn = max(len(v) for v in by_t.values()) or 1
    bubbles, labels, legend_rows = [], [], []
    for t, items in sorted(by_t.items(), key=lambda kv: -len(kv[1])):
        lon, lat = THEATER_GEO[t]
        x, y = proj(lon, lat)
        n = len(items)
        r = 9 + 26 * math.sqrt(n / maxn)          # 面积正比于条数
        dirs = Counter(s.get("direction") for s in items)
        # 主导方向：排除「未表态」后取最高；全未表态则记未表态
        real = {d: c for d, c in dirs.items() if d and d != "未表态"}
        lead = max(real.items(), key=lambda kv: kv[1])[0] if real else "未表态"
        col = DIR_COLOR.get(lead, "#6c757d")
        tc = THEATER_COLOR.get(t, "#888")
        esc_t = _esc(t)
        tip = f"{t}｜{n} 条｜主导方向 {lead}"
        # ★ 气泡可点：点击弹出该战区言论列表（Chao 2026-09-02 要求）。
        #   热区单独画一个透明大圆，保证小气泡也能点中（半径至少 18px）。
        bubbles.append(
            f'<g class="mp-bub" data-theater="{esc_t}" data-period="{_esc(period_key)}" '
            f'role="button" tabindex="0">'
            f'<title>{_esc(tip)}　—— 点击查看全部言论</title>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{col}" '
            f'fill-opacity="0.30" stroke="{col}" stroke-width="1.8"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" fill="{tc}"/>'
            f'<circle class="mp-hit" cx="{x:.1f}" cy="{y:.1f}" '
            f'r="{max(r, 18.0):.1f}" fill="transparent"/></g>')
        labels.append(
            f'<text x="{x:.1f}" y="{y - r - 7:.1f}" fill="{tc}" font-size="12" '
            f'font-weight="600" text-anchor="middle">{esc_t}</text>'
            f'<text x="{x:.1f}" y="{y + r + 15:.1f}" fill="#c3cad3" font-size="11" '
            f'text-anchor="middle">{n} 条 · {_esc(lead)}</text>')
        pct = " ".join(
            f'<span class="mp-d" style="color:{DIR_COLOR.get(d, "#888")}">{_esc(d)} {c}</span>'
            for d, c in dirs.most_common() if d)
        legend_rows.append(
            f'<tr class="mp-row" data-theater="{esc_t}" '
            f'data-period="{_esc(period_key)}" tabindex="0">'
            f'<td><span class="mp-dot" style="background:{tc}"></span>{esc_t}</td>'
            f'<td class="mp-n">{n}</td><td>{pct}</td>'
            f'<td class="mp-open">查看言论 →</td></tr>')

    dir_legend = "".join(
        f'<span class="mp-lg"><i style="background:{c}"></i>{_esc(d)}</span>'
        for d, c in DIR_COLOR.items())

    return f'''<div class="map-wrap">
<svg viewBox="0 0 {W} {H}" width="100%" preserveAspectRatio="xMidYMid meet">
  <rect width="{W}" height="{H}" fill="{OCEAN}"/>
  {_graticule()}
  {_land_paths()}
  {"".join(bubbles)}
  {"".join(labels)}
</svg>
<div class="mp-legend">气泡面积 = 言论条数，颜色 = 主导走势方向：{dir_legend}
  <span class="mp-hint">点击气泡或下表任意一行，打开该战区的全部言论列表</span></div>
<table class="mp-table"><thead><tr><th>战区</th><th>条数</th><th>方向分布</th>
<th></th></tr></thead>
<tbody>{"".join(legend_rows)}</tbody></table>
</div>'''


MAP_CSS = """
.map-wrap{background:#2b3036;border:1px solid #3b424a;border-radius:10px;padding:12px}
.map-empty{background:#2b3036;border:1px solid #3b424a;border-radius:10px;
  padding:26px;color:#8a929c;font-size:12.5px;text-align:center}
.mp-legend{margin-top:9px;font-size:11.5px;color:#8a929c;display:flex;
  align-items:center;gap:12px;flex-wrap:wrap}
.mp-lg{display:inline-flex;align-items:center;gap:5px;color:#c3cad3}
.mp-lg i{width:9px;height:9px;border-radius:2px;display:inline-block}
.mp-table{width:100%;border-collapse:collapse;margin-top:11px;font-size:12px}
.mp-table th{text-align:left;color:#8a929c;font-weight:500;font-size:11px;
  padding:5px 8px;border-bottom:1px solid #3b424a}
.mp-table td{padding:5px 8px;border-bottom:1px solid #2f353c;color:#d8dee9}
.mp-dot{width:9px;height:9px;border-radius:2px;display:inline-block;margin-right:7px}
.mp-n{font-family:ui-monospace,monospace;color:#c3cad3}
.mp-d{margin-right:9px;font-size:11.5px}
.mp-bub{cursor:pointer;transition:opacity .15s}
.map-wrap:hover .mp-bub{opacity:.7}
.mp-bub:hover{opacity:1}
.mp-bub:hover circle:first-of-type{fill-opacity:.55}
.mp-bub:focus-visible{outline:none}
.mp-bub:focus-visible circle:first-of-type{stroke-width:3.4}
.mp-hint{margin-left:auto;color:#88c0d0;font-size:11.5px}
.mp-row{cursor:pointer}
.mp-row:hover td{background:rgba(136,192,208,.10)}
.mp-row:focus-visible td{background:rgba(136,192,208,.16);outline:none}
.mp-open{color:#88c0d0;font-size:11.5px;white-space:nowrap;text-align:right;opacity:0}
.mp-row:hover .mp-open,.mp-row:focus-visible .mp-open{opacity:1}
"""
