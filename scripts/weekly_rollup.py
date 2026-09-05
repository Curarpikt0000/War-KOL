#!/usr/bin/env python3
"""War KOL 周报聚合器。

只读地扫描 data/thesis/ (五要素抽取产物，已过闸的合格言论) 与 data/statements/，
按 published_on 落在 [week_start, week_end] 的记录做战区聚合 + 立场变化检测。

铁律：
- 只认 published_on（实际发表日）。date_status != verified / 为空的一律不算入本周，
  另行统计为 undated，绝不用 collected_on 顶替。
- 立场变化 = 同一 KOL 同一战区，本周主导方向 vs 上周主导方向 不同。
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEATERS = ["俄乌", "中东", "印太", "南亚", "非洲", "拉美", "军工与战略"]
DIRECTIONS = ["升级", "僵持", "降级", "未表态"]


def load_thesis() -> list[dict]:
    """载入最新一份 thesis_all_*.json（五要素合格言论全集）。"""
    files = sorted(glob.glob(os.path.join(ROOT, "data/thesis/thesis_all_*.json")))
    if not files:
        return []
    latest = files[-1]
    with open(latest, encoding="utf-8") as fh:
        rows = json.load(fh)
    for r in rows:
        r["_src_file"] = os.path.basename(latest)
    return rows


def load_statements() -> list[dict]:
    """载入全部 statements（未过五要素闸的原始条目），用于覆盖率对照。"""
    out: list[dict] = []
    seen: set[tuple] = set()
    for path in sorted(glob.glob(os.path.join(ROOT, "data/statements/*.json"))):
        if path.endswith(".bak"):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                rows = json.load(fh)
        except Exception:
            continue
        if isinstance(rows, dict):
            rows = rows.get("items") or rows.get("statements") or []
        for r in rows:
            key = (r.get("kol"), r.get("source_url"))
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
    return out


def in_window(row: dict, start: dt.date, end: dt.date) -> bool:
    p = (row.get("published_on") or "").strip()
    if not p:
        return False
    try:
        d = dt.date.fromisoformat(p[:10])
    except ValueError:
        return False
    return start <= d <= end


def dominant(dirs: list[str]) -> str:
    """主导方向：忽略『未表态』后取众数；全为未表态则返回未表态；无数据返回 '-'。"""
    real = [d for d in dirs if d and d != "未表态"]
    if not real:
        return "未表态" if dirs else "-"
    cnt = collections.Counter(real)
    top = cnt.most_common()
    # 平票时按 升级 > 降级 > 僵持 的显著性优先（升级/降级是有信息的信号）
    best = top[0][1]
    tied = [d for d, n in top if n == best]
    for pref in ("升级", "降级", "僵持"):
        if pref in tied:
            return pref
    return tied[0]


def theater_rollup(rows: list[dict]) -> dict:
    out = {}
    for th in THEATERS:
        sub = [r for r in rows if r.get("theater") == th]
        dirs = [r.get("direction") for r in sub]
        out[th] = {
            "n_statements": len(sub),
            "n_kol": len(set(r.get("kol") for r in sub)),
            "dominant": dominant(dirs),
            "dir_counts": dict(collections.Counter(d for d in dirs if d)),
            "rows": sub,
        }
    return out


def kol_theater_dir(rows: list[dict]) -> dict:
    """{(kol, theater): dominant_direction}"""
    buckets = collections.defaultdict(list)
    for r in rows:
        k, t = r.get("kol"), r.get("theater")
        if not k or not t:
            continue
        buckets[(k, t)].append(r.get("direction"))
    return {key: dominant(v) for key, v in buckets.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", default=dt.date.today().isoformat(),
                    help="本周结束日 (含)，默认今天")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", default=os.path.join(ROOT, "data/weekly"))
    args = ap.parse_args()

    end = dt.date.fromisoformat(args.end)
    start = end - dt.timedelta(days=args.days - 1)
    prev_end = start - dt.timedelta(days=1)
    prev_start = prev_end - dt.timedelta(days=args.days - 1)

    thesis = load_thesis()
    stmts = load_statements()

    cur = [r for r in thesis if in_window(r, start, end)]
    prev = [r for r in thesis if in_window(r, prev_start, prev_end)]

    # statements 层（未过五要素闸）本周命中，用于说明「抓到了但没够格」
    cur_stmt = [r for r in stmts if in_window(r, start, end)]

    undated = [r for r in thesis if not (r.get("published_on") or "").strip()]

    cur_map = kol_theater_dir(cur)
    prev_map = kol_theater_dir(prev)
    changes = []
    for key in set(cur_map) & set(prev_map):
        if cur_map[key] != prev_map[key]:
            kol, th = key
            changes.append({
                "kol": kol, "theater": th,
                "from": prev_map[key], "to": cur_map[key],
                "cur_rows": [r for r in cur if r.get("kol") == kol and r.get("theater") == th],
                "prev_rows": [r for r in prev if r.get("kol") == kol and r.get("theater") == th],
            })

    # ── 30 天窗口的立场变化 ────────────────────────────────────────────
    # 为什么需要：本项目日均合格言论个位数，7天窗口里同一 KOL 极少两次发声，
    # 严格的「本周 vs 上周」几乎恒为空。30d vs 前30d 才是实际有信号的尺度。
    # 两个口径都输出，周报里注明各自窗口，不混为一谈。
    m30_end, m30_start = end, end - dt.timedelta(days=29)
    p30_end, p30_start = m30_start - dt.timedelta(days=1), m30_start - dt.timedelta(days=30)
    cur30 = [r for r in thesis if in_window(r, m30_start, m30_end)]
    prev30 = [r for r in thesis if in_window(r, p30_start, p30_end)]
    c30, p30 = kol_theater_dir(cur30), kol_theater_dir(prev30)
    changes30 = []
    for key in set(c30) & set(p30):
        if c30[key] != p30[key]:
            kol, th = key
            changes30.append({
                "kol": kol, "theater": th, "from": p30[key], "to": c30[key],
                "cur_rows": [r for r in cur30 if r.get("kol") == kol and r.get("theater") == th],
                "prev_rows": [r for r in prev30 if r.get("kol") == kol and r.get("theater") == th],
            })

    # 年内方向轨迹（>=3 次有日期观测且出现过方向翻转）——给周报做背景纵深
    traj = collections.defaultdict(list)
    for r in thesis:
        p = (r.get("published_on") or "")[:10]
        if p >= f"{end.year}-01-01":
            traj[(r.get("kol"), r.get("theater"))].append(
                {"date": p, "dir": r.get("direction"),
                 "topic": r.get("topic"), "url": r.get("source_url")})
    trajectories = []
    for (kol, th), v in traj.items():
        v.sort(key=lambda x: x["date"])
        real = {x["dir"] for x in v if x["dir"] and x["dir"] != "未表态"}
        if len(v) >= 3 and len(real) > 1:
            trajectories.append({"kol": kol, "theater": th, "points": v})

    result = {
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "prev_start": prev_start.isoformat(),
        "prev_end": prev_end.isoformat(),
        "generated_on": dt.date.today().isoformat(),
        "n_thesis_total": len(thesis),
        "n_statements_total": len(stmts),
        "n_thesis_in_week": len(cur),
        "n_thesis_prev_week": len(prev),
        "n_statements_in_week": len(cur_stmt),
        "n_thesis_undated": len(undated),
        "theaters": {k: {kk: vv for kk, vv in v.items() if kk != "rows"}
                     for k, v in theater_rollup(cur).items()},
        "stance_changes": [{kk: vv for kk, vv in c.items() if not kk.endswith("_rows")}
                           for c in changes],
        "window30": {"cur": [m30_start.isoformat(), m30_end.isoformat()],
                     "prev": [p30_start.isoformat(), p30_end.isoformat()],
                     "n_cur": len(cur30), "n_prev": len(prev30)},
        "stance_changes_30d": [{kk: vv for kk, vv in c.items() if not kk.endswith("_rows")}
                               for c in changes30],
        "trajectories": trajectories,
        "n_kol_active_week": len(set(r.get("kol") for r in cur)),
    }

    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"week_{start.isoformat()}_{end.isoformat()}.json")
    full = dict(result)
    full["rows_in_week"] = cur
    full["rows_30d"] = cur30
    full["stance_changes_detail"] = changes
    full["stance_changes_30d_detail"] = changes30
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(full, fh, ensure_ascii=False, indent=1)

    print(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"\n[saved] {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
