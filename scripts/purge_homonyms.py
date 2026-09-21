#!/usr/bin/env python3
"""清除已入库的同名者误抓条目（Chao 2026-09-02 批准方案 A）。

背景：归属校验旧逻辑只问「正文里有没有这个名字」，同名的另一个人当然也有名字
      → 直接穿透。实测污染：印度军事分析师 Sushant Singh 混入同名宝莱坞演员
      Sushant Singh Rajput 的娱乐报道；国防分析师 Todd Harrison 混入同名食药
      律师 Todd Harrison J.D. 的 FDA 法规文章。

本脚本用 attribution.homonym_check（新加的通用闸门，非硬编码个案）重扫已入库
数据，把命中的条目**移出主表、落盘留痕**，不是物理删除——
留痕文件 data/removed_homonym_<date>.json 可随时复核与恢复。

★ 默认 dry-run，只打印不改动。确认无误后加 --apply 才真正执行。
"""
import argparse
import json
import os
import shutil
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SDIR = os.path.join(DATA, "statements")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from attribution import homonym_check  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写入（默认只预览）")
    a = ap.parse_args()

    roster = {(k.get("name_en") or k.get("name_zh")): k
              for k in json.load(open(os.path.join(DATA, "kol_registry.json"),
                                      encoding="utf-8"))}
    removed, total, touched = [], 0, {}
    for fn in sorted(os.listdir(SDIR)):
        if not fn.endswith(".json"):
            continue
        p = os.path.join(SDIR, fn)
        try:
            recs = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        keep = []
        for r in recs:
            total += 1
            is_h, why = homonym_check(roster.get(r.get("kol")), r)
            if is_h and r.get("status") == "ok":
                r["_removed_reason"] = why
                r["_removed_from"] = fn
                removed.append(r)
            else:
                keep.append(r)
        if len(keep) != len(recs):
            touched[p] = keep

    print(f"扫描 {total} 条，命中同名者 {len(removed)} 条，涉及 {len(touched)} 个文件")
    by_kol = {}
    for r in removed:
        by_kol.setdefault(r.get("kol"), []).append(r)
    for k, v in sorted(by_kol.items(), key=lambda x: -len(x[1])):
        print(f"  {k[:30]:<32} {len(v)} 条")
        for r in v[:3]:
            print(f"      · {(r.get('title') or '')[:66]}")

    if not a.apply:
        print("\n[dry-run] 未改动任何文件。确认无误后加 --apply 执行。")
        return 0
    if not removed:
        print("无需清理。")
        return 0

    # 落盘留痕（不是物理删除，可复核可恢复）
    # ★ 同日多次运行不能互相覆盖——首轮清 23 条、次轮清 2 条时，
    #   固定文件名让第二次把第一次的记录冲掉了（实测踩过）。改为累加。
    op = os.path.join(DATA, f"removed_homonym_{date.today()}.json")
    prev = []
    if os.path.exists(op):
        try:
            prev = json.load(open(op, encoding="utf-8"))
        except Exception:
            prev = []
    seen = {(r.get("kol"), r.get("source_url")) for r in prev}
    merged = prev + [r for r in removed
                     if (r.get("kol"), r.get("source_url")) not in seen]
    json.dump(merged, open(op, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n留痕 → {op}（本轮 {len(removed)} 条，累计 {len(merged)} 条）")

    for p, keep in touched.items():
        shutil.copy2(p, p + ".bak")          # 改前必备份
        json.dump(keep, open(p, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"  已清理 {os.path.basename(p)}（备份 .bak）")

    # 翻译缓存里的对应条目一并清掉，避免留下孤儿译文
    tp = os.path.join(DATA, "translations.json")
    if os.path.exists(tp):
        tr = json.load(open(tp, encoding="utf-8"))
        urls = {r.get("source_url") for r in removed}
        n = len([u for u in urls if u in tr.get("stmt", {})])
        for u in urls:
            tr.get("stmt", {}).pop(u, None)
        shutil.copy2(tp, tp + ".bak")
        json.dump(tr, open(tp, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"  翻译缓存清理 {n} 条孤儿译文")
    print("完成。请重跑 build_dashboard.py 使前端生效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
