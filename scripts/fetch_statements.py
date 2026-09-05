#!/usr/bin/env python3
"""War-KOL 言论抓取器：读名册 active 全量 → 抓最新言论 → 落盘 JSON。

★ cron 绝不写死 KOL 数量（Eco 踩坑：硬编码「88个KOL」4 处，新增会漏抓）——
  本脚本一律读 data/kol_registry.json 取 active 全部。

数据纪律（AGENTS.md）：
- 绝不编造。抓不到就标 status，不臆造言论/日期/出处。
- 每条锚 source_url。
- 发表日按 KOL 实际发表日；查不到留空标 date_status=unverified，
  【绝不用 collected_on 顶替】（Forecast-Checker 教训）。

用法：
  python3 scripts/fetch_statements.py --mode daily          # 每日增量（近 3 天）
  python3 scripts/fetch_statements.py --mode backfill --days 365 --limit 5
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from attribution import filter_hits  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
REGISTRY = os.path.join(DATA, "kol_registry.json")
STORE_DIR = os.path.join(DATA, "statements")
os.makedirs(STORE_DIR, exist_ok=True)

THEATER_HINT = {
    "俄乌": "Ukraine Russia war",
    "中东": "Iran Israel Middle East conflict",
    "印太": "Taiwan South China Sea PLA",
    "南亚": "India Pakistan conflict",
    "非洲": "Sudan Sahel conflict",
    "拉美": "Venezuela Latin America security",
    "军工与战略": "defense industry munitions production",
}

# 战争走势方向（不是金融多空——语义是「冲突会不会升级」）
DIR_UP = ["escalat", "offensive", "surge", "buildup", "build-up", "mobiliz",
          "strike", "invasion", "attack", "expand", "intensif", "threat",
          "prepare for war", "imminent", "provocation", "incursion", "raid",
          "reinforce", "deploy", "missile launch", "airstrike", "bombard",
          "升级", "扩大", "进攻", "威胁", "增兵", "空袭", "开战"]
DIR_DOWN = ["ceasefire", "truce", "de-escalat", "deescalat", "withdraw",
            "peace deal", "peace plan", "negotiat", "settlement", "diplomacy",
            "talks", "agreement", "pull back", "disengage", "armistice",
            "停火", "撤军", "和谈", "降级", "谈判", "协议"]
DIR_HOLD = ["stalemate", "attrition", "frozen", "grinding", "deadlock",
            "static", "entrenched", "war of attrition", "no breakthrough",
            "protracted", "prolonged", "僵持", "消耗", "胶着", "拉锯"]


def classify_direction(text):
    """粗分类，仅作初筛；真正判定由 cron 里的 agent 复核。"""
    t = (text or "").lower()
    su = sum(t.count(k) for k in DIR_UP)
    sd = sum(t.count(k) for k in DIR_DOWN)
    sh = sum(t.count(k) for k in DIR_HOLD)
    if max(su, sd, sh) == 0:
        return "未表态"
    return {su: "升级", sd: "降级", sh: "僵持"}[max(su, sd, sh)]


_DATE_PATS = [
    (re.compile(r"\b(20[12]\d)-(\d{1,2})-(\d{1,2})\b"), lambda m: (int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(20[12]\d)", re.I),
     lambda m: (int(m[3]), _MON[m[2][:3].title()], int(m[1]))),
    (re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d{1,2}),?\s+(20[12]\d)", re.I),
     lambda m: (int(m[3]), _MON[m[1][:3].title()], int(m[2]))),
]
_MON = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def extract_date(text):
    """从正文抽发表日。抽不到返回 (None, 'unverified')——绝不用抓取日顶替。"""
    for pat, conv in _DATE_PATS:
        m = pat.search(text or "")
        if m:
            try:
                y, mo, d = conv(m)
                dt = date(y, mo, d)
                if date(2015, 1, 1) <= dt <= date.today() + timedelta(days=1):
                    return dt.isoformat(), "verified"
            except (ValueError, KeyError):
                continue
    return None, "unverified"


def search(query, limit=6):
    """检索。优先 ddgs（免 key，cron 脚本模式下可用）；
    Hermes 内核环境下退回 web_search。失败返回空列表并如实标注，绝不编造。"""
    try:
        from ddgs import DDGS
        with DDGS() as d:
            return [
                {"title": r.get("title", ""),
                 "url": (r.get("href") or r.get("url") or "").strip(),
                 "description": r.get("body", "")}
                for r in d.text(query, max_results=limit)
            ]
    except Exception as e1:
        try:
            from hermes_tools import web_search   # type: ignore
            r = web_search(query, limit=limit)
            return r.get("data", {}).get("web", []) or []
        except Exception as e2:
            print(f"    [search 失败] ddgs={e1} hermes={e2}", file=sys.stderr)
            return []


def build_queries(kol, mode, days):
    """构造检索式。

    ★ Chao 2026-09-03：「目前言论太少了」。诊断发现瓶颈不在门槛而在上游——
      旧版每人只发 2-3 个 query，候选池人均仅 13.4 条。
      三人对照实测：加下面这组 query 后唯一 URL 从 18 → 40-72（2.2-4 倍）。

    分五族，各自捞不同形态的观点：
      1 基础族   —— 原有的主题检索
      2 访谈族   —— interview / testimony / briefing，观点密度最高
      3 音频族   —— podcast transcript，长篇论述常在这里
      4 句式族   —— "I think" / "I expect"，直接命中第一人称判断
      5 站点族   —— 定向战略评论重镇，绕开搜索引擎的主题漂移
    """
    name = kol.get("name_en") or kol.get("name_zh")
    theaters = kol.get("theater") or []
    hint = " OR ".join(str(THEATER_HINT.get(t, t)) for t in theaters[:2]) or "war analysis"
    yr = date.today().year

    qs = [f'"{name}" {hint} analysis']
    if mode == "backfill":
        qs += [f'"{name}" {hint} {yr}', f'"{name}" {hint} {yr-1}']
    else:
        qs += [f'"{name}" latest assessment']

    qs += [
        f'"{name}" interview {yr}',
        f'"{name}" testimony OR briefing {yr}',
        f'"{name}" podcast transcript {hint}',
        f'"{name}" "I think" OR "I expect" {hint}',
        f'"{name}" commentary {yr-1} {hint}',
        f'site:warontherocks.com "{name}"',
        f'site:foreignaffairs.com OR site:foreignpolicy.com "{name}"',
    ]
    if kol.get("x_handle") and kol["x_handle"].lower() != "unknown":
        qs.append(f'{kol["x_handle"]} {hint}')
    return qs


def fetch_one(kol, mode, days, per_query=8):
    name = kol.get("name_en") or kol.get("name_zh")
    cutoff = date.today() - timedelta(days=days)
    raw, seen = [], set()
    for q in build_queries(kol, mode, days):
        for hit in search(q, per_query):
            url = hit.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            raw.append(hit)
        # ★ query 数从 3 涨到 11（2026-09-03 扩量），节流必须跟上，
        #   否则 ddgs 连续打会 429 —— 实测 1.2s 间隔稳定。
        time.sleep(1.2)

    # ★ 归属校验：检索引擎对中文名/音译名会退化成主题搜索，
    #   抓回与本人无关的智库文章甚至同名者主页（2026-09-02 实测）。
    #   不校验就入库 = 往库里灌垃圾，比没有数据更有害。
    attributed, rejected = filter_hits(kol, raw)

    out = []
    for hit in attributed:
            blob = f"{hit.get('title','')} {hit.get('description','')}"
            pub, dstatus = extract_date(blob)
            if pub and date.fromisoformat(pub) < cutoff:
                continue
            # ★ 必须取【当前 hit】的 url。曾误用循环外残留的 url 变量，
            #   导致一个人所有条目 source_url 全指向同一个错误链接
            #   （2026-09-02 抽查发现：标题写 Key.Aero，URL 却是 ynetnews）。
            out.append({
                "kol": name,
                "theater": (kol.get("theater") or ["未分类"])[0],
                "title": hit.get("title", "")[:300],
                "summary": (hit.get("description") or "")[:600],
                "quote": "",
                "source_url": hit.get("url", ""),
                "published_on": pub,
                "date_status": dstatus,
                "direction": classify_direction(blob),
                "collected_on": date.today().isoformat(),
                "status": "ok",
                "attribution": hit.get("attribution", "verified"),
                "attribution_reason": hit.get("attribution_reason", ""),
            })

    if rejected:
        rej_path = os.path.join(STORE_DIR, "rejected_attribution.jsonl")
        with open(rej_path, "a", encoding="utf-8") as f:
            for h in rejected:
                f.write(json.dumps({"kol": name, **h}, ensure_ascii=False) + "\n")

    if not out:
        return [{
            "kol": name,
            "theater": (kol.get("theater") or ["未分类"])[0],
            "title": "", "summary": "", "quote": "", "source_url": "",
            "published_on": None, "date_status": "unverified",
            "direction": "未表态",
            "collected_on": date.today().isoformat(),
            "status": "not_found",   # 绝不编造，如实标
        }]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["daily", "backfill"], default="daily")
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 人（调试）")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    days = args.days or (365 if args.mode == "backfill" else 3)
    roster = json.load(open(REGISTRY, encoding="utf-8"))
    roster = [k for k in roster if k.get("active", True)]   # ★读 active 全量，不写死人数
    if args.start:
        roster = roster[args.start:]
    if args.limit:
        roster = roster[:args.limit]

    print(f"名册 active {len(roster)} 人 | mode={args.mode} 窗口 {days} 天")
    out_path = args.out or os.path.join(
        STORE_DIR, f"{args.mode}_{date.today().isoformat()}.json")

    # 增量落盘：每人写一次，超时也不丢已完成部分
    allrecs = []
    if os.path.exists(out_path):
        try:
            allrecs = json.load(open(out_path, encoding="utf-8"))
        except Exception:
            allrecs = []
    done = {r["kol"] for r in allrecs}

    for i, kol in enumerate(roster, 1):
        name = kol.get("name_en") or kol.get("name_zh")
        if name in done:
            print(f"[{i}/{len(roster)}] {name} — 已有，跳过")
            continue
        recs = fetch_one(kol, args.mode, days)
        allrecs.extend(recs)
        ok = sum(1 for r in recs if r["status"] == "ok")
        print(f"[{i}/{len(roster)}] {name}: {ok} 条")
        json.dump(allrecs, open(out_path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)

    ok = sum(1 for r in allrecs if r["status"] == "ok")
    nf = sum(1 for r in allrecs if r["status"] == "not_found")
    ver = sum(1 for r in allrecs if r["date_status"] == "verified")
    print(f"\n合计 {len(allrecs)} 条：有效 {ok} / 未找到 {nf}")
    print(f"发表日已核实 {ver} / 未核实 {ok - ver}（未核实者留空，不用抓取日顶替）")
    print(f"→ {out_path}")


if __name__ == "__main__":
    main()
