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


def load_translations():
    """中文翻译缓存（scripts/translate.py 产物）。

    键：言论按 source_url，KOL 按 name_en/name_zh。
    缺失即视为未翻译——前端会照实标注，绝不用英文冒充中文。
    """
    p = os.path.join(DATA, "translations.json")
    if not os.path.exists(p):
        return {"stmt": {}, "kol": {}}
    try:
        t = json.load(open(p, encoding="utf-8"))
        t.setdefault("stmt", {})
        t.setdefault("kol", {})
        return t
    except Exception:
        return {"stmt": {}, "kol": {}}


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
        # 轴标签可点 → 打开该战区言论列表（与地图/温度计共用同一弹层）
        txts.append(f'<text class="rd-ax" data-theater="{esc(t)}" role="button" '
                    f'tabindex="0" x="{lx:.1f}" y="{ly:.1f}" fill="{col}" '
                    f'font-size="12.5" text-anchor="{anc}" '
                    f'dominant-baseline="middle">{esc(t)} {counter[t]}'
                    f'<title>点击查看 {esc(t)} 的全部言论</title></text>')
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
            f'<div xmlns="http://www.w3.org/1999/xhtml" class="tl-card" '
            f'data-si="{s.get("_si")}" role="button" tabindex="0" '
            f'title="点击查看该条详情">'
            f'<div class="tl-d">{d.isoformat()}</div>'
            f'<div class="tl-k">{esc(s.get("kol", "")[:22])}</div>'
            f'<div class="tl-t">{esc((s.get("_title_cn") or s.get("title") or "")[:46])}</div>'
            f'</div></foreignObject>')
    axis = f'<line x1="40" y1="150" x2="{Wd-40}" y2="150" stroke="{GRID}" stroke-width="2"/>'
    return (f'<div class="tl-wrap"><svg width="{Wd}" height="270">{axis}{"".join(rows)}</svg></div>'
            f'<div class="tl-note">{d0.isoformat()} ~ {d1.isoformat()}，'
            f'共 {len(ev)} 条带已核实发表日的言论，横向滚动查看。'
            f'<br><span class="l3-tip">点任意卡片 → 中文总结 → '
            f'再点开英文原文与出处</span></div>')


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
    return world_map_svg(stmts, pl, period)


# ── 言论卡片（日/周/月档）────────────────────────────────────
#   ★ 三级钻取（Chao 2026-09-02 拍板，全站统一）：
#     L1 卡片正面 = 中文标题（+日期/方向/KOL）
#     L2 点一次   = 中文言论总结（LLM 译写要点）
#     L3 再点一次 = 英文原文摘要 + 原始出处链接
#   为什么原文放第三级而不是直接给链接：读者先看懂「他说了什么」，
#   再决定要不要花时间读英文原文；出处始终可达，不牺牲可追溯性。
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
                       for d, c in dirs.most_common() if d)
            + '<br><span class="l3-tip">每张卡片三级展开：中文标题 → '
              '中文言论总结 → 英文原文与出处；KOL 名前的色块＝所属战区</span></div>')
    blocks = []
    for t, items in sorted(by_t.items(), key=lambda kv: -len(kv[1])):
        col = THEATER_COLOR.get(t, MUTED)
        items.sort(key=lambda s: s.get("published_on") or "", reverse=True)
        cards = []
        for s in items[:18]:
            dc = DIR_COLOR.get(s.get("direction"), MUTED)
            dd = s.get("published_on") or "日期未核实"
            unv = "" if s.get("date_status") == "verified" else " sc-unv"
            si = s.get("_si")
            tcn = s.get("_title_cn") or s.get("title", "")
            # 出处域名：展开前也能判断信源，不必先点两级才知道是谁发的
            dom = ""
            try:
                dom = (s.get("source_url") or "").split("/")[2].replace("www.", "")
            except Exception:
                dom = ""
            cards.append(
                f'<div class="scard" data-si="{si}" style="border-top-color:{dc}">'
                f'<div class="sc-top">'
                f'<span class="sc-dir" style="background:{dc}22;color:{dc};'
                f'border-color:{dc}66">{esc(s.get("direction"))}</span>'
                f'<span class="sc-date{unv}">{esc(dd)}</span></div>'
                f'<div class="sc-kol"><span class="tdot" style="background:{col}"></span>'
                f'{esc(s.get("kol", "")[:32])}</div>'
                f'<div class="sc-title" title="{esc(tcn)}">{esc(tcn)}</div>'
                f'<div class="sc-dom">{esc(dom)}</div>'
                f'<div class="sc-lv sc-lv1"></div>'
                f'<button type="button" class="sc-step" data-step="2">'
                f'展开中文总结 ▾</button></div>')
        more = (f'<div class="pmore">另有 {len(items)-18} 条，见下方观点全景</div>'
                if len(items) > 18 else "")
        blocks.append(
            f'<div class="tgroup"><div class="thead" style="border-color:{col}">'
            f'<span class="tdot" style="background:{col}"></span>{esc(t)}'
            f'<span class="tn">{len(items)} 条</span></div>'
            f'<div class="scard-grid">{"".join(cards)}</div>{more}</div>')
    return head + "".join(blocks)


# ── KOL 卡片：网格卡片 + 点击弹出钻取层（Chao 2026-09-02 指定卡片形式）──
#   原实现是竖排 <details> 列表行，一屏只看得到几个人。
#   改为响应式卡片网格：一屏纵览全部，点卡片弹出遮罩层看三层详情。
#   言论明细走 JSON payload 由前端渲染，避免 62 张卡片内联 647 条把 HTML 撑爆。
# ── 战区升级温度计（借鉴 AI-News compute_danger_gauge 的加权净占比思路）──
#   为什么要它：现在只有「升级 N 条 / 僵持 M 条」的原始计数，读者得自己心算谁更紧张。
#   温度计把它归一到 -100~+100，一眼看出各战区的紧张度排序。
#   ★ 加权口径（刻意确定性，不交给 LLM 判）：
#     recency 半衰期 30 天（战况变化快，远比 AI 立场易变）× KOL 星级权重。
#     「未表态」不计入分母——它是「没判断」，不是「判断中立」，
#     混进去会把温度稀释成假中性。
def theater_gauge(stmts, roster):
    star_of = {}
    for k in roster:
        nm = k.get("name_en") or k.get("name_zh")
        sr = k.get("rating") or ""
        star_of[nm] = int(sr[0]) if sr and sr[0].isdigit() else 3
    val = {"升级": 1.0, "僵持": 0.0, "降级": -1.0}
    today = date.today()
    agg = defaultdict(lambda: {"num": 0.0, "den": 0.0, "n": 0, "top": []})
    for s in stmts:
        d0 = s.get("direction")
        if d0 not in val:
            continue
        p = s.get("published_on")
        if not p:
            continue
        try:
            days = max(0, (today - date.fromisoformat(p)).days)
        except Exception:
            continue
        recency = 0.5 ** (days / 30.0)
        w = recency * (star_of.get(s.get("kol"), 3) / 5.0)
        t = s.get("theater") or "未分类"
        a = agg[t]
        a["num"] += val[d0] * w
        a["den"] += w
        a["n"] += 1
        a["top"].append((w, s.get("kol"), d0, p))
    out = []
    for t, a in agg.items():
        if a["den"] <= 0:
            continue
        g = round(100 * a["num"] / a["den"], 1)
        a["top"].sort(reverse=True)
        out.append({"theater": t, "gauge": g, "n": a["n"],
                    "top": [(k, dd, pp) for _, k, dd, pp in a["top"][:3]]})
    out.sort(key=lambda x: -x["gauge"])
    return out


def gauge_html(rows):
    if not rows:
        return ('<p class="empty">窗口内没有带已核实发表日的明确方向判断，'
                '无法计算温度（不编造中性值）。</p>')
    items = []
    for r in rows:
        g = r["gauge"]
        # -100..100 → 0..100% 的指针位置
        pos = (g + 100) / 2.0
        col = "#bf616a" if g > 25 else ("#a3be8c" if g < -25 else "#ebcb8b")
        tc = THEATER_COLOR.get(r["theater"], MUTED)
        contrib = "、".join(f'{esc(k[:22])}（{esc(d)}）' for k, d, _ in r["top"])
        items.append(
            f'<div class="gg-row" data-theater="{esc(r["theater"])}" '
            f'role="button" tabindex="0" title="点击查看该战区全部言论">'
            f'<div class="gg-name"><span class="tdot" style="background:{tc}"></span>'
            f'{esc(r["theater"])}</div>'
            f'<div class="gg-track"><div class="gg-mid"></div>'
            f'<div class="gg-pin" style="left:{pos:.1f}%;background:{col}"></div></div>'
            f'<div class="gg-val" style="color:{col}">{g:+.0f}</div>'
            f'<div class="gg-n">{r["n"]} 条</div>'
            f'<div class="gg-top">权重最高：{contrib or "—"}</div></div>')
    return (f'<div class="gg-wrap">'
            f'<div class="gg-scale"><span>-100 降级</span>'
            f'<span>0 僵持</span><span>+100 升级</span></div>'
            f'{"".join(items)}'
            f'<div class="gg-note">口径：方向值（升级+1／僵持0／降级-1）× '
            f'时间衰减（半衰期 30 天）× KOL 星级权重，归一到 -100~+100。'
            f'「未表态」不计入——那是没判断，不是判断中立。'
            f'只用已核实发表日的言论。'
            f'<br><span class="l3-tip">点任意一行 → 该战区言论列表 → '
            f'双击条目看中文总结 → 再点开英文原文与出处</span></div></div>')


