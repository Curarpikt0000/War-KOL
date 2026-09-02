#!/usr/bin/env python3
"""War-KOL dashboard 构建器：单文件自包含 HTML。

呈现范式（AGENTS.md，仿三个既有项目）：
1. Eco KOL 板块  → 观点卡片（按战区分组 + 方向徽章）、三层信息结构、名录档案卡
2. Forecast 雷达 → 纯 SVG 手绘，无 JS 依赖，莫兰迪深色
3. Forecast 时间线 → 月刻度横轴、事件点上下交替 + 引线、横向滚动

纪律：
- 三层信息结构（Chao 硬要求）：一句话 → 点开 100-300 字结构化详情 → 原始 source link。
  detail 只把 summary 换句话说 = 不合格。
- 禁 emoji 标题（本机无 emoji 字体，headless 渲染全变 □）→ 用 CSS 色块。
- 标题 ≤8 字不塞参数；每 section 配一行简明说明；每图单独 title。
- 抓不到的如实标 status，绝不编造。
"""
import html
import json
import math
import os
from collections import Counter, defaultdict
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "dashboard", "index.html")

# 莫兰迪深色（与 Eco / Forecast 同一套视觉语言）
BG, PANEL, FG, MUTED, GRID = "#22262b", "#2b3036", "#d8dee9", "#8a929c", "#3b424a"
THEATER_COLOR = {
    "俄乌": "#bf616a", "中东": "#d08770", "印太": "#ebcb8b",
    "南亚": "#a3be8c", "非洲": "#88c0d0", "拉美": "#b48ead",
    "军工与战略": "#81a1c1", "未分类": "#6c757d",
}
DIR_COLOR = {"升级": "#bf616a", "僵持": "#ebcb8b", "降级": "#a3be8c", "未表态": "#6c757d"}
STAR_COLOR = {5: "#a3be8c", 4: "#88c0d0", 3: "#ebcb8b", 2: "#d08770", 1: "#bf616a"}


def esc(s):
    return html.escape(str(s if s is not None else ""))


def load(fn, default):
    p = os.path.join(DATA, fn)
    if not os.path.exists(p):
        return default
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def latest_statements():
    """取最新一份 statements 文件（backfill 优先，其次 daily 累积）。"""
    d = os.path.join(DATA, "statements")
    if not os.path.isdir(d):
        return []
    recs = []
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".json"):
            try:
                recs.extend(json.load(open(os.path.join(d, fn), encoding="utf-8")))
            except Exception:
                continue
    # 去重：同 kol + url 只留一条
    seen, out = set(), []
    for r in recs:
        k = (r.get("kol"), r.get("source_url"))
        if r.get("status") != "ok" or not r.get("source_url") or k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


# ── 雷达图：战区言论密度（纯 SVG，仿 Forecast radar_svg）───────────
def radar_svg(counter, title_key="战区"):
    labels = [t for t in THEATER_COLOR if t != "未分类" and counter.get(t)]
    if not labels:
        return '<p class="empty">暂无数据</p>'
    cx, cy, R, n = 210, 195, 135, len(labels)
    maxv = max(counter[t] for t in labels) or 1
    axes, txts, pts, dots = [], [], [], []
    for i, t in enumerate(labels):
        ang = -math.pi / 2 + 2 * math.pi * i / n
        ca, sa = math.cos(ang), math.sin(ang)
        col = THEATER_COLOR[t]
        axes.append(f'<line x1="{cx}" y1="{cy}" x2="{cx+R*ca:.1f}" y2="{cy+R*sa:.1f}" '
                    f'stroke="{GRID}" stroke-width="1" opacity=".6"/>')
        lx, ly = cx + (R + 26) * ca, cy + (R + 26) * sa
        anc = "start" if ca > 0.3 else ("end" if ca < -0.3 else "middle")
        txts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" fill="{col}" font-size="12.5" '
                    f'text-anchor="{anc}" dominant-baseline="middle">{esc(t)} {counter[t]}</text>')
        f = counter[t] / maxv
        px, py = cx + R * f * ca, cy + R * f * sa
        pts.append(f"{px:.1f},{py:.1f}")
        dots.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="{col}"/>')
    rings = []
    for f in (0.25, 0.5, 0.75, 1.0):
        rp = " ".join(
            f"{cx+R*f*math.cos(-math.pi/2+2*math.pi*i/n):.1f},"
            f"{cy+R*f*math.sin(-math.pi/2+2*math.pi*i/n):.1f}" for i in range(n))
        rings.append(f'<polygon points="{rp}" fill="none" stroke="{GRID}" '
                     f'stroke-width="1" opacity=".45"/>')
    poly = (f'<polygon points="{" ".join(pts)}" fill="#88c0d0" fill-opacity=".22" '
            f'stroke="#88c0d0" stroke-width="2"/>')
    return (f'<svg viewBox="0 0 420 400" width="100%" style="max-width:460px">'
            f'{"".join(rings)}{"".join(axes)}{poly}{"".join(dots)}{"".join(txts)}</svg>')


