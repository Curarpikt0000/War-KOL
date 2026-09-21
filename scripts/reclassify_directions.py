#!/usr/bin/env python3
"""对已抓取的言论重算方向分类（词表升级后回填历史数据）。

方向 = 升级 / 僵持 / 降级 / 未表态。
语义是「冲突会不会升级」，不是金融多空。
"""
import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(ROOT, "data", "statements")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_statements import classify_direction  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None)
    args = ap.parse_args()
    files = ([args.file if os.path.isabs(args.file) else os.path.join(STORE, args.file)]
             if args.file else sorted(glob.glob(os.path.join(STORE, "*.json"))))
    from collections import Counter
    for path in files:
        recs = json.load(open(path, encoding="utf-8"))
        before = Counter(r.get("direction") for r in recs)
        n = 0
        for r in recs:
            if r.get("status") != "ok":
                continue
            blob = f"{r.get('title','')} {r.get('summary','')}"
            new = classify_direction(blob)
            if new != r.get("direction"):
                r["direction"] = new
                n += 1
        json.dump(recs, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        after = Counter(r.get("direction") for r in recs)
        print(f"{os.path.basename(path)}: 改判 {n} 条")
        print(f"  前: {dict(before)}")
        print(f"  后: {dict(after)}")


if __name__ == "__main__":
    main()