def changes_html():
    """立场变化 call-out（数据由 scripts/stance_tracker.py 每日生成）。"""
    d = load("stance_changes.json", {})
    ch = d.get("changes") or []
    if not ch:
        why = d.get("reason") or "本期无立场变化"
        return (f'<div class="kol-overview">暂无可报告的立场转向。'
                f'<br><span style="color:{MUTED}">{esc(why)}。'
                f'转向检测需要至少两份日快照做比对，'
                f'系统每日 09:00 落一份，次日起自动产出。</span></div>')
    KIND = {"escalate": ("转向升级", "#bf616a"),
            "deescalate": ("转向降级", "#a3be8c"),
            "new": ("新表态", "#88c0d0")}
    rows = []
    for c in ch[:24]:
        lab, col = KIND.get(c["kind"], ("变化", MUTED))
        arrow = (f'{esc(c["from"])} → <b style="color:{col}">{esc(c["to"])}</b>'
                 if c.get("from") else f'<b style="color:{col}">{esc(c["to"])}</b>')
        tc = THEATER_COLOR.get(c["theater"], MUTED)
        rows.append(
            f'<div class="ch-row" style="border-left-color:{col}">'
            f'<span class="ch-kind" style="background:{col}22;color:{col};'
            f'border-color:{col}66">{lab}</span>'
            f'<span class="ch-kol">{esc(c["kol"][:34])}</span>'
            f'<span class="ch-th"><span class="tdot" style="background:{tc}"></span>'
            f'{esc(c["theater"])}</span>'
            f'<span class="ch-arrow">{arrow}</span>'
            f'<span class="ch-meta">近 {c["n"]} 条 · 最新 {esc(c["last"])}</span></div>')
    more = (f'<div class="pmore">另有 {len(ch)-24} 条转向未列出</div>'
            if len(ch) > 24 else "")
    return (f'<div class="kol-overview">对比 <b>{esc(d.get("baseline_date"))}</b> 的快照，'
            f'共 <b>{len(ch)}</b> 位 KOL 在某战区改变了主导判断。'
            f'<br><span class="l3-tip">主导方向 = 该 KOL 该战区近 '
            f'{d.get("window_days", 30)} 天言论的方向众数（排除未表态）</span></div>'
            f'{"".join(rows)}{more}')


def kol_cards(roster, by_kol, idx_of, tr):
    groups = defaultdict(list)
    for k in roster:
        groups[(k.get("theater") or ["未分类"])[0]].append(k)
    payload = {}
    out = []
    for t in sorted(groups, key=lambda x: -len(groups[x])):
        col = THEATER_COLOR.get(t, MUTED)
        people = sorted(groups[t], key=lambda k: -(k.get("weighted_score") or 0))
        cards = []
        for k in people:
            name = k.get("name_en") or k.get("name_zh")
            kt = tr["kol"].get(name) or {}
            stmts = by_kol.get(name, [])
            sr = k.get("rating") or ""
            sn = int(sr[0]) if sr and sr[0].isdigit() else 3
            dirs = Counter(s.get("direction") for s in stmts)
            real = {d: c for d, c in dirs.items() if d and d != "未表态"}
            lead = max(real.items(), key=lambda kv: kv[1])[0] if real else "未表态"
            lc = DIR_COLOR.get(lead, MUTED)
            dated = sum(1 for s in stmts if s.get("published_on"))
            flag = ""
            if k.get("watchlist"):
                flag = '<div class="kc-warn">监测对象 · 需交叉验证</div>'
            elif k.get("quality_flag"):
                flag = f'<div class="kc-flag">{esc(k["quality_flag"])}</div>'
            cards.append(
                f'<div class="kcard" data-kol="{esc(name)}" tabindex="0" role="button" '
                f'style="border-top-color:{col}">'
                f'<div class="kc-top">'
                f'<span class="star" style="color:{STAR_COLOR.get(sn, MUTED)}">'
                f'{"★"*sn}{"☆"*(5-sn)}</span>'
                f'<span class="kc-score">{k.get("weighted_score") or "—"}</span></div>'
                f'<div class="kc-name">{esc(name)}</div>'
                f'<div class="kc-aff">{esc((kt.get("aff_cn") or k.get("affiliation") or "")[:58])}</div>'
                f'{flag}'
                f'<div class="kc-spec">{esc((kt.get("spec_cn") or k.get("specialty") or "")[:74]) or "—"}</div>'
                f'<div class="kc-foot">'
                f'<span class="kc-dir" style="background:{lc}22;color:{lc};'
                f'border-color:{lc}66">{esc(lead)}</span>'
                f'<span class="kc-n">{len(stmts)} 条 · {dated} 条有日期</span></div>'
                f'<div class="kc-more">点击查看全部言论 →</div></div>')
            payload[name] = {
                "t": t, "star": sn,
                # 中文优先，未翻译时回落英文原文并由前端标注
                "aff": kt.get("aff_cn") or k.get("affiliation") or "unknown",
                "role": kt.get("role_cn") or k.get("role") or "unknown",
                "spec": kt.get("spec_cn") or k.get("specialty") or "",
                "aff_en": k.get("affiliation") or "",
                "role_en": k.get("role") or "",
                "spec_en": k.get("specialty") or "",
                "sa": k.get("score_A"), "sb": k.get("score_B"),
                "sc": k.get("score_C"), "sd": k.get("score_D"),
                "w": k.get("weighted_score"),
                "why": kt.get("why_cn") or k.get("rating_reason") or "—",
                "why_en": k.get("rating_reason") or "",
                "ctr": kt.get("ctr_cn") or k.get("controversies") or "none",
                "ctr_en": k.get("controversies") or "",
                "cn": bool(kt.get("status") == "ok"),
                "watch": bool(k.get("watchlist")),
                "flag": k.get("quality_flag") or "",
                # 只存全局言论表的下标，明细统一由 STMTS 提供（去重、体积更小）
                "h": [idx_of[(s.get("kol"), s.get("source_url"))] for s in stmts
                      if (s.get("kol"), s.get("source_url")) in idx_of],
            }
        out.append(f'<div class="tgroup"><div class="thead" style="border-color:{col}">'
                   f'<span class="tdot" style="background:{col}"></span>{esc(t)}'
                   f'<span class="tn">{len(people)} 人</span></div>'
                   f'<div class="kcard-grid">{"".join(cards)}</div></div>')
    return "".join(out), payload


def main():
    roster = load("kol_registry.json", [])
    stmts = all_statements()
    by_kol = defaultdict(list)
    for s in stmts:
        by_kol[s["kol"]].append(s)
    for v in by_kol.values():
        v.sort(key=lambda s: s.get("published_on") or "0000", reverse=True)

    periods = {p: slice_period(stmts, p) for p in ("day", "week", "month")}

    # ── 全局言论表：地图弹层、言论卡片、KOL 弹层共用同一份 ──
    #   行格式（定长数组，省体积）：
    #   0 发表日 / 1 日期状态 / 2 方向 / 3 战区 / 4 KOL / 5 英文原标题
    #   6 英文原摘要 / 7 出处URL / 8 归属校验依据
    #   9 中文标题 / 10 中文总结（缺失=未翻译，前端照实标注不冒充）
    tr = load_translations()
    stmt_rows, idx_of = [], {}
    for s in stmts:
        key = (s.get("kol"), s.get("source_url"))
        if key in idx_of:
            continue
        t = tr["stmt"].get(s.get("source_url")) or {}
        idx_of[key] = len(stmt_rows)
        s["_si"] = idx_of[key]
        s["_title_cn"] = t.get("title_cn") or ""
        stmt_rows.append([
            s.get("published_on") or "", s.get("date_status") or "unverified",
            s.get("direction") or "", s.get("theater") or "未分类",
            s.get("kol") or "", s.get("title") or "",
            (s.get("summary") or "")[:700], s.get("source_url") or "",
            s.get("attribution_reason") or "",
            t.get("title_cn") or "", t.get("summary_cn") or "",
        ])
    # 每个时间档位命中的行下标（前端切档时直接取交集，不重算日期）
    period_idx = {p: sorted({idx_of[(s.get("kol"), s.get("source_url"))]
                             for s in v
                             if (s.get("kol"), s.get("source_url")) in idx_of})
                  for p, v in periods.items()}
    tc = Counter(s.get("theater", "未分类") for s in stmts)
    dirc = Counter(s.get("direction") for s in stmts)
    dated = sum(1 for s in stmts if s.get("published_on"))
    nf = len([k for k in roster if not by_kol.get(k.get("name_en") or k.get("name_zh"))])

    ntr = sum(1 for r in stmt_rows if r[9] and r[10])
    kpi = [("名册人数", len(roster), "Notion 单向镜像"),
           ("言论条目", len(stmts), "已过归属校验"),
           ("中文译写", ntr, f"占 {ntr*100//max(len(stmt_rows),1)}%"),
           ("发表日已核实", dated, f"占 {dated*100//max(len(stmts),1)}%"),
           ("覆盖战区", len([t for t in tc if tc[t]]), "含军工与战略"),
           ("本轮无产出", nf, "如实标注，未编造")]
    kpi_html = "".join(
        f'<div class="kpi"><div class="kv">{v}</div><div class="kl">{esc(l)}</div>'
        f'<div class="ks">{esc(s)}</div></div>' for l, v, s in kpi)
    dir_html = "".join(
        f'<div class="dline" data-dir="{esc(d)}" role="button" tabindex="0" '
        f'title="点击查看所有判断为「{esc(d)}」的言论">'
        f'<span class="dirb" style="background:{DIR_COLOR[d]}"></span>'
        f'<span class="dn">{esc(d)}</span>'
        f'<span class="dbar" style="width:{c*100//max(sum(dirc.values()),1)}%;'
        f'background:{DIR_COLOR[d]}"></span><span class="dc">{c}</span></div>'
        for d, c in dirc.most_common() if d)

    cards_html, kol_payload = kol_cards(roster, by_kol, idx_of, tr)
    payload_json = json.dumps(kol_payload, ensure_ascii=False, separators=(",", ":"))
    stmts_json = json.dumps(stmt_rows, ensure_ascii=False, separators=(",", ":"))
    pidx_json = json.dumps(period_idx, ensure_ascii=False, separators=(",", ":"))
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
.kpis{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}}
.kpi{{background:{PANEL};border:1px solid {GRID};border-radius:10px;padding:14px 16px}}
.kv{{font-size:26px;font-weight:600}}
.kl{{font-size:12.5px;margin-top:2px}}
.ks{{font-size:11px;color:{MUTED}}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}}
.ptitle{{font-size:13.5px;margin-bottom:10px;font-weight:600}}
.dline{{display:flex;align-items:center;gap:9px;margin:9px 0;cursor:pointer;
  border-radius:6px;padding:3px 6px;margin-left:-6px;margin-right:-6px}}
