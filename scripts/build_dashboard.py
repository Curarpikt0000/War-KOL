#!/usr/bin/env python3
"""War-KOL dashboard 构建器：单文件自包含 HTML。

呈现范式对齐 Eco-and-Volatility-Checker（Chao 2026-09-02 指定补齐四项）：
1. 左侧固定 menu（自动生成 + 主题分组可折叠 + scrollspy 高亮跟随）
2. 日/周/月 三档言论卡片（三份数据全部内嵌，点击只切 display，零请求）
3. 每个 KOL 三层钻取：卡片 → 带日期的时间列表 → 单条详情展开
4. 世界地图 section（第二 row），各地域军事走向汇总，同样带日/周/月三档

★ scrollspy 只认带 .part-num 的顶级标题——Eco 踩过：图内小标题也带 .part-title，
  会掉进「其他」组并让高亮来回跳。
★ 菜单顺序 === DOM 顺序（按分组首个成员的 DOM 位置排序），否则向下滚动时高亮乱窜。
★ 禁 emoji（本机无 emoji 字体，headless 渲染全变 □）→ 用 CSS 色块。
"""
import html
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from world_map import MAP_CSS, world_map_svg  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "dashboard", "index.html")

BG, PANEL, CARD2 = "#22262b", "#2b3036", "#262b31"
FG, MUTED, GRID = "#d8dee9", "#8a929c", "#3b424a"
ACCENT = "#88c0d0"
THEATER_COLOR = {
    "俄乌": "#bf616a", "中东": "#d08770", "印太": "#ebcb8b",
    "南亚": "#a3be8c", "非洲": "#88c0d0", "拉美": "#b48ead",
    "军工与战略": "#81a1c1", "未分类": "#6c757d",
}
DIR_COLOR = {"升级": "#bf616a", "僵持": "#ebcb8b", "降级": "#a3be8c", "未表态": "#6c757d"}
STAR_COLOR = {5: "#a3be8c", 4: "#88c0d0", 3: "#ebcb8b", 2: "#d08770", 1: "#bf616a"}
PERIOD_LABEL = {"day": "本日", "week": "本周", "month": "本月"}
PERIOD_DAYS = {"day": 1, "week": 7, "month": 30}


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


def all_statements():
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
    seen, out = set(), []
    for r in recs:
        k = (r.get("kol"), r.get("source_url"))
        if r.get("status") != "ok" or not r.get("source_url") or k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def slice_period(stmts, period):
    """按【实际发表日】切档。无发表日者不进任何档位——
    绝不用抓取日顶替（AGENTS.md 数据纪律）。"""
    cutoff = date.today() - timedelta(days=PERIOD_DAYS[period])
    out = []
    for s in stmts:
        p = s.get("published_on")
        if not p:
            continue
        try:
            if date.fromisoformat(p) >= cutoff:
                out.append(s)
        except Exception:
            continue
    return out


# ── 战区雷达 ────────────────────────────────────────────────
def radar_svg(counter):
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
    poly = (f'<polygon points="{" ".join(pts)}" fill="{ACCENT}" fill-opacity=".22" '
            f'stroke="{ACCENT}" stroke-width="2"/>')
    return (f'<svg viewBox="0 0 420 400" width="100%" style="max-width:460px">'
            f'{"".join(rings)}{"".join(axes)}{poly}{"".join(dots)}{"".join(txts)}</svg>')


# ── 时间线 ──────────────────────────────────────────────────
def timeline_html(stmts):
    ev = []
    for s in stmts:
        p = s.get("published_on")
        if not p:
            continue
        try:
            ev.append((date.fromisoformat(p), s))
        except Exception:
            continue
    if not ev:
        return ('<p class="empty">暂无带已核实发表日的言论。'
                '（发表日查不到者按纪律留空，不用抓取日顶替）</p>')
    ev.sort(key=lambda x: x[0])
    d0, d1 = ev[0][0], ev[-1][0]
    span = max((d1 - d0).days, 1)
    Wd = max(1100, span * 3)
    rows = []
    for i, (d, s) in enumerate(ev):
        x = 60 + (d - d0).days / span * (Wd - 120)
        up = i % 2 == 0
        y_dot, y_box = 150, (40 if up else 190)
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
    axis = f'<line x1="40" y1="150" x2="{Wd-40}" y2="150" stroke="{GRID}" stroke-width="2"/>'
    return (f'<div class="tl-wrap"><svg width="{Wd}" height="270">{axis}{"".join(rows)}</svg></div>'
            f'<div class="tl-note">{d0.isoformat()} ~ {d1.isoformat()}，'
            f'共 {len(ev)} 条带已核实发表日的言论，横向滚动查看</div>')