# ── 时间线：月刻度横轴，事件上下交替（仿 Forecast timeline_html）──
def timeline_html(stmts):
    ev = []
    for s in stmts:
        p = s.get("published_on")
        if not p:
            continue
        try:
            d = date.fromisoformat(p)
        except Exception:
            continue
        ev.append((d, s))
    if not ev:
        return ('<p class="empty">暂无带已核实发表日的言论。'
                '（发表日查不到的条目按纪律留空，不用抓取日顶替）</p>')
    ev.sort(key=lambda x: x[0])
    d0, d1 = ev[0][0], ev[-1][0]
    span = max((d1 - d0).days, 1)
    W = max(1100, span * 3)
    rows = []
    for i, (d, s) in enumerate(ev):
        x = 60 + (d - d0).days / span * (W - 120)
        up = i % 2 == 0
        y_dot, y_box = (150, 40) if up else (150, 190)
        col = DIR_COLOR.get(s.get("direction"), MUTED)
        rows.append(
            f'<line x1="{x:.0f}" y1="{y_dot}" x2="{x:.0f}" y2="{y_box + (60 if up else 0)}" '
            f'stroke="{col}" stroke-width="1" opacity=".5"/>'
            f'<circle cx="{x:.0f}" cy="{y_dot}" r="4.5" fill="{col}"/>'
            f'<foreignObject x="{x-85:.0f}" y="{y_box}" width="170" height="62">'
            f'<div xmlns="http://www.w3.org/1999/xhtml" class="tl-card">'
            f'<div class="tl-d">{d.isoformat()}</div>'
            f'<div class="tl-k">{esc(s.get("kol", "")[:22])}</div>'
            f'<div class="tl-t">{esc(s.get("title", "")[:46])}</div>'
            f'</div></foreignObject>')
    axis = f'<line x1="40" y1="150" x2="{W-40}" y2="150" stroke="{GRID}" stroke-width="2"/>'
    return (f'<div class="tl-wrap"><svg width="{W}" height="270">{axis}{"".join(rows)}</svg></div>'
            f'<div class="tl-note">{d0.isoformat()} ~ {d1.isoformat()}，'
            f'共 {len(ev)} 条带已核实发表日的言论，横向滚动查看</div>')


