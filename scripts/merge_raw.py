#!/usr/bin/env python3
"""War-KOL: 合并 data/raw/*.json → data/candidates_raw.json，跨战区去重。

去重规则（同一人被多个战区小组各收一次是正常现象，不是错误）：
- 主键 = name_en 规范化（小写、去标点、压空格）
- 合并时 theater 变成【列表】，保留全部战区（一个人可以同时覆盖俄乌和军工）
- 四维分数取各组【最高分】——理由：不同小组只看自己领域，
  低分往往是「在我这个领域他不算核心」，而非「他不行」。取最高分反映其真实上限。
- rating_reason / controversies / sources 全部合并去重保留（信息只增不减）
"""
import glob
import json
import os
import re
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "data", "candidates_raw.json")

SCORES = ["score_A", "score_B", "score_C", "score_D"]


def norm(name):
    s = (name or "").strip().lower()
    s = re.sub(r"[.\-_'’,]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def as_list(v):
    if v is None or v == "":
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def merge(a, b):
    """b 并入 a。"""
    # theater 累积
    ts = as_list(a.get("theater")) + as_list(b.get("theater"))
    a["theater"] = sorted({t for t in ts if t})
    # 分数取最高
    for k in SCORES:
        va, vb = a.get(k), b.get(k)
        if vb is not None and (va is None or float(vb) > float(va)):
            a[k] = vb
    # 文本字段：拼接去重
    for k in ("rating_reason", "controversies", "specialty", "affiliation", "role"):
        va = (a.get(k) or "").strip()
        vb = (b.get(k) or "").strip()
        if vb and vb.lower() not in ("none", "unknown") and vb != va:
            if not va or va.lower() in ("none", "unknown"):
                a[k] = vb
            elif vb not in va:
                a[k] = f"{va} ｜ {vb}"
    # sources 合并去重
    srcs = as_list(a.get("sources")) + as_list(b.get("sources"))
    seen, out = set(), []
    for s in srcs:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    a["sources"] = out
    # 平台类：空的用对方补
    for k in ("platforms", "x_handle", "youtube", "language", "name_zh"):
        if (not a.get(k) or str(a.get(k)).lower() == "unknown") and b.get(k):
            a[k] = b[k]
    a["_merged_from"] = a.get("_merged_from", 1) + 1
    return a


def main():
    files = sorted(glob.glob(os.path.join(RAW_DIR, "*.json")))
    if not files:
        raise SystemExit(f"{RAW_DIR} 下没有 json")

    merged = {}
    order = []
    total = 0
    for f in files:
        recs = json.load(open(f, encoding="utf-8"))
        total += len(recs)
        for r in recs:
            r.setdefault("_source_file", os.path.basename(f))
            key = norm(r.get("name_en") or r.get("name_zh"))
            if not key:
                print(f"  [跳过] 无名记录 @ {os.path.basename(f)}")
                continue
            if key in merged:
                merge(merged[key], r)
            else:
                r["theater"] = as_list(r.get("theater"))
                r["sources"] = as_list(r.get("sources"))
                r["_merged_from"] = 1
                merged[key] = r
                order.append(key)

    out = [merged[k] for k in order]
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"输入 {len(files)} 个文件 / {total} 条")
    print(f"去重后 {len(out)} 人（合并掉 {total - len(out)} 条重复）")
    multi = [r for r in out if r["_merged_from"] > 1]
    print(f"\n跨战区人物 {len(multi)} 人：")
    for r in sorted(multi, key=lambda x: -x["_merged_from"]):
        print(f"  {r['name_en']:28} {r['_merged_from']}组  {'/'.join(r['theater'])}")
    print("\ntheater 覆盖（去重后，一人可多战区）：")
    c = Counter(t for r in out for t in r["theater"])
    for t, n in c.most_common():
        print(f"  {t}: {n}")
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