# ── 日/周/月 三档 tab（仿 Eco _kol_period_tabs）───────────────
def period_tabs(group, active="week", counts=None):
    """三档切换。★按钮上直接标条数——否则用户点进空档不知是没数据还是页面坏了。"""
    btns = ""
    for p in ("day", "week", "month"):
        n = "" if counts is None else f'<span class="kp-n">{len(counts.get(p, []))}</span>'
        btns += (f'<button type="button" class="kp-btn{" on" if p == active else ""}" '
                 f'data-kp-group="{group}" data-kp="{p}">{PERIOD_LABEL[p]}{n}</button>')
    return f'<div class="kp-tabs" data-kp-tabs="{group}">{btns}</div>'


def multi_period(render, data_by_period, group, active="week"):
    panes = ""
    for p in ("day", "week", "month"):
        body = render(data_by_period.get(p, []), p)
        style = "" if p == active else ' style="display:none"'
        panes += (f'<div class="kp-pane" data-kp-group="{group}" '
                  f'data-kp-pane="{p}"{style}>{body}</div>')
    return period_tabs(group, active, data_by_period) + panes


# ── 地域走向汇总（世界地图 + 表）────────────────────────────
def region_pane(stmts, period):
    pl = PERIOD_LABEL[period]
    return world_map_svg(stmts, pl)


# ── 言论卡片（日/周/月档）────────────────────────────────────
def statements_pane(stmts, period):
    pl = PERIOD_LABEL[period]
    if not stmts:
        return (f'<div class="kol-overview">{pl}窗口内没有带已核实发表日的言论。'
                f'<br><span style="color:{MUTED}">两个原因，都不是页面故障：'
                f'① 智库长文与深度分析本就不是日更，短窗口天然稀疏；'
                f'② 发表日抽取不到的条目按纪律留空、不计入时间档'
                f'（绝不用抓取日顶替）。完整内容见下方「观点全景」。</span></div>')
    by_t = defaultdict(list)
    for s in stmts:
        by_t[s.get("theater", "未分类")].append(s)
    dirs = Counter(s.get("direction") for s in stmts)
    head = (f'<div class="kol-overview">{pl}共 <b>{len(stmts)}</b> 条言论，'
            f'覆盖 <b>{len(by_t)}</b> 个战区，'
            f'涉及 <b>{len({s["kol"] for s in stmts})}</b> 位 KOL。方向分布：'
            + " ".join(f'<span class="badge" style="background:{DIR_COLOR[d]}22;'
                       f'color:{DIR_COLOR[d]};border-color:{DIR_COLOR[d]}66">{d} {c}</span>'
                       for d, c in dirs.most_common() if d) + '</div>')
    blocks = []
    for t, items in sorted(by_t.items(), key=lambda kv: -len(kv[1])):
        col = THEATER_COLOR.get(t, MUTED)
        items.sort(key=lambda s: s.get("published_on") or "", reverse=True)
        cards = []
        for s in items[:18]:
            dc = DIR_COLOR.get(s.get("direction"), MUTED)
            dd = s.get("published_on") or "日期未核实"
            unv = "" if s.get("date_status") == "verified" else " sc-unv"
            summ = esc((s.get("summary") or "")[:230]) or "（该来源摘要为空，请直接看原文）"
            cards.append(
                f'<div class="scard" style="border-top-color:{dc}">'
                f'<div class="sc-top">'
                f'<span class="sc-dir" style="background:{dc}22;color:{dc};'
                f'border-color:{dc}66">{esc(s.get("direction"))}</span>'
                f'<span class="sc-date{unv}">{esc(dd)}</span></div>'
                f'<div class="sc-kol"><span class="tdot" style="background:{col}"></span>'
                f'{esc(s.get("kol", "")[:32])}</div>'
                f'<div class="sc-title">{esc(s.get("title", "")[:96])}</div>'
                f'<div class="sc-sum">{summ}</div>'
                f'<a class="sc-src" href="{esc(s.get("source_url"))}" target="_blank" '
                f'rel="noopener">原始出处 →</a></div>')
        more = (f'<div class="pmore">另有 {len(items)-18} 条，见下方观点全景</div>'
                if len(items) > 18 else "")
        blocks.append(
            f'<div class="tgroup"><div class="thead" style="border-color:{col}">'
            f'<span class="tdot" style="background:{col}"></span>{esc(t)}'
            f'<span class="tn">{len(items)} 条</span></div>'
            f'<div class="scard-grid">{"".join(cards)}</div>{more}</div>')
    return head + "".join(blocks)