.dline:hover{{background:rgba(136,192,208,.10)}}
.dline:focus-visible{{background:rgba(136,192,208,.16);outline:none}}
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
  font-size:10.5px;color:{FG};overflow:hidden;height:58px;cursor:pointer;
  transition:border-color .15s,transform .15s}}
.tl-card:hover{{border-color:{ACCENT};transform:translateY(-1px)}}
.tl-card:focus-visible{{outline:2px solid {ACCENT};outline-offset:1px}}
/* 雷达轴标签可点 */
.rd-ax{{cursor:pointer}}
.rd-ax:hover{{text-decoration:underline}}
.rd-ax:focus-visible{{outline:1px solid {ACCENT}}}
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
/* ── KOL 卡片网格（Chao 2026-09-02：列表 → 卡片）── */
.kcard-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(268px,1fr));
  gap:11px}}
.kcard{{background:{PANEL};border:1px solid {GRID};border-top:3px solid;
  border-radius:9px;padding:12px 14px 10px;cursor:pointer;display:flex;
  flex-direction:column;transition:transform .15s,box-shadow .15s,border-color .15s}}
.kcard:hover{{transform:translateY(-2px);box-shadow:0 5px 16px rgba(0,0,0,.3);
  border-color:{ACCENT}}}
.kcard:focus-visible{{outline:2px solid {ACCENT};outline-offset:2px}}
.kc-top{{display:flex;align-items:center;justify-content:space-between;
  margin-bottom:6px}}