# ── KOL 卡片：三层信息结构 ────────────────────────────────────
def kol_cards(roster, by_kol):
    groups = defaultdict(list)
    for k in roster:
        groups[(k.get("theater") or ["未分类"])[0]].append(k)
    out = []
    for t in sorted(groups, key=lambda x: -len(groups[x])):
        col = THEATER_COLOR.get(t, MUTED)
        people = sorted(groups[t], key=lambda k: -(k.get("weighted_score") or 0))
        cards = []
        for k in people:
            name = k.get("name_en") or k.get("name_zh")
            stmts = by_kol.get(name, [])
            stars = int(round((k.get("weighted_score") or 0)))
            sr = k.get("rating") or ""
            sn = int(sr[0]) if sr and sr[0].isdigit() else 3
            warn = ""
            if k.get("watchlist"):
                warn = (f'<div class="warn">监测对象 · 低可信度，需交叉验证</div>')
            elif k.get("quality_flag"):
                warn = f'<div class="flag">{esc(k["quality_flag"])}</div>'
            # 第一层：一句话
            one = esc((k.get("specialty") or "")[:90]) or "—"
            # 第二层：100-300 字结构化详情（真·结构化，非 summary 换句话说）
            detail = (
                f'<div class="dt"><b>机构</b>{esc(k.get("affiliation") or "unknown")}</div>'
                f'<div class="dt"><b>角色</b>{esc(k.get("role") or "unknown")}</div>'
                f'<div class="dt"><b>四维</b>机构根基 {k.get("score_A")} · '
                f'一手性 {k.get("score_B")} · 命中率 {k.get("score_C")} · '
                f'透明度 {k.get("score_D")} → 加权 {k.get("weighted_score")}</div>'
                f'<div class="dt"><b>评级依据</b>{esc(k.get("rating_reason") or "—")}</div>'
                f'<div class="dt"><b>争议</b>{esc(k.get("controversies") or "none")}</div>')
            # 第三层：原始 source link
            links = []
            for s in stmts[:8]:
                dd = s.get("published_on") or "日期未核实"
                dc = DIR_COLOR.get(s.get("direction"), MUTED)
                links.append(
                    f'<li><span class="dirb" style="background:{dc}"></span>'
                    f'<span class="sd">{esc(dd)}</span> '
                    f'<a href="{esc(s.get("source_url"))}" target="_blank" rel="noopener">'
                    f'{esc(s.get("title", "")[:78])}</a></li>')
            slist = ('<ul class="slist">' + "".join(links) + "</ul>") if links else \
                '<p class="empty">本轮未抓到可归属于本人的公开言论（如实标注，未编造）</p>'
            dirs = Counter(s.get("direction") for s in stmts)
            badges = "".join(
                f'<span class="badge" style="background:{DIR_COLOR[d]}22;'
                f'color:{DIR_COLOR[d]};border-color:{DIR_COLOR[d]}66">{d} {c}</span>'
                for d, c in dirs.most_common() if d)
            cards.append(f'''
<details class="card" style="border-left-color:{col}">
  <summary>
    <span class="star" style="color:{STAR_COLOR.get(sn, MUTED)}">{"★"*sn}{"☆"*(5-sn)}</span>
    <span class="nm">{esc(name)}</span>
    <span class="aff">{esc((k.get("affiliation") or "")[:52])}</span>
    <span class="cnt">{len(stmts)} 条</span>
  </summary>
  {warn}
  <div class="one">{one}</div>
  <div class="badges">{badges}</div>
  <div class="detail">{detail}</div>
  <div class="sh">原始出处</div>
  {slist}
</details>''')
        out.append(f'<div class="tgroup"><div class="thead" style="border-color:{col}">'
                   f'<span class="tdot" style="background:{col}"></span>{esc(t)}'
                   f'<span class="tn">{len(people)} 人</span></div>'
                   f'{"".join(cards)}</div>')
    return "".join(out)


