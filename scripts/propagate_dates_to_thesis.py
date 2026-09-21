#!/usr/bin/env python3
"""把 statements 里已核实的 published_on 回填进 thesis 产物。

为什么需要：extract_thesis.py 在进程启动时快照读入 statements。若 enrich_dates.py
在其之后才补出发表日，thesis 里就会残留 published_on=null，导致周报/时间线按发表日
筛选时全部落空（2026-09-05 实测：本周唯一合格言论因此不可见）。

纪律：
- 只做 source_url 精确 join，不做模糊匹配、不推断、不用 collected_on 顶替。
- 只填补 thesis 侧为空的字段；thesis 已有值则不动（statements 侧若与之冲突另行报告）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--thesis", help="默认取 data/thesis/ 最新一份")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = args.thesis
    if not path:
        cands = sorted(glob.glob(os.path.join(ROOT, "data/thesis/thesis_all_*.json")))
        if not cands:
            print("没有 thesis 产物")
            return 1
        path = cands[-1]

    # statements 侧建索引：source_url -> (published_on, date_status, date_source)
    idx: dict[str, tuple] = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "data/statements/*.json"))):
        if p.endswith(".bak"):
            continue
        try:
            rows = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        for r in rows:
            u, d = r.get("source_url"), (r.get("published_on") or "").strip()
            if u and d:
                idx[u] = (d, r.get("date_status"), r.get("date_source"))

    th = json.load(open(path, encoding="utf-8"))
    filled = conflict = 0
    for r in th:
        got = idx.get(r.get("source_url"))
        if not got:
            continue
        d, ds, src = got
        cur = (r.get("published_on") or "").strip()
        if not cur:
            r["published_on"] = d
            r["date_status"] = ds or "verified"
            if src:
                r["date_source"] = src
            filled += 1
        elif cur != d:
            conflict += 1
            print(f"  [冲突] {r.get('kol')} thesis={cur} statements={d} {r.get('source_url')[:70]}")

    print(f"{os.path.basename(path)}：回填 {filled} 条，冲突 {conflict} 条（冲突不覆盖）")
    dated = sum(1 for r in th if (r.get("published_on") or "").strip())
    print(f"发表日覆盖：{dated}/{len(th)}")

    if not args.dry_run and filled:
        json.dump(th, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"已写回 {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