# ── KOL 卡片：三层钻取 ──────────────────────────────────────
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
            sr = k.get("rating") or ""
            sn = int(sr[0]) if sr and sr[0].isdigit() else 3
            warn = ""
            if k.get("watchlist"):
                warn = '<div class="warn">监测对象 · 低可信度，需交叉验证</div>'
            elif k.get("quality_flag"):
                warn = f'<div class="flag">{esc(k["quality_flag"])}</div>'
            one = esc((k.get("specialty") or "")[:90]) or "—"
            detail = (
                f'<div class="dt"><b>机构</b>{esc(k.get("affiliation") or "unknown")}</div>'
                f'<div class="dt"><b>角色</b>{esc(k.get("role") or "unknown")}</div>'
                f'<div class="dt"><b>四维</b>机构根基 {k.get("score_A")} · '
                f'一手性 {k.get("score_B")} · 命中率 {k.get("score_C")} · '
                f'透明度 {k.get("score_D")} → 加权 {k.get("weighted_score")}</div>'
                f'<div class="dt"><b>评级依据</b>{esc(k.get("rating_reason") or "—")}</div>'
                f'<div class="dt"><b>争议</b>{esc(k.get("controversies") or "none")}</div>')
            # ── 第二层：带日期的时间列表；第三层：单条详情展开 ──
            rows = []
            for s in stmts:
                dd = s.get("published_on") or "日期未核实"
                dstat = s.get("date_status", "unverified")
                dc = DIR_COLOR.get(s.get("direction"), MUTED)
                summ = esc((s.get("summary") or "")[:600]) or "（该来源摘要为空，请直接看原文）"
                rows.append(
                    f'<div class="kd-row">'
                    f'<div class="kd-hd"><span class="kd-caret">▸</span>'
                    f'<span class="dirb" style="background:{dc}"></span>'
                    f'<span class="kd-date{"" if dstat == "verified" else " kd-unv"}">{esc(dd)}</span>'
                    f'<span class="kd-title">{esc(s.get("title", "")[:88])}</span></div>'
                    f'<div class="kd-body"><div class="kd-sum">{summ}</div>'
                    f'<div class="kd-meta">走势判断：<b style="color:{dc}">'
                    f'{esc(s.get("direction"))}</b>　发表日状态：{esc(dstat)}　'
                    f'归属校验：{esc(s.get("attribution_reason") or "—")}</div>'
                    f'<a class="kd-src" href="{esc(s.get("source_url"))}" target="_blank" '
                    f'rel="noopener">打开原始出处 →</a></div></div>')
            drill = ("".join(rows) if rows else
                     '<p class="empty">本轮未抓到可归属于本人的公开言论（如实标注，未编造）</p>')
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
  <div class="sh">言论记录（点每条展开详情 → 再点链接看原文）</div>
  <div class="kd-list">{drill}</div>