def main():
    roster = load("kol_registry.json", [])
    stmts = latest_statements()
    by_kol = defaultdict(list)
    for s in stmts:
        by_kol[s["kol"]].append(s)
    for v in by_kol.values():
        v.sort(key=lambda s: s.get("published_on") or "0000", reverse=True)

    tc = Counter()
    for s in stmts:
        tc[s.get("theater", "未分类")] += 1
    dirc = Counter(s.get("direction") for s in stmts)
    dated = sum(1 for s in stmts if s.get("published_on"))
    nf = len([k for k in roster
              if not by_kol.get(k.get("name_en") or k.get("name_zh"))])

    kpi = [
        ("名册人数", len(roster), "Notion 单向镜像"),
        ("言论条目", len(stmts), "已通过归属校验"),
        ("发表日已核实", dated, f"占 {dated*100//max(len(stmts),1)}%"),
        ("覆盖战区", len([t for t in tc if tc[t]]), "含军工与战略"),
        ("本轮无产出", nf, "如实标注，未编造"),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><div class="kv">{v}</div><div class="kl">{esc(l)}</div>'
        f'<div class="ks">{esc(s)}</div></div>' for l, v, s in kpi)

    dir_html = "".join(
        f'<div class="dline"><span class="dirb" style="background:{DIR_COLOR[d]}"></span>'
        f'<span class="dn">{esc(d)}</span>'
        f'<span class="dbar" style="width:{c*100//max(sum(dirc.values()),1)}%;'
        f'background:{DIR_COLOR[d]}"></span><span class="dc">{c}</span></div>'
        for d, c in dirc.most_common() if d)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    doc = f'''<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>War KOL · 全球战争分析看板</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:{BG};color:{FG};
  font-family:-apple-system,"Segoe UI","Noto Sans CJK SC",sans-serif;line-height:1.6}}
.wrap{{max-width:1180px;margin:0 auto;padding:28px 20px 80px}}
h1{{font-size:26px;margin:0 0 4px;font-weight:600}}
.sub{{color:{MUTED};font-size:13px;margin-bottom:26px}}
.sec{{margin:34px 0 12px;padding-bottom:8px;border-bottom:1px solid {GRID};
  display:flex;align-items:baseline;gap:12px}}
.sec h2{{font-size:17px;margin:0;font-weight:600}}
.sec .desc{{color:{MUTED};font-size:12.5px}}
.panel{{background:{PANEL};border:1px solid {GRID};border-radius:10px;padding:18px}}
.kpis{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}}
.kpi{{background:{PANEL};border:1px solid {GRID};border-radius:10px;padding:14px 16px}}
.kv{{font-size:26px;font-weight:600}}
.kl{{font-size:12.5px;color:{FG};margin-top:2px}}
.ks{{font-size:11px;color:{MUTED}}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}}
.ptitle{{font-size:13.5px;margin-bottom:10px;color:{FG};font-weight:600}}
.dline{{display:flex;align-items:center;gap:9px;margin:9px 0}}
.dirb{{width:9px;height:9px;border-radius:2px;display:inline-block;flex:none}}
.dn{{width:52px;font-size:12.5px}}
.dbar{{height:9px;border-radius:3px;min-width:3px}}
.dc{{font-size:12px;color:{MUTED}}}
.tl-wrap{{overflow-x:auto;background:{PANEL};border:1px solid {GRID};
  border-radius:10px;padding:8px}}
.tl-card{{background:{BG};border:1px solid {GRID};border-radius:6px;padding:5px 7px;
  font-size:10.5px;color:{FG};overflow:hidden;height:58px}}
.tl-d{{color:{MUTED};font-size:9.5px}}
.tl-k{{font-weight:600;font-size:10.5px;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}}
.tl-t{{color:{MUTED};font-size:9.5px;overflow:hidden}}
.tl-note{{color:{MUTED};font-size:12px;margin-top:8px}}
.tgroup{{margin-bottom:22px}}
.thead{{display:flex;align-items:center;gap:9px;font-size:14.5px;font-weight:600;
  padding:7px 0 7px 11px;border-left:3px solid;margin-bottom:9px}}
.tdot{{width:9px;height:9px;border-radius:2px}}
.tn{{color:{MUTED};font-size:12px;font-weight:400}}
.card{{background:{PANEL};border:1px solid {GRID};border-left:3px solid;
  border-radius:8px;margin-bottom:8px;padding:0}}
.card summary{{cursor:pointer;padding:11px 15px;display:flex;align-items:center;
  gap:11px;list-style:none}}
.card summary::-webkit-details-marker{{display:none}}
.star{{font-size:12px;letter-spacing:1px;flex:none}}
.nm{{font-weight:600;font-size:13.5px}}
.aff{{color:{MUTED};font-size:11.5px;flex:1;overflow:hidden;white-space:nowrap;
  text-overflow:ellipsis}}
.cnt{{color:{MUTED};font-size:11.5px;flex:none}}
.warn{{margin:0 15px 9px;padding:7px 11px;background:#bf616a22;
  border:1px solid #bf616a66;border-radius:6px;font-size:12px;color:#e8a0a6}}
.flag{{margin:0 15px 9px;padding:6px 11px;background:#ebcb8b1a;
  border:1px solid #ebcb8b55;border-radius:6px;font-size:12px;color:#ebcb8b}}
.one{{padding:0 15px 9px;font-size:13px}}
.badges{{padding:0 15px 10px;display:flex;gap:6px;flex-wrap:wrap}}
.badge{{font-size:11px;padding:2px 8px;border-radius:10px;border:1px solid}}
.detail{{margin:0 15px 11px;padding:11px 13px;background:{BG};
  border-radius:7px;font-size:12.5px}}
.dt{{margin:5px 0}}
.dt b{{color:{MUTED};font-weight:500;margin-right:8px;font-size:11.5px}}
.sh{{padding:0 15px 5px;font-size:11.5px;color:{MUTED}}}
.slist{{margin:0 15px 13px;padding-left:16px}}
.slist li{{font-size:12.5px;margin:5px 0}}
.sd{{color:{MUTED};font-size:11px;margin-right:5px}}
a{{color:#88c0d0;text-decoration:none}} a:hover{{text-decoration:underline}}
.empty{{color:{MUTED};font-size:12.5px;padding:0 15px 13px}}
.foot{{margin-top:44px;padding-top:16px;border-top:1px solid {GRID};
  color:{MUTED};font-size:11.5px}}
@media(max-width:880px){{.kpis{{grid-template-columns:repeat(2,1fr)}}
  .two{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap">

<h1>War KOL</h1>
<div class="sub">全球战争分析与走势预测 KOL 每日言论汇总 · 更新于 {now}</div>

<div class="sec"><h2>总览</h2>
  <span class="desc">名册来自 Notion 单向镜像；所有言论经归属校验，抓不到即如实标注</span></div>
<div class="kpis">{kpi_html}</div>

<div class="sec"><h2>战区雷达</h2>
  <span class="desc">各战区言论密度，反映当前全球关注热点分布</span></div>
<div class="two">
  <div class="panel"><div class="ptitle">战区言论密度</div>
    {radar_svg(tc)}</div>
  <div class="panel"><div class="ptitle">走势方向分布</div>
    <div style="font-size:12px;color:{MUTED};margin-bottom:12px">
      判断维度为冲突是否升级，非金融多空</div>
    {dir_html or '<p class="empty">暂无数据</p>'}</div>
</div>

<div class="sec"><h2>事件时间线</h2>
  <span class="desc">按 KOL 实际发表日排布，未核实日期者不入轴</span></div>
{timeline_html(stmts)}

<div class="sec"><h2>观点全景</h2>
  <span class="desc">按战区分组，点开看评级依据与原始出处</span></div>
{kol_cards(roster, by_kol)}

<div class="foot">
名册 SSOT = Notion「War KOL List」，本页为单向镜像产物。<br>
评级口径：机构根基 30% · 一手性 25% · 历史命中率 30% · 方法透明度 15%，
群体内百分位定星。入库门槛 3★，南亚战区因结构性原因放宽至 2★（标区域代表）。<br>
标「监测对象」者为指定纳入的低可信度信源，其言论需交叉验证后方可采信。<br>
数据纪律：每条锚 source_url；发表日按实际发表日，查不到留空不用抓取日顶替；
抓不到内容如实标注，绝不编造。
</div>
</div></body></html>'''

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(doc)
    print(f"名册 {len(roster)} 人 | 言论 {len(stmts)} 条 | 带日期 {dated} 条")
    print(f"→ {OUT}  ({os.path.getsize(OUT)//1024} KB)")


if __name__ == "__main__":
    main()