.star{{font-size:11.5px;letter-spacing:1px}}
.kc-score{{font-size:11px;color:{MUTED};font-family:ui-monospace,monospace}}
.kc-name{{font-size:13.5px;font-weight:600;margin-bottom:3px;line-height:1.35}}
.kc-aff{{font-size:11px;color:{MUTED};line-height:1.45;margin-bottom:7px}}
.kc-warn{{font-size:10.5px;color:#e8a0a6;background:#bf616a22;
  border:1px solid #bf616a55;border-radius:5px;padding:3px 8px;margin-bottom:7px}}
.kc-flag{{font-size:10.5px;color:#ebcb8b;background:#ebcb8b1a;
  border:1px solid #ebcb8b44;border-radius:5px;padding:3px 8px;margin-bottom:7px}}
.kc-spec{{font-size:11.5px;color:{FG};line-height:1.5;flex:1;margin-bottom:9px}}
.kc-foot{{display:flex;align-items:center;justify-content:space-between;gap:8px}}
.kc-dir{{font-size:10.5px;padding:2px 9px;border-radius:10px;border:1px solid;
  flex:none}}
.kc-n{{font-size:10.5px;color:{MUTED}}}
.kc-more{{font-size:10.5px;color:{ACCENT};opacity:0;margin-top:7px;
  transition:opacity .15s}}
.kcard:hover .kc-more{{opacity:1}}
.badge{{font-size:11px;padding:2px 8px;border-radius:10px;border:1px solid}}
/* ── 钻取弹层：卡片 → 时间列表 → 单条详情 ── */
.kd-mask{{position:fixed;inset:0;background:rgba(8,10,13,.86);z-index:900;
  display:none;align-items:flex-start;justify-content:center;padding:40px 18px;
  overflow-y:auto}}
.kd-mask.on{{display:flex}}
/* 战区列表弹层固定在视口内，页面不再产生第二条滚动条 */
#tv-mask{{align-items:center;overflow:hidden;padding:32px 18px}}
.kd-panel{{background:{BG};border:1px solid {GRID};border-radius:12px;
  max-width:880px;width:100%;padding:22px 24px 26px;position:relative}}
/* KOL 档案弹层同样锁在视口内：头部固定、正文自己滚（战区弹层同款处理） */
#kd-mask{{align-items:center;overflow:hidden;padding:28px 18px}}
#kd-mask .kd-panel{{display:flex;flex-direction:column;
  max-height:calc(100vh - 56px);padding-bottom:16px}}
#kd-mask .kd-name,#kd-mask .kd-sub{{flex:none}}
#kd-scroll{{flex:1;min-height:0;overflow-y:auto;padding-right:6px;
  scrollbar-width:thin;scrollbar-color:#4a525c transparent}}
#kd-scroll::-webkit-scrollbar{{width:8px}}
#kd-scroll::-webkit-scrollbar-thumb{{background:#4a525c;border-radius:4px}}
.kd-close{{position:absolute;top:8px;right:10px;background:none;border:none;
  color:{MUTED};font-size:22px;cursor:pointer;line-height:1;
  width:38px;height:38px;border-radius:8px}}
.kd-close:hover{{color:{FG};background:rgba(136,192,208,.12)}}
.kd-name{{font-size:19px;font-weight:600;margin-bottom:3px;padding-right:30px}}
.kd-sub{{font-size:12px;color:{MUTED};margin-bottom:13px}}
.kd-bio{{background:{PANEL};border:1px solid {GRID};border-radius:8px;
  padding:12px 14px;font-size:12.5px;margin-bottom:14px}}
.dt{{margin:6px 0;display:grid;grid-template-columns:64px 1fr;gap:10px;
  align-items:baseline}}
.dt b{{color:{MUTED};font-weight:500;font-size:11.5px;margin:0}}
.dt > span{{line-height:1.65}}
/* 四维评分芯片：最关键的量化信息不该是纯文本（视觉复核指出） */
.kd-dim{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:9px 0}}
.kd-dim > div{{background:{CARD2};border:1px solid {GRID};border-radius:7px;
  padding:7px 10px}}
.kd-dim .dl{{font-size:10.5px;color:{MUTED};margin-bottom:4px}}
.kd-dim .dvv{{font-size:15px;font-weight:600;line-height:1}}
.kd-dim .dbarw{{height:4px;background:{GRID};border-radius:2px;margin-top:6px;
  overflow:hidden}}
.kd-dim .dbari{{height:100%;border-radius:2px}}
.kd-wsum{{font-size:11.5px;color:{MUTED};margin:-2px 0 10px}}
.kd-grp{{font-size:11.5px;color:{MUTED};margin:14px 0 7px}}
.kd-row{{border:1px solid {GRID};border-radius:7px;margin-bottom:5px;
  background:{PANEL};overflow:hidden}}
.kd-hd{{display:flex;align-items:center;gap:8px;padding:8px 11px;cursor:pointer;
  font-size:12.5px}}
.kd-hd:hover{{background:rgba(136,192,208,.07)}}
.kd-caret{{color:{MUTED};font-size:10px;width:10px;flex:none}}
.kd-date{{color:{ACCENT};font-size:11px;font-family:ui-monospace,monospace;
  flex:none;width:96px}}
.kd-date.kd-unv{{color:{MUTED}}}
.kd-title{{flex:1;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}}
.kd-body{{display:none;padding:2px 14px 13px 31px;font-size:12.5px;
  border-top:1px solid {GRID}}}
.kd-row.open .kd-body{{display:block}}
.kd-sum{{color:{FG};margin:9px 0;line-height:1.65}}
.kd-meta{{color:{MUTED};font-size:11.5px;margin-bottom:8px}}
.kd-src{{font-size:12px}}
.kd-empty{{color:{MUTED};font-size:12.5px;padding:14px 0}}
/* ── 战区言论列表弹层：地图气泡点开 → 可排序表格 → 双击展开详情 ── */
.tv-panel{{max-width:1080px;display:flex;flex-direction:column;
  max-height:calc(100vh - 48px)}}
/* ★ 弹层自身不滚：头部固定、表格区吃掉剩余高度自己滚。
   否则会出现「弹层内表格滚 + 页面外层滚」双滚动条，且底部被视口裁掉。*/
.tv-panel > .kd-name,.tv-panel > .kd-sub,.tv-panel > .tv-bar,
.tv-panel > .tv-hint{{flex:none}}
.tv-bar{{display:flex;gap:10px;align-items:center;margin-bottom:10px;flex-wrap:wrap}}
.tv-q{{flex:1;min-width:200px;background:{PANEL};border:1px solid {GRID};
  border-radius:7px;color:{FG};font-size:12.5px;padding:7px 12px;outline:none;
  font-family:inherit}}
.tv-q:focus{{border-color:{ACCENT}}}
.tv-tabs{{display:flex;gap:5px}}
.tv-tab{{font-size:11.5px;font-weight:600;color:{MUTED};background:{PANEL};
  border:1px solid {GRID};border-radius:7px;padding:5px 13px;cursor:pointer;
  font-family:inherit}}
.tv-tab:hover{{border-color:{ACCENT};color:{FG}}}
.tv-tab.on{{background:{ACCENT};border-color:{ACCENT};color:#1e2429}}
.tv-hint{{font-size:11.5px;color:{MUTED};margin-bottom:9px}}
.tv-tablewrap{{border:1px solid {GRID};border-radius:9px;
  flex:1;min-height:0;overflow-y:auto;padding-bottom:2px;position:relative;
  scrollbar-width:thin;scrollbar-color:{GRID} transparent;
  /* 底部渐隐：最后一行被容器切断时提示「还有内容」，而不像渲染坏了。
     滚到底后由 JS 加 .tv-atbot 撤掉遮罩，避免「已经到底了还像有东西」。*/
  -webkit-mask-image:linear-gradient(to bottom,#000 calc(100% - 28px),transparent);
  mask-image:linear-gradient(to bottom,#000 calc(100% - 28px),transparent)}}
.tv-tablewrap.tv-atbot{{-webkit-mask-image:none;mask-image:none}}
.tv-tablewrap::-webkit-scrollbar{{width:8px}}
.tv-tablewrap::-webkit-scrollbar-track{{background:transparent}}
.tv-tablewrap::-webkit-scrollbar-thumb{{background:#4a525c;border-radius:4px}}
.tv-tablewrap::-webkit-scrollbar-thumb:hover{{background:#5b6470}}
.tv-table{{width:100%;border-collapse:collapse;font-size:12.5px;table-layout:fixed}}
.tv-table thead th{{position:sticky;top:0;background:{CARD2};text-align:left;
  font-size:11px;font-weight:600;color:{MUTED};padding:9px 11px;
  border-bottom:1px solid {GRID};white-space:nowrap;z-index:2}}
.tv-table th.tv-s{{cursor:pointer;user-select:none}}
.tv-table th.tv-s:hover{{color:{FG}}}
.tv-table th .tv-ar{{margin-left:5px;font-size:9px;color:{ACCENT};opacity:.25}}
.tv-table th.tv-s:hover .tv-ar{{opacity:.6}}
.tv-table th.tv-on .tv-ar{{opacity:1}}
.tv-table th.tv-on{{color:{FG}}}
.tv-table thead th:nth-child(1){{width:100px}}
.tv-table thead th:nth-child(2){{width:268px}}
.tv-table thead th:nth-child(3){{width:96px}}
.tv-table thead th:nth-child(5){{width:82px;text-align:right}}
.tv-table tbody td:nth-child(5){{text-align:right}}
.tv-table thead th:last-child,.tv-table tbody td:last-child{{padding-right:14px}}
.tv-table tbody td{{padding:8px 11px;border-bottom:1px solid #2f353c;
  vertical-align:top;line-height:1.5}}
.tv-r{{cursor:pointer}}
.tv-r:hover td{{background:rgba(136,192,208,.08)}}
.tv-r.open td{{background:rgba(136,192,208,.11)}}
.tv-dt{{font-family:ui-monospace,monospace;font-size:11px;color:#c3cad3}}
.tv-dt.tv-unv{{color:{MUTED}}}
.tv-kol{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.tv-tt{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.tv-r.open .tv-tt{{white-space:normal}}
.tv-dir{{font-size:10.5px;padding:1px 8px;border-radius:9px;border:1px solid;
  white-space:nowrap}}
.tv-src{{font-size:11.5px;white-space:nowrap}}
.tv-det td{{background:{PANEL};padding:13px 16px 16px 16px;font-size:12.5px}}
.tv-ctx{{font-size:11px;color:{ACCENT};margin:-13px -16px 7px;
  padding:7px 16px 6px;border-bottom:1px solid {GRID};
  position:sticky;top:36px;z-index:1;background:{PANEL}}}
.tv-rel{{font-size:11px;color:{MUTED};background:{CARD2};border:1px solid {GRID};
  border-radius:5px;padding:2px 8px;display:inline-block;margin-bottom:8px}}
.tv-det .tv-sum{{line-height:1.7;margin-bottom:11px;max-width:82ch}}
.tv-kv{{display:grid;grid-template-columns:repeat(3,1fr);
  gap:1px;background:{GRID};border:1px solid {GRID};border-radius:7px;
  overflow:hidden;margin-bottom:11px}}
.tv-kv > div{{background:{CARD2};padding:7px 11px;display:flex;gap:10px;
  align-items:baseline;font-size:12px}}
.tv-kv b{{color:{MUTED};font-weight:500;font-size:11px;flex:none;width:60px}}
.tv-kv span{{word-break:break-word}}
.tv-kv .tv-dir{{align-self:center}}
.tv-kv-wide{{grid-column:1/-1}}
@media(max-width:760px){{.tv-kv{{grid-template-columns:1fr}}}}
.tv-act{{display:flex;gap:10px;flex-wrap:wrap}}
.tv-btn{{font-size:11.5px;color:{ACCENT};background:none;border:1px solid {GRID};
  border-radius:6px;padding:4px 12px;cursor:pointer;font-family:inherit}}
.tv-btn:hover{{border-color:{ACCENT}}}
.tv-btn-primary{{background:{ACCENT};border-color:{ACCENT};color:#1e2429;
  font-weight:600;text-decoration:none}}
.tv-btn-primary:hover{{filter:brightness(1.08);text-decoration:none}}
.tv-none{{color:{MUTED};font-size:12.5px;padding:20px 14px;text-align:center}}
/* ── 三级钻取通用样式（言论卡片 / 战区列表 / KOL 弹层共用）── */
.l3-tip{{color:{ACCENT};font-size:11.5px}}
.l3-pend{{font-size:10px;color:{MUTED};background:{CARD2};border:1px solid {GRID};
  border-radius:4px;padding:1px 6px;margin-left:7px;white-space:nowrap}}
.l3-cn{{line-height:1.75;color:{FG};font-size:12.5px}}
.l3-missing{{color:{MUTED};font-size:11.5px;line-height:1.6;
  background:{CARD2};border:1px dashed {GRID};border-radius:6px;padding:8px 11px}}
.l3-btn{{font-size:11.5px;color:{ACCENT};background:none;border:1px solid {GRID};
  border-radius:6px;padding:4px 12px;cursor:pointer;font-family:inherit;
  margin-top:9px}}
.l3-btn:hover{{border-color:{ACCENT};background:rgba(136,192,208,.08)}}
.l3-btn.on{{border-color:{ACCENT}}}
.l3-wrap{{display:none;margin-top:9px}}
.l3-wrap.on{{display:block}}
.l3-en{{background:{CARD2};border:1px solid {GRID};border-radius:7px;
  padding:10px 13px}}
.l3-en-t{{font-size:10.5px;color:{MUTED};letter-spacing:.4px;margin-bottom:4px}}
.l3-en-b{{font-size:12px;line-height:1.65;color:#c3cad3}}
/* ── 升级温度计 ── */
.gg-wrap{{font-size:12.5px}}
.gg-scale{{display:flex;justify-content:space-between;font-size:10.5px;
  color:{MUTED};margin:0 0 10px}}
.gg-row{{display:grid;grid-template-columns:96px 1fr 52px 58px;
  gap:10px;align-items:center;padding:8px 6px;border-bottom:1px solid #2f353c;
  cursor:pointer;border-radius:6px}}
.gg-row:hover{{background:rgba(136,192,208,.09)}}
.gg-row:focus-visible{{background:rgba(136,192,208,.15);outline:none}}
.gg-name{{display:flex;align-items:center;gap:7px;font-size:12.5px}}
.gg-track{{position:relative;height:8px;background:{CARD2};border-radius:4px;
  border:1px solid {GRID}}}
.gg-mid{{position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;
  background:{GRID}}}
.gg-pin{{position:absolute;top:-3px;width:4px;height:12px;border-radius:2px;
  transform:translateX(-2px)}}
.gg-val{{font-family:ui-monospace,monospace;font-size:13px;font-weight:600;
  text-align:right}}
.gg-n{{font-size:11px;color:{MUTED};text-align:right}}
.gg-top{{grid-column:1/-1;font-size:11px;color:{MUTED};padding-left:103px;
  margin-top:-4px}}
.gg-note{{margin-top:11px;font-size:11px;color:{MUTED};line-height:1.6}}
/* ── 立场转向 call-out ── */
.ch-row{{display:flex;align-items:center;gap:11px;flex-wrap:wrap;
  background:{PANEL};border:1px solid {GRID};border-left:3px solid;
  border-radius:8px;padding:9px 13px;margin-bottom:6px;font-size:12.5px}}
.ch-kind{{font-size:10.5px;padding:2px 9px;border-radius:10px;border:1px solid;
  flex:none}}
.ch-kol{{font-weight:600}}
.ch-th{{display:flex;align-items:center;gap:6px;color:{MUTED};font-size:12px}}
.ch-arrow{{font-size:12px}}
.ch-meta{{margin-left:auto;font-size:11px;color:{MUTED}}}
@media(max-width:760px){{.gg-row{{grid-template-columns:82px 1fr 46px}}
  .gg-n{{display:none}} .gg-top{{padding-left:0}}}}
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
.sc-title{{font-size:12.5px;line-height:1.55;margin-bottom:7px;font-weight:500;
  /* 固定两行高度：标题 1 行或 2 行都占同样空间，消除卡片行间高度阶梯 */
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
  overflow:hidden;min-height:calc(12.5px * 1.55 * 2)}}
.sc-dom{{font-size:10.5px;color:{MUTED};font-family:ui-monospace,monospace;
  margin-bottom:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.sc-lv{{font-size:11.5px;line-height:1.6;flex:1;margin-bottom:0}}
.sc-lv:not(:empty){{margin-bottom:9px}}
.sc-src{{font-size:11.5px;align-self:flex-start;display:inline-block;
  margin-top:8px}}
.sc-step{{font-size:11px;color:{ACCENT};background:none;border:1px solid {GRID};
  border-radius:6px;padding:4px 11px;cursor:pointer;font-family:inherit;
  align-self:flex-start;margin-top:auto}}
.sc-step:hover{{border-color:{ACCENT};background:rgba(136,192,208,.08)}}
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

<div class="part-title"><span class="part-num">＋</span>升级温度计
  <span class="desc">各战区加权净升级倾向，按紧张度排序；权重＝时效衰减 × KOL 星级</span></div>
<div class="panel">{gauge_html(theater_gauge(stmts, roster))}</div>

<div class="part-title"><span class="part-num">＋</span>战区雷达
  <span class="desc">全量言论的战区密度分布与走势方向构成</span></div>
<div class="two">
  <div class="panel"><div class="ptitle">战区言论密度</div>{radar_svg(tc)}</div>
  <div class="panel"><div class="ptitle">走势方向分布</div>
    <div style="font-size:12px;color:{MUTED};margin-bottom:12px">
      判断维度为冲突是否升级，非金融多空</div>
    {dir_html or '<p class="empty">暂无数据</p>'}</div>
</div>

<div class="part-title"><span class="part-num">＋</span>立场转向
  <span class="desc">谁改了判断——比谁一直在喊更值得注意；与历史快照逐日比对</span></div>
{changes_html()}

<div class="part-title"><span class="part-num">＋</span>言论卡片
  <span class="desc">按实际发表日切档，可切日/周/月；未核实日期者不入档</span></div>
{multi_period(statements_pane, periods, "stmt", "month")}

<div class="part-title"><span class="part-num">＋</span>事件时间线
  <span class="desc">按 KOL 实际发表日排布，横向滚动</span></div>
{timeline_html(stmts)}

<div class="part-title"><span class="part-num">＋</span>观点全景
  <span class="desc">按战区分组，展开看评级依据；每条言论可再展开详情与原文</span></div>
{cards_html}

<div class="foot">
名册 SSOT = Notion「War KOL List」，本页为单向镜像产物。<br>
评级口径：机构根基 30% · 一手性 25% · 历史命中率 30% · 方法透明度 15%，
群体内百分位定星。入库门槛 3★，南亚战区因结构性原因放宽至 2★（标区域代表）。<br>
标「监测对象」者为指定纳入的低可信度信源，其言论需交叉验证后方可采信。<br>
数据纪律：每条锚 source_url；发表日按实际发表日，查不到留空不用抓取日顶替；
抓不到内容如实标注，绝不编造。
</div>
</div>

<div class="kd-mask" id="kd-mask">
  <div class="kd-panel">
    <button class="kd-close" type="button" aria-label="关闭">×</button>
    <div class="kd-name" id="kd-name"></div>
    <div class="kd-sub" id="kd-sub"></div>
    <div id="kd-scroll">
      <div class="kd-bio" id="kd-bio"></div>
      <div id="kd-body"></div>
    </div>
  </div>
</div>

<div class="kd-mask" id="tv-mask">
  <div class="kd-panel tv-panel">
    <button class="kd-close" type="button" aria-label="关闭">×</button>
    <div class="kd-name" id="tv-name"></div>
    <div class="kd-sub" id="tv-sub"></div>
    <div class="tv-bar">
      <input type="search" id="tv-q" class="tv-q" placeholder="按 KOL、标题、摘要筛选…"
             autocomplete="off">
      <div class="tv-tabs" id="tv-tabs">
        <button type="button" class="tv-tab" data-tvp="day">本日</button>
        <button type="button" class="tv-tab" data-tvp="week">本周</button>
        <button type="button" class="tv-tab" data-tvp="month">本月</button>
        <button type="button" class="tv-tab on" data-tvp="all">全部</button>
      </div>
    </div>
    <div class="tv-hint" id="tv-hint"></div>
    <div class="tv-tablewrap">
      <table class="tv-table">
        <thead><tr>
          <th class="tv-s" data-sort="0">发表日</th>
          <th class="tv-s" data-sort="4">KOL</th>
          <th class="tv-s" data-sort="2">走势</th>
          <th class="tv-s" data-sort="5">标题</th>
          <th>出处</th>
        </tr></thead>
        <tbody id="tv-body"></tbody>
      </table>
    </div>
  </div>
</div>

<script>
/* 左侧索引栏：自动生成 + 主题分组 + scrollspy。
   ★只认带 .part-num 的顶级标题（Eco 踩坑：图内小标题也带 .part-title，
     会掉进「其他」组并让高亮来回窜）。
   ★★菜单必须【严格按 DOM 顺序】铺开（Chao 2026-09-02 指出跳动感）：
     旧实现按 GROUPS 定义顺序装桶，同组成员会被聚到一起，
     和页面真实顺序错位（立场转向/战区雷达被调了个）→ 往下滚高亮往回跳。
     现改为：顺着 DOM 走，遇到组名变化才开新组；同一组名在页面里
     不连续出现时，就如实拆成两段，绝不为了「归类好看」打乱顺序。*/
(function() {{
  var titles = Array.prototype.slice.call(document.querySelectorAll('.part-title'))
                    .filter(function(t) {{ return t.querySelector('.part-num'); }});
  var box = document.getElementById('sidenav-links');
  if (!titles.length || !box) return;
  var GROUPS = [
    {{ name: '总览', match: ['总览'] }},
    {{ name: '地域与走势', match: ['地域走向', '战区雷达', '升级温度计'] }},
    {{ name: '言论与时间', match: ['言论卡片', '事件时间线', '立场转向'] }},
    {{ name: 'KOL 观点', match: ['观点全景'] }}
  ];
  function groupNameOf(label) {{
    for (var g = 0; g < GROUPS.length; g++)
      for (var m = 0; m < GROUPS[g].match.length; m++)
        if (label.indexOf(GROUPS[g].match[m]) >= 0) return GROUPS[g].name;
    return '其他';
  }}
  var links = [], seq = [];
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
    links[i] = a;
    // 顺着 DOM 走：组名与上一段相同就并入，不同就开新段
    var gn = groupNameOf(label);
    if (seq.length && seq[seq.length - 1].name === gn) seq[seq.length - 1].items.push(a);
    else seq.push({{ name: gn, items: [a] }});
  }});
  seq.forEach(function(o) {{
    var wrap = document.createElement('div'); wrap.className = 'sn-group';
    var hdr = document.createElement('div'); hdr.className = 'sn-group-hdr';
    hdr.innerHTML = '<span class="sn-caret">▾</span>' + o.name +
                    '<span class="sn-cnt">' + o.items.length + '</span>';
    var list = document.createElement('div'); list.className = 'sn-group-list';
    o.items.forEach(function(a) {{ list.appendChild(a); }});
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
  /* L3 展开钮（三处弹层共用同一个 class） */
  var l3 = ev.target.closest ? ev.target.closest('.l3-btn') : null;
  if (l3) {{
    var w = l3.nextElementSibling;
    if (w && w.classList.contains('l3-wrap')) {{
      var on = w.classList.toggle('on');
      /* 文案随状态切换：展开态必须写「收起」，否则和 ▴ 箭头自相矛盾 */
      if (!l3.getAttribute('data-label'))
        l3.setAttribute('data-label', l3.textContent.replace(/\\s*[▾▴]\\s*$/, ''));
      var lab = l3.getAttribute('data-label');
      l3.textContent = on ? ('收起' + lab.replace(/^展开/, '') + ' ▴')
                          : (lab + ' ▾');
      l3.classList.toggle('on', on);
    }}
    ev.stopPropagation();
    return;
  }}
  /* 言论卡片三级：L1 标题 →（点钮）L2 中文总结 →（再点）L3 英文原文+出处 */
  var st = ev.target.closest ? ev.target.closest('.sc-step') : null;
  if (st) {{
    var card = st.closest('.scard');
    var r = STMTS[parseInt(card.getAttribute('data-si'), 10)];
    var box = card.querySelector('.sc-lv');
    if (!r || !box) return;
    var lvl = parseInt(card.getAttribute('data-lv') || '1', 10);
    if (lvl === 1) {{
      box.innerHTML = r[10]
        ? '<div class="l3-cn">' + hesc(r[10]) + '</div>'
        : '<div class="l3-missing">该条尚未生成中文总结（如实标注，未用机翻冒充）。'
          + '可继续展开看英文原文。</div>';
      card.setAttribute('data-lv', '2');
      st.textContent = '展开英文原文与出处 ▾';
    }} else if (lvl === 2) {{
      box.innerHTML += '<div class="l3-en"><div class="l3-en-t">英文原标题</div>' +
        '<div class="l3-en-b">' + hesc(r[5]) + '</div>' +
        '<div class="l3-en-t" style="margin-top:7px">英文原文摘要</div>' +
        '<div class="l3-en-b">' +
        (hesc(r[6]) || '（该来源摘要为空，请直接看原文）') + '</div>' +
        '<a class="sc-src" href="' + hesc(r[7]) +
        '" target="_blank" rel="noopener">打开原始出处 →</a></div>';
      card.setAttribute('data-lv', '3');
      st.textContent = '收起 ▴';
    }} else {{
      box.innerHTML = '';
      card.setAttribute('data-lv', '1');
      st.textContent = '展开中文总结 ▾';
    }}
    return;
  }}
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
    return;
  }}
  var kc = ev.target.closest ? ev.target.closest('.kcard') : null;
  if (kc) {{ openKol(kc.getAttribute('data-kol')); return; }}
  if (ev.target.closest && ev.target.closest('#kd-mask .kd-close')) {{ closeKol(); return; }}
  if (ev.target.id === 'kd-mask') closeKol();
}});

/* ── KOL 钻取弹层：卡片 → 带日期时间列表 → 单条详情 ── */
var KOL = {payload_json};
/* 全局言论表（地图弹层与 KOL 弹层共用同一份）：
   0 发表日 1 日期状态 2 方向 3 战区 4 KOL 5 标题 6 摘要 7 出处URL 8 归属依据 */
var STMTS = {stmts_json};
var PIDX = {pidx_json};
var DIRC = {{"升级":"#bf616a","僵持":"#ebcb8b","降级":"#a3be8c","未表态":"#6c757d"}};
function hesc(s) {{
  return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

/* ── 统一的三级钻取行（Chao 2026-09-02 拍板，全站共用一个渲染器）──
   L1 中文标题（未翻译时显示英文原标题并打「待翻译」标）
   L2 中文言论总结
   L3 英文原文摘要 + 归属/日期元信息 + 原始出处链接
   ★ 只用一个函数，KOL 弹层 / 战区列表 / 时间线全走它，
     否则三处各写一遍，改一处漏两处（Eco 踩过）。
   行数据 = STMTS 行：0日期 1日期状态 2方向 3战区 4KOL 5英标题
            6英摘要 7出处 8归属依据 9中标题 10中总结 */
function l3Row(r) {{
  var c = DIRC[r[2]] || '#6c757d';
  var dt = r[0] || '日期未核实';
  var unv = (r[1] === 'verified') ? '' : ' kd-unv';
  var titleCn = r[9] || '';
  var sumCn = r[10] || '';
  var head = titleCn ? hesc(titleCn) : hesc(r[5]);
  var pend = titleCn ? '' :
    '<span class="l3-pend">待翻译</span>';
  var lv2 = sumCn
    ? '<div class="l3-cn">' + hesc(sumCn) + '</div>'
    : '<div class="l3-cn l3-missing">该条尚未生成中文总结（翻译任务未覆盖到，' +
      '如实标注、不用机翻标题冒充）。可直接展开下一级看英文原文。</div>';
  var lv3 = '<div class="l3-en"><div class="l3-en-t">英文原文摘要</div>' +
    '<div class="l3-en-b">' +
    (hesc(r[6]) || '（该来源摘要为空，请直接打开原文）') + '</div>' +
    '<div class="kd-meta">走势判断：<b style="color:' + c + '">' + hesc(r[2]) +
    '</b>　战区：' + hesc(r[3]) + '　KOL：' + hesc(r[4]) +
    '　发表日：' + hesc(dt) +
    '（' + (r[1] === 'verified' ? '已核实' : '未核实') + '）' +
    '　归属校验：' + hesc(r[8] || '—') + '</div>' +
    '<a class="kd-src" href="' + hesc(r[7]) + '" target="_blank" rel="noopener">' +
    '打开原始出处 →</a></div>';
  return '<div class="kd-row"><div class="kd-hd">' +
    '<span class="kd-caret">▸</span>' +
    '<span class="dirb" style="background:' + c + '"></span>' +
    '<span class="kd-date' + unv + '">' + hesc(dt) + '</span>' +
    '<span class="kd-title">' + head + pend + '</span></div>' +
    '<div class="kd-body">' + lv2 +
    '<button type="button" class="l3-btn" data-l3="open">' +
    '展开英文原文与出处 ▾</button>' +
    '<div class="l3-wrap">' + lv3 + '</div></div></div>';
}}
function openKol(name) {{
  var d = KOL[name];
  if (!d) return;
  var mask = document.getElementById('kd-mask');
  document.getElementById('kd-name').textContent = name;
  document.getElementById('kd-sub').textContent =
    d.t + ' · ' + '★'.repeat(d.star) + '☆'.repeat(5 - d.star) +
    '（群体内百分位）· 加权 ' + (d.w || '—') + '/10（绝对分）';
  var bio = '';
  if (d.watch) bio += '<div class="kc-warn">监测对象 · 低可信度，需交叉验证后方可采信</div>';
  else if (d.flag) bio += '<div class="kc-flag">' + hesc(d.flag) + '</div>';
  bio += '<div class="dt"><b>机构</b><span>' + hesc(d.aff) + '</span></div>';
  bio += '<div class="dt"><b>角色</b><span>' + hesc(d.role) + '</span></div>';
  if (d.spec) bio += '<div class="dt"><b>专长</b><span>' + hesc(d.spec) + '</span></div>';
  /* 四维做成带条形的芯片，比一行纯文本可读得多 */
  var DIMS = [['机构根基', d.sa, '#88c0d0'], ['一手性', d.sb, '#a3be8c'],
              ['命中率', d.sc, '#ebcb8b'], ['方法透明度', d.sd, '#b48ead']];
  bio += '<div class="kd-dim">' + DIMS.map(function(x) {{
    var v = (x[1] === null || x[1] === undefined) ? 0 : x[1];
    return '<div><div class="dl">' + x[0] + '</div>' +
      '<div class="dvv" style="color:' + x[2] + '">' + hesc(x[1] == null ? '—' : x[1]) +
      '<span style="font-size:10px;color:#8a929c"> /10</span></div>' +
      '<div class="dbarw"><div class="dbari" style="width:' +
      Math.max(0, Math.min(100, v * 10)) + '%;background:' + x[2] + '"></div></div>' +
      '</div>'; }}).join('') + '</div>';
  bio += '<div class="kd-wsum">加权总分 <b>' + hesc(d.w) +
         '</b>（权重：机构根基 30% · 一手性 25% · 命中率 30% · 透明度 15%）</div>';
  bio += '<div class="dt"><b>评级依据</b><span>' + hesc(d.why) + '</span></div>';
  bio += '<div class="dt"><b>争议</b><span>' + hesc(d.ctr) + '</span></div>';
  /* 档案第二级：中文档案 → 展开原始字段（可核对译写有没有走样）。
     ★ 注意：registry 里部分字段建册时就是中文写的，所以这里叫「原始字段」
       而不是「英文字段」——标错会让人以为翻译坏了（视觉复核时踩过）。
     只有和译文真正不同的字段才列，一模一样就没必要占地方。*/
  var en = [['机构', d.aff_en, d.aff], ['角色', d.role_en, d.role],
            ['专长', d.spec_en, d.spec], ['评级依据', d.why_en, d.why],
            ['争议', d.ctr_en, d.ctr]]
    .filter(function(x) {{ return x[1] && x[1] !== x[2]; }})
    .map(function(x) {{
      return '<div class="dt"><b>' + x[0] + '</b><span>' + hesc(x[1]) +
             '</span></div>'; }})
    .join('');
  if (en) {{
    bio += '<button type="button" class="l3-btn" data-l3="open">' +
           '展开抓取原文字段 ▾</button>' +
           '<div class="l3-wrap"><div class="l3-en">' +
           '<div class="l3-en-t">抓取到的原始字段 · 未经译写</div>' + en +
           '</div></div>';
  }}
  if (!d.cn) {{
    bio += '<div class="l3-missing" style="margin-top:8px">' +
           '本人档案尚未生成中文译写，以上为英文原文。</div>';
  }}
  document.getElementById('kd-bio').innerHTML = bio;
  var h = (d.h || []).map(function(i) {{ return STMTS[i]; }})
                     .filter(function(r) {{ return !!r; }});
  var body = '';
  if (!h.length) {{
    body = '<div class="kd-empty">本轮未抓到可归属于本人的公开言论（如实标注，未编造）。</div>';
  }} else {{
    var dated = [], undated = [];
    for (var i = 0; i < h.length; i++) (h[i][0] ? dated : undated).push(h[i]);
    dated.sort(function(a, b) {{ return a[0] < b[0] ? 1 : -1; }});
    if (dated.length) {{
      body += '<div class="kd-grp">已核实发表日 · ' + dated.length + ' 条（时间倒序）</div>';
      for (var a = 0; a < dated.length; a++) body += l3Row(dated[a]);
    }}
    if (undated.length) {{
      body += '<div class="kd-grp">发表日未核实 · ' + undated.length +
              ' 条（按纪律留空，不用抓取日顶替）</div>';
      for (var b = 0; b < undated.length; b++) body += l3Row(undated[b]);
    }}
  }}
  document.getElementById('kd-body').innerHTML = body;
  mask.classList.add('on');
  document.body.style.overflow = 'hidden';
}}
function closeKol() {{
  document.getElementById('kd-mask').classList.remove('on');
  if (!document.getElementById('tv-mask').classList.contains('on'))
    document.body.style.overflow = '';
}}

/* ── 战区言论列表弹层 ────────────────────────────────────────
   地图气泡 / 战区表格行 → 打开该战区全部言论的可排序列表 → 双击行展开详情。
   ★行数据引用全局 STMTS 下标，不复制对象；排序在下标数组上做，几百行也秒开。
   ★为什么表头点击排序自己写而不用库：整站是单文件零依赖 HTML，
     引外部 JS 会破坏离线可用性。*/
var TV = {{theater:'', dir:'', only:null, period:'all', sort:0, desc:true, q:''}};
function tvOpen(theater, period) {{
  TV.theater = theater; TV.dir = ''; TV.only = null;
  TV.period = (period && PIDX[period]) ? period : 'all';
  TV.sort = 0; TV.desc = true; TV.q = '';
  tvShow(theater + ' · 言论列表');
}}
/* 按走势方向开列表（战区雷达的方向分布条点进来） */
function tvOpenDir(dir) {{
  TV.theater = ''; TV.dir = dir; TV.only = null;
  TV.period = 'all'; TV.sort = 0; TV.desc = true; TV.q = '';
  tvShow('走势判断「' + dir + '」· 言论列表');
}}
/* 单条直达（时间线卡片点进来）：列表里只放这一条，并自动展开详情 */
function tvOpenOne(si) {{
  var r = STMTS[si];
  if (!r) return;
  TV.theater = ''; TV.dir = ''; TV.only = si;
  TV.period = 'all'; TV.sort = 0; TV.desc = true; TV.q = '';
  tvShow((r[0] || '发表日未核实') + ' · ' + r[4]);
  var tr = document.querySelector('#tv-body .tv-r[data-si="' + si + '"]');
  if (tr) tvToggleDetail(tr);
}}
function tvShow(title) {{
  var qi = document.getElementById('tv-q'); if (qi) qi.value = '';
  var tabs = document.querySelectorAll('.tv-tab');
  for (var i = 0; i < tabs.length; i++)
    tabs[i].classList.toggle('on', tabs[i].getAttribute('data-tvp') === TV.period);
  document.getElementById('tv-name').textContent = title;
  tvRender();
  document.getElementById('tv-mask').classList.add('on');
  document.body.style.overflow = 'hidden';
}}
function tvClose() {{
  document.getElementById('tv-mask').classList.remove('on');
  if (!document.getElementById('kd-mask').classList.contains('on'))
    document.body.style.overflow = '';
}}
function tvRows() {{
  var pool, i, out = [];
  // 单条直达模式：只放这一条，不受档位/搜索影响
  if (TV.only !== null && TV.only !== undefined) return [TV.only];
  if (TV.period === 'all') {{
    pool = []; for (i = 0; i < STMTS.length; i++) pool.push(i);
  }} else {{ pool = PIDX[TV.period] || []; }}
  var q = TV.q.toLowerCase();
  for (i = 0; i < pool.length; i++) {{
    var r = STMTS[pool[i]];
    if (!r) continue;
    if (TV.theater && r[3] !== TV.theater) continue;   // 按战区
    if (TV.dir && r[2] !== TV.dir) continue;           // 按走势方向
    /* 中英文都可搜：中文标题/总结 + 英文标题/摘要 + KOL 名 */
    if (q && (r[4] + ' ' + r[5] + ' ' + r[6] + ' ' + (r[9] || '') + ' ' +
              (r[10] || '')).toLowerCase().indexOf(q) < 0) continue;
    out.push(pool[i]);
  }}
  var k = TV.sort, dir = TV.desc ? -1 : 1;
  out.sort(function(a, b) {{
    var x = STMTS[a][k] || '', y = STMTS[b][k] || '';
    /* 日期列：空值（未核实）永远沉底，不参与升降序，否则升序时一屏全是空白 */
    if (k === 0) {{
      if (!x && !y) return 0;
      if (!x) return 1;
      if (!y) return -1;
    }}
    if (x === y) return 0;
    return (x > y ? 1 : -1) * dir;
  }});
  return out;
}}
function tvRender() {{
  var idx = tvRows(), body = document.getElementById('tv-body'), h = '';
  var total = 0, ti;
  for (ti = 0; ti < STMTS.length; ti++) {{
    if (TV.theater && STMTS[ti][3] === TV.theater) total++;
    else if (TV.dir && STMTS[ti][2] === TV.dir) total++;
  }}
  var PL = {{day:'本日', week:'本周', month:'本月', all:'全部时段'}};
  var sub;
  if (TV.only !== null && TV.only !== undefined) {{
    sub = '单条详情（来自事件时间线）';
  }} else {{
    var scope = TV.theater ? '该战区' : (TV.dir ? '该走势' : '');
    sub = PL[TV.period] + ' · ' + idx.length + ' 条' +
          (idx.length === total || !scope ? ''
           : '（' + scope + '累计 ' + total + ' 条）');
  }}
  document.getElementById('tv-sub').textContent = sub;
  document.getElementById('tv-hint').textContent =
    (TV.only !== null && TV.only !== undefined)
      ? '已自动展开该条中文总结，再点「展开英文原文与出处」看原始材料。'
      : '点表头排序，双击任意一行展开详情。日/周/月按实际发表日切档，' +
        '发表日未核实的条目只出现在「全部」档。';
  var ths = document.querySelectorAll('.tv-table th.tv-s');
  for (var t = 0; t < ths.length; t++) {{
    var on = parseInt(ths[t].getAttribute('data-sort'), 10) === TV.sort;
    ths[t].classList.toggle('tv-on', on);
    var ar = ths[t].querySelector('.tv-ar');
    if (!ar) {{ ar = document.createElement('span'); ar.className = 'tv-ar';
                ths[t].appendChild(ar); }}
    /* 未激活列用双向箭头，避免被误读成「已按降序排」 */
    ar.textContent = on ? (TV.desc ? '▼' : '▲') : '⇅';
    ths[t].setAttribute('aria-sort',
      on ? (TV.desc ? 'descending' : 'ascending') : 'none');
  }}
  if (!idx.length) {{
    body.innerHTML = '<tr><td colspan="5" class="tv-none">' +
      '当前筛选条件下没有言论。换个档位或清空搜索词再试。</td></tr>';
    return;
  }}
  for (var i = 0; i < idx.length; i++) {{
    var r = STMTS[idx[i]], c = DIRC[r[2]] || '#6c757d';
    /* 列表只显中文标题；未翻译的回落英文原标题并打「待翻译」标 */
    var ttl = r[9] ? hesc(r[9])
                   : hesc(r[5]) + '<span class="l3-pend">待翻译</span>';
    h += '<tr class="tv-r" data-si="' + idx[i] + '" tabindex="0">' +
      '<td><span class="tv-dt' + (r[1] === 'verified' ? '' : ' tv-unv') + '">' +
      hesc(r[0] || '未核实') + '</span></td>' +
      '<td class="tv-kol" title="' + hesc(r[4]) + '">' + hesc(r[4]) + '</td>' +
      '<td><span class="tv-dir" style="background:' + c + '22;color:' + c +
      ';border-color:' + c + '66">' + hesc(r[2] || '—') + '</span></td>' +
      '<td class="tv-tt" title="' + hesc(r[9] || r[5]) + '">' + ttl + '</td>' +
      '<td><a class="tv-src" href="' + hesc(r[7]) +
      '" target="_blank" rel="noopener">原文 →</a></td></tr>';
  }}
  body.innerHTML = h;
}}
function tvToggleDetail(tr) {{
  var si = parseInt(tr.getAttribute('data-si'), 10), r = STMTS[si];
  if (!r) return;
  var nxt = tr.nextElementSibling;
  if (nxt && nxt.classList.contains('tv-det')) {{
    nxt.parentNode.removeChild(nxt); tr.classList.remove('open'); return;
  }}
  var c = DIRC[r[2]] || '#6c757d';
  var det = document.createElement('tr');
  det.className = 'tv-det';
  /* 摘要开头常见 "5 days ago · " 之类的相对时间前缀，抽出来单独做标签并中文化，
     否则它会和正文粘成一句，且中文界面里夹英文（视觉复核时发现）。*/
  var sum0 = r[6] || '', rel = '';
  var UNIT = {{second:'秒', minute:'分钟', hour:'小时', day:'天',
               week:'周', month:'个月', year:'年'}};
  var m = sum0.match(/^\\s*(?:(\\d+)\\s+(second|minute|hour|day|week|month|year)s?\\s+ago|(yesterday|today))\\s*[·\\-—|]?\\s*/i);
  if (m) {{
    if (m[3]) rel = (m[3].toLowerCase() === 'today') ? '当天' : '前一天';
    else rel = m[1] + UNIT[m[2].toLowerCase()] + '前';
    sum0 = sum0.slice(m[0].length);
  }}
  det.innerHTML = '<td colspan="5">' +
    '<div class="tv-ctx">' + hesc(r[0] || '发表日未核实') + '　·　' +
      hesc(r[4]) + '</div>' +
    (rel ? '<div class="tv-rel">来源页标注：' + hesc(rel) + '</div>' : '') +
    /* L2：中文总结 */
    (r[10]
      ? '<div class="tv-sum l3-cn">' + hesc(r[10]) + '</div>'
      : '<div class="tv-sum l3-missing">该条尚未生成中文总结（如实标注，' +
        '未用机翻冒充）。展开下一级看英文原文。</div>') +
    '<div class="tv-kv">' +
    /* KOL 名常有机构后缀，会换行三行把同排短字段撑出空腔 → 单独通栏一行 */
    '<div class="tv-kv-wide"><b>KOL</b><span>' + hesc(r[4]) + '</span></div>' +
    '<div><b>战区</b><span>' + hesc(r[3]) + '</span></div>' +
    '<div><b>走势判断</b><span class="tv-dir" style="background:' + c +
      '22;color:' + c + ';border-color:' + c + '66">' +
      hesc(r[2] || '—') + '</span></div>' +
    '<div><b>发表日</b><span>' + hesc(r[0] || '未核实') +
      '（' + (r[1] === 'verified' ? '已核实' : '未核实') + '）</span></div>' +
    '<div class="tv-kv-wide"><b>归属校验</b><span>' + hesc(r[8] || '—') +
      '</span></div>' +
    '</div>' +
    /* L3：英文原文（再点一次才出来） */
    '<button type="button" class="l3-btn" data-l3="open">' +
    '展开英文原文与出处 ▾</button>' +
    '<div class="l3-wrap"><div class="l3-en">' +
    '<div class="l3-en-t">英文原标题</div>' +
    '<div class="l3-en-b">' + hesc(r[5]) + '</div>' +
    '<div class="l3-en-t" style="margin-top:8px">英文原文摘要</div>' +
    '<div class="l3-en-b">' + (hesc(sum0) || '（该来源摘要为空，请直接看原文）') +
    '</div></div></div>' +
    '<div class="tv-act">' +
    '<a class="tv-btn tv-btn-primary" href="' + hesc(r[7]) +
    '" target="_blank" rel="noopener">打开原始出处</a>' +
    (KOL[r[4]] ? '<button type="button" class="tv-btn tv-tokol" data-k="' +
       hesc(r[4]) + '">查看该 KOL 档案</button>' : '') +
    '</div></td>';
  tr.parentNode.insertBefore(det, tr.nextSibling);
  tr.classList.add('open');
  /* 展开的详情常高过滚动容器 → 优先保证【底部按钮】可见（父行滚出无妨，
     详情自带 tv-ctx 一行标明是哪条）。容器装得下时才顺带把父行拉回视野。*/
  var wrap = document.querySelector('.tv-tablewrap');
  if (wrap) {{
    var wb = wrap.getBoundingClientRect();
    var over = det.getBoundingClientRect().bottom - wb.bottom;
    if (over > 0) wrap.scrollTop += over + 12;
    var thead = wrap.querySelector('thead');
    var headH = thead ? thead.getBoundingClientRect().height : 0;
    var need = tr.getBoundingClientRect().height + det.getBoundingClientRect().height;
    if (need <= wb.height - headH) {{
      var short = (wb.top + headH) - tr.getBoundingClientRect().top;
      if (short > 0) wrap.scrollTop -= short + 4;
    }}
  }}
}}
document.addEventListener('click', function(ev) {{
  var g = ev.target.closest ? ev.target.closest('.mp-bub') : null;
  if (g) {{ tvOpen(g.getAttribute('data-theater'), g.getAttribute('data-period'));
            return; }}
  var mr = ev.target.closest ? ev.target.closest('.mp-row') : null;
  if (mr) {{ tvOpen(mr.getAttribute('data-theater'), mr.getAttribute('data-period'));
             return; }}
  /* 升级温度计的战区行 */
  var gr = ev.target.closest ? ev.target.closest('.gg-row') : null;
  if (gr && gr.getAttribute('data-theater')) {{
    tvOpen(gr.getAttribute('data-theater'), 'all'); return; }}
  /* 战区雷达的轴标签（SVG <text>，closest 在 SVG 上可用） */
  var rx = ev.target.closest ? ev.target.closest('.rd-ax') : null;
  if (rx && rx.getAttribute('data-theater')) {{
    tvOpen(rx.getAttribute('data-theater'), 'all'); return; }}
  /* 走势方向分布条 */
  var dl = ev.target.closest ? ev.target.closest('.dline') : null;
  if (dl && dl.getAttribute('data-dir')) {{
    tvOpenDir(dl.getAttribute('data-dir')); return; }}
  /* 事件时间线卡片 → 单条直达 */
  var tc2 = ev.target.closest ? ev.target.closest('.tl-card') : null;
  if (tc2 && tc2.getAttribute('data-si')) {{
    tvOpenOne(parseInt(tc2.getAttribute('data-si'), 10)); return; }}
  var th = ev.target.closest ? ev.target.closest('.tv-table th.tv-s') : null;
  if (th) {{
    var k = parseInt(th.getAttribute('data-sort'), 10);
    if (k === TV.sort) TV.desc = !TV.desc; else {{ TV.sort = k; TV.desc = (k === 0); }}
    tvRender(); return;
  }}
  var tab = ev.target.closest ? ev.target.closest('.tv-tab') : null;
  if (tab) {{
    TV.period = tab.getAttribute('data-tvp');
    var tabs = document.querySelectorAll('.tv-tab');
    for (var i = 0; i < tabs.length; i++) tabs[i].classList.toggle('on', tabs[i] === tab);
    tvRender(); return;
  }}
  var tk = ev.target.closest ? ev.target.closest('.tv-tokol') : null;
  if (tk) {{ openKol(tk.getAttribute('data-k')); return; }}
  if (ev.target.id === 'tv-mask') {{ tvClose(); return; }}
  if (ev.target.closest && ev.target.closest('#tv-mask .kd-close')) {{ tvClose(); }}
}});
/* 双击行展开详情（单击留给「原文」链接，避免误触） */
document.addEventListener('dblclick', function(ev) {{
  var tr = ev.target.closest ? ev.target.closest('.tv-r') : null;
  if (!tr || (ev.target.closest && ev.target.closest('a'))) return;
  ev.preventDefault();
  tvToggleDetail(tr);
}});
(function() {{
  var qi = document.getElementById('tv-q');
  if (qi) qi.addEventListener('input', function() {{ TV.q = qi.value || ''; tvRender(); }});
  /* 滚到底就撤掉底部渐隐（否则「已经到底」也像还有内容） */
  var wrap = document.querySelector('.tv-tablewrap');
  if (wrap) wrap.addEventListener('scroll', function() {{
    var atBot = wrap.scrollTop + wrap.clientHeight >= wrap.scrollHeight - 2;
    wrap.classList.toggle('tv-atbot', atBot);
  }}, {{passive:true}});
  /* 键盘可达：气泡/表格行按 Enter 或空格等同点击 */
  document.addEventListener('keydown', function(ev) {{
    if (ev.key !== 'Enter' && ev.key !== ' ') return;
    var el = document.activeElement;
    if (!el || !el.getAttribute) return;
    if (el.classList.contains('mp-bub') || el.classList.contains('mp-row')) {{
      ev.preventDefault();
      tvOpen(el.getAttribute('data-theater'), el.getAttribute('data-period'));
    }} else if (el.classList.contains('gg-row') || el.classList.contains('rd-ax')) {{
      ev.preventDefault(); tvOpen(el.getAttribute('data-theater'), 'all');
    }} else if (el.classList.contains('dline')) {{
      ev.preventDefault(); tvOpenDir(el.getAttribute('data-dir'));
    }} else if (el.classList.contains('tl-card')) {{
      ev.preventDefault(); tvOpenOne(parseInt(el.getAttribute('data-si'), 10));
    }} else if (el.classList.contains('tv-r')) {{
      ev.preventDefault(); tvToggleDetail(el);
    }}
  }});
}})();
document.addEventListener('keydown', function(ev) {{
  if (ev.key === 'Escape') {{
    /* 两层弹层同开时，Esc 先关上层（战区列表），再按一次关 KOL 档案 */
    if (document.getElementById('tv-mask').classList.contains('on')) tvClose();
    else closeKol();
    return;
  }}
  if ((ev.key === 'Enter' || ev.key === ' ') && document.activeElement &&
      document.activeElement.classList &&
      document.activeElement.classList.contains('kcard')) {{
    ev.preventDefault();
    openKol(document.activeElement.getAttribute('data-kol'));
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