</details>''')
        out.append(f'<div class="tgroup"><div class="thead" style="border-color:{col}">'
                   f'<span class="tdot" style="background:{col}"></span>{esc(t)}'
                   f'<span class="tn">{len(people)} 人</span></div>'
                   f'{"".join(cards)}</div>')
    return "".join(out)


def main():
    roster = load("kol_registry.json", [])
    stmts = all_statements()
    by_kol = defaultdict(list)
    for s in stmts:
        by_kol[s["kol"]].append(s)
    for v in by_kol.values():
        v.sort(key=lambda s: s.get("published_on") or "0000", reverse=True)

    periods = {p: slice_period(stmts, p) for p in ("day", "week", "month")}
    tc = Counter(s.get("theater", "未分类") for s in stmts)
    dirc = Counter(s.get("direction") for s in stmts)
    dated = sum(1 for s in stmts if s.get("published_on"))
    nf = len([k for k in roster if not by_kol.get(k.get("name_en") or k.get("name_zh"))])

    kpi = [("名册人数", len(roster), "Notion 单向镜像"),
           ("言论条目", len(stmts), "已过归属校验"),
           ("发表日已核实", dated, f"占 {dated*100//max(len(stmts),1)}%"),
           ("覆盖战区", len([t for t in tc if tc[t]]), "含军工与战略"),
           ("本轮无产出", nf, "如实标注，未编造")]
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
.wrap{{max-width:1240px;margin:0 auto;padding:28px 26px 80px}}
h1{{font-size:26px;margin:0 0 4px;font-weight:600}}
.sub{{color:{MUTED};font-size:13px;margin-bottom:24px}}
/* 左侧固定索引栏 */
.sidenav{{position:fixed;top:0;left:0;width:224px;height:100vh;overflow-y:auto;
  background:{CARD2};border-right:1px solid {GRID};padding:18px 11px 40px;
  z-index:90;transition:transform .25s ease}}
.sidenav-title{{font-size:11.5px;font-weight:700;color:{MUTED};letter-spacing:1px;
  padding:0 8px 10px;border-bottom:1px solid {GRID};margin-bottom:8px}}
.sidenav a{{display:block;font-size:12.5px;line-height:1.35;color:{FG};
  text-decoration:none;padding:7px 9px;border-radius:7px;margin-bottom:2px;
  border-left:3px solid transparent;transition:all .15s}}
.sidenav a:hover{{background:rgba(136,192,208,.12)}}
.sidenav a.sn-active{{background:rgba(136,192,208,.20);border-left-color:{ACCENT};
  font-weight:600}}
.sn-group{{margin-bottom:6px}}
.sn-group-hdr{{display:flex;align-items:center;gap:6px;font-size:11.5px;
  font-weight:700;color:{ACCENT};padding:7px 8px;cursor:pointer;border-radius:6px;
  user-select:none}}
.sn-group-hdr:hover{{background:rgba(136,192,208,.10)}}
.sn-caret{{font-size:10px;transition:transform .18s}}
.sn-collapsed .sn-caret{{transform:rotate(-90deg)}}
.sn-cnt{{margin-left:auto;font-size:10px;color:{MUTED};
  background:rgba(136,192,208,.14);padding:1px 6px;border-radius:8px}}
.sn-group-list{{overflow:hidden;transition:max-height .22s ease;max-height:900px;
  padding-left:4px}}
.sn-collapsed .sn-group-list{{max-height:0}}
#sn-toggle{{display:none}}
@media(min-width:1101px){{body{{padding-left:224px}}}}
@media(max-width:1100px){{
  .sidenav{{transform:translateX(-100%);box-shadow:2px 0 16px rgba(0,0,0,.3)}}
  .sidenav.sn-open{{transform:translateX(0)}}
  #sn-toggle{{display:flex;position:fixed;top:12px;left:12px;z-index:95;
    width:42px;height:42px;align-items:center;justify-content:center;
    background:{ACCENT};color:#1e2429;border:none;border-radius:10px;
    font-size:20px;cursor:pointer}}}}
.part-title{{margin:34px 0 12px;padding-bottom:8px;border-bottom:1px solid {GRID};
  display:flex;align-items:baseline;gap:11px;scroll-margin-top:16px;
  font-size:17px;font-weight:600}}
.part-num{{color:{ACCENT};font-weight:700}}
.part-title .desc{{color:{MUTED};font-size:12.5px;font-weight:400}}
.panel{{background:{PANEL};border:1px solid {GRID};border-radius:10px;padding:18px}}
.kpis{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}}
.kpi{{background:{PANEL};border:1px solid {GRID};border-radius:10px;padding:14px 16px}}
.kv{{font-size:26px;font-weight:600}}
.kl{{font-size:12.5px;margin-top:2px}}
.ks{{font-size:11px;color:{MUTED}}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}}
.ptitle{{font-size:13.5px;margin-bottom:10px;font-weight:600}}
.dline{{display:flex;align-items:center;gap:9px;margin:9px 0}}
.dirb{{width:9px;height:9px;border-radius:2px;display:inline-block;flex:none}}
.dn{{width:52px;font-size:12.5px}}
.dbar{{height:9px;border-radius:3px;min-width:3px}}
.dc{{font-size:12px;color:{MUTED}}}
/* 日/周/月 tab */
.kp-tabs{{display:flex;gap:6px;margin:0 0 13px;flex-wrap:wrap}}
.kp-btn{{font-size:12px;font-weight:600;color:{MUTED};background:{PANEL};
  border:1px solid {GRID};border-radius:7px;padding:5px 15px;cursor:pointer}}
.kp-btn:hover{{border-color:{ACCENT};color:{FG}}}
.kp-btn.on{{background:{ACCENT};border-color:{ACCENT};color:#1e2429}}
.kp-n{{margin-left:6px;font-size:10px;opacity:.75;font-family:ui-monospace,monospace}}
.kol-overview{{background:{PANEL};border:1px solid {GRID};border-radius:9px;
  padding:11px 15px;font-size:12.5px;margin-bottom:13px}}
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
  border-radius:8px;margin-bottom:8px}}
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
.detail{{margin:0 15px 11px;padding:11px 13px;background:{BG};border-radius:7px;
  font-size:12.5px}}
.dt{{margin:5px 0}}
.dt b{{color:{MUTED};font-weight:500;margin-right:8px;font-size:11.5px}}
.sh{{padding:0 15px 6px;font-size:11.5px;color:{MUTED}}}
/* 三层钻取：时间列表 → 单条详情 */
.kd-list{{margin:0 15px 13px}}
.kd-row{{border:1px solid {GRID};border-radius:7px;margin-bottom:5px;
  background:{BG};overflow:hidden}}
.kd-hd{{display:flex;align-items:center;gap:8px;padding:7px 11px;cursor:pointer;
  font-size:12.5px}}
.kd-hd:hover{{background:rgba(136,192,208,.07)}}
.kd-caret{{color:{MUTED};font-size:10px;width:10px;flex:none}}
.kd-date{{color:{ACCENT};font-size:11px;font-family:ui-monospace,monospace;
  flex:none;width:96px}}
.kd-date.kd-unv{{color:{MUTED}}}
.kd-title{{flex:1;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}}
.kd-body{{display:none;padding:2px 13px 12px 30px;font-size:12.5px;
  border-top:1px solid {GRID}}}
.kd-row.open .kd-body{{display:block}}
.kd-sum{{color:{FG};margin:9px 0}}
.kd-meta{{color:{MUTED};font-size:11.5px;margin-bottom:8px}}
.kd-src{{font-size:12px}}
.slist{{margin:0 15px 13px;padding-left:16px}}
.slist li{{font-size:12.5px;margin:5px 0}}
/* 言论卡片网格（Chao 2026-09-02 指定卡片形式，不用列表） */
.scard-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(292px,1fr));
  gap:11px}}
.scard{{background:{PANEL};border:1px solid {GRID};border-top:3px solid;
  border-radius:9px;padding:12px 14px;display:flex;flex-direction:column;
  transition:transform .15s,box-shadow .15s}}
.scard:hover{{transform:translateY(-2px);box-shadow:0 4px 14px rgba(0,0,0,.28)}}
.sc-top{{display:flex;align-items:center;justify-content:space-between;
  margin-bottom:7px}}
.sc-dir{{font-size:10.5px;padding:2px 9px;border-radius:10px;border:1px solid}}
.sc-date{{color:{ACCENT};font-size:10.5px;font-family:ui-monospace,monospace}}
.sc-date.sc-unv{{color:{MUTED}}}
.sc-kol{{display:flex;align-items:center;gap:6px;font-size:12px;
  color:{FG};font-weight:600;margin-bottom:5px}}
.sc-title{{font-size:12.5px;line-height:1.45;margin-bottom:7px}}
.sc-sum{{font-size:11.5px;color:{MUTED};line-height:1.55;flex:1;margin-bottom:9px}}
.sc-src{{font-size:11.5px;align-self:flex-start}}
.pmore{{color:{MUTED};font-size:11.5px;padding:4px 0 0 2px}}
a{{color:{ACCENT};text-decoration:none}} a:hover{{text-decoration:underline}}
.empty{{color:{MUTED};font-size:12.5px;padding:10px 15px}}
.foot{{margin-top:44px;padding-top:16px;border-top:1px solid {GRID};
  color:{MUTED};font-size:11.5px}}
{MAP_CSS}
@media(max-width:880px){{.kpis{{grid-template-columns:repeat(2,1fr)}}
  .two{{grid-template-columns:1fr}}}}
</style></head><body>

<button id="sn-toggle" aria-label="模块索引"
  onclick="document.getElementById('sidenav').classList.toggle('sn-open')">≡</button>
<nav class="sidenav" id="sidenav">
  <div class="sidenav-title">模块索引</div>
  <div id="sidenav-links"></div>
</nav>

<div class="wrap">
<h1>War KOL</h1>
<div class="sub">全球战争分析与走势预测 KOL 每日言论汇总 · 更新于 {now}</div>

<div class="part-title"><span class="part-num">＋</span>总览
  <span class="desc">名册来自 Notion 单向镜像；言论经归属校验，抓不到即如实标注</span></div>
<div class="kpis">{kpi_html}</div>

<div class="part-title"><span class="part-num">＋</span>地域走向
  <span class="desc">各战区军事走向汇总，气泡面积＝言论量、颜色＝主导方向，可切日/周/月</span></div>
{multi_period(region_pane, periods, "map", "month")}

<div class="part-title"><span class="part-num">＋</span>战区雷达
  <span class="desc">全量言论的战区密度分布与走势方向构成</span></div>
<div class="two">
  <div class="panel"><div class="ptitle">战区言论密度</div>{radar_svg(tc)}</div>
  <div class="panel"><div class="ptitle">走势方向分布</div>
    <div style="font-size:12px;color:{MUTED};margin-bottom:12px">
      判断维度为冲突是否升级，非金融多空</div>
    {dir_html or '<p class="empty">暂无数据</p>'}</div>
</div>

<div class="part-title"><span class="part-num">＋</span>言论卡片
  <span class="desc">按实际发表日切档，可切日/周/月；未核实日期者不入档</span></div>
{multi_period(statements_pane, periods, "stmt", "month")}

<div class="part-title"><span class="part-num">＋</span>事件时间线
  <span class="desc">按 KOL 实际发表日排布，横向滚动</span></div>
{timeline_html(stmts)}

<div class="part-title"><span class="part-num">＋</span>观点全景
  <span class="desc">按战区分组，展开看评级依据；每条言论可再展开详情与原文</span></div>
{kol_cards(roster, by_kol)}

<div class="foot">
名册 SSOT = Notion「War KOL List」，本页为单向镜像产物。<br>
评级口径：机构根基 30% · 一手性 25% · 历史命中率 30% · 方法透明度 15%，
群体内百分位定星。入库门槛 3★，南亚战区因结构性原因放宽至 2★（标区域代表）。<br>
标「监测对象」者为指定纳入的低可信度信源，其言论需交叉验证后方可采信。<br>
数据纪律：每条锚 source_url；发表日按实际发表日，查不到留空不用抓取日顶替；
抓不到内容如实标注，绝不编造。
</div>
</div>

<script>
/* 左侧索引栏：自动生成 + 主题分组 + scrollspy。
   ★只认带 .part-num 的顶级标题（Eco 踩坑：图内小标题也带 .part-title，
     会掉进「其他」组并让高亮来回窜）。
   ★菜单顺序 === DOM 顺序（分组按首个成员的 DOM 位置排序）。*/
(function() {{
  var titles = Array.prototype.slice.call(document.querySelectorAll('.part-title'))
                    .filter(function(t) {{ return t.querySelector('.part-num'); }});
  var box = document.getElementById('sidenav-links');
  if (!titles.length || !box) return;
  var GROUPS = [
    {{ name: '总览', match: ['总览'] }},
    {{ name: '地域与走势', match: ['地域走向', '战区雷达'] }},
    {{ name: '言论与时间', match: ['言论卡片', '事件时间线'] }},
    {{ name: 'KOL 观点', match: ['观点全景'] }}
  ];
  function groupOf(label) {{
    for (var g = 0; g < GROUPS.length; g++)
      for (var m = 0; m < GROUPS[g].match.length; m++)
        if (label.indexOf(GROUPS[g].match[m]) >= 0) return g;
    return GROUPS.length;
  }}
  var links = [], bucket = {{}};
  titles.forEach(function(t, i) {{
    var id = t.id || ('sec-' + i); t.id = id;
    var tc = t.cloneNode(true);
    var d = tc.querySelector('.desc'); if (d) d.remove();
    var num = tc.querySelector('.part-num'); if (num) num.remove();
    var label = (tc.textContent || '').trim();
    var a = document.createElement('a');
    a.href = '#' + id; a.textContent = label;
    a.addEventListener('click', function(e) {{
      e.preventDefault();
      document.getElementById(id).scrollIntoView({{behavior:'smooth', block:'start'}});
      if (window.innerWidth <= 1100)
        document.getElementById('sidenav').classList.remove('sn-open');
    }});
    (bucket[groupOf(label)] = bucket[groupOf(label)] || []).push({{a:a, idx:i}});
    links[i] = a;
  }});
  var order = [];
  for (var gi = 0; gi <= GROUPS.length; gi++) {{
    var it = bucket[gi]; if (!it || !it.length) continue;
    order.push({{gIdx:gi, gName:(gi < GROUPS.length) ? GROUPS[gi].name : '其他',
                first:it[0].idx}});
  }}
  order.sort(function(a,b) {{ return a.first - b.first; }});
  order.forEach(function(o) {{
    var items = bucket[o.gIdx];
    var wrap = document.createElement('div'); wrap.className = 'sn-group';
    var hdr = document.createElement('div'); hdr.className = 'sn-group-hdr';
    hdr.innerHTML = '<span class="sn-caret">▾</span>' + o.gName +
                    '<span class="sn-cnt">' + items.length + '</span>';
    var list = document.createElement('div'); list.className = 'sn-group-list';
    items.forEach(function(x) {{ list.appendChild(x.a); }});
    hdr.addEventListener('click', function() {{ wrap.classList.toggle('sn-collapsed'); }});
    wrap.appendChild(hdr); wrap.appendChild(list); box.appendChild(wrap);
  }});
  function onScroll() {{
    var trigger = 120, active = 0;
    for (var i = 0; i < titles.length; i++) {{
      if (titles[i].getBoundingClientRect().top - trigger <= 0) active = i; else break;
    }}
    if ((window.innerHeight + window.scrollY) >= (document.body.scrollHeight - 4))
      active = titles.length - 1;
    links.forEach(function(l, i) {{
      if (!l) return;
      var on = (i === active);
      l.classList.toggle('sn-active', on);
      if (on) {{
        var grp = l.closest ? l.closest('.sn-group') : null;
        if (grp) grp.classList.remove('sn-collapsed');
        var nav = document.getElementById('sidenav');
        if (nav) {{
          var lr = l.getBoundingClientRect(), nr = nav.getBoundingClientRect();
          if (lr.top < nr.top + 24 || lr.bottom > nr.bottom - 24) {{
            var target = nav.scrollTop + (lr.top - nr.top) - nr.height * 0.33;
            if (target < 0) target = 0;
            nav.scrollTo ? nav.scrollTo({{top:target, behavior:'smooth'}})
                         : (nav.scrollTop = target);
          }}
        }}
      }}
    }});
  }}
  window.addEventListener('scroll', onScroll, {{passive:true}});
  window.addEventListener('resize', onScroll, {{passive:true}});
  onScroll();
}})();

/* 日/周/月 切档 + 单条言论展开（事件委托，三份数据已内嵌，点击零请求） */
document.addEventListener('click', function(ev) {{
  var kp = ev.target.closest ? ev.target.closest('.kp-btn') : null;
  if (kp) {{
    var grp = kp.getAttribute('data-kp-group'), sel = kp.getAttribute('data-kp'), i;
    var btns = document.querySelectorAll('.kp-btn[data-kp-group="' + grp + '"]');
    for (i = 0; i < btns.length; i++)
      btns[i].classList.toggle('on', btns[i].getAttribute('data-kp') === sel);
    var panes = document.querySelectorAll('.kp-pane[data-kp-group="' + grp + '"]');
    for (i = 0; i < panes.length; i++)
      panes[i].style.display =
        (panes[i].getAttribute('data-kp-pane') === sel) ? '' : 'none';
    return;
  }}
  var hd = ev.target.closest ? ev.target.closest('.kd-hd') : null;
  if (hd) {{
    var row = hd.parentNode;
    row.classList.toggle('open');
    var c = row.querySelector('.kd-caret');
    if (c) c.textContent = row.classList.contains('open') ? '▾' : '▸';
  }}
}});
</script>
</body></html>'''

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(doc)
    print(f"名册 {len(roster)} 人 | 言论 {len(stmts)} 条 | 带日期 {dated} 条")
    print(f"档位: 日 {len(periods['day'])} / 周 {len(periods['week'])} / 月 {len(periods['month'])}")
    print(f"→ {OUT}  ({os.path.getsize(OUT)//1024} KB)")


if __name__ == "__main__":
    main()
