#!/usr/bin/env python3
"""用当前 attribution.py 的判据重新校验已入库言论，剔除历史漏网条目。

为什么需要：归属校验的判据是逐步补强的（第一道姓名匹配 → 第二道同名者识别
→ 第三道通用平台账号校验）。判据升级后，**历史文件里按旧判据放行的条目不会
自动失效**，dashboard 会继续展示脏数据。

★ 2026-09-03 触发场景：primary_url = https://www.youtube.com/@zhuweiyi 让
  _own_domains 抽出裸域 youtube.com，于是「ZHU - YouTube」（电子音乐人频道）
  被判为本人自有平台；同理 en.wikipedia.org 被当成「自有域名」后绕过了
  DENY_DOMAINS，把「At sign - Wikipedia」这类词条当成本人言论。

纪律：默认 dry-run；--apply 才落地，且**必须留痕**到
data/removed_attribution_<date>.json（累加，不覆盖——purge_homonyms 踩过
同日重跑冲掉首轮记录的坑）。
"""
import argparse
import json
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import attribution as A  # noqa: E402

STORE = os.path.join(ROOT, "data", "statements")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    reg = {k["name_en"]: k for k in
           json.load(open(os.path.join(ROOT, "data", "kol_registry.json"),
                          encoding="utf-8"))}
    removed_all = []
    for fn in sorted(os.listdir(STORE)):
        if not fn.endswith(".json") or fn.endswith(".bak"):
            continue
        path = os.path.join(STORE, fn)
        recs = json.load(open(path, encoding="utf-8"))
        keep, drop = [], []
        for r in recs:
            k = reg.get(r.get("kol"))
            if not k or r.get("attribution") != "verified":
                keep.append(r)
                continue
            hit = {"title": r.get("title", ""),
                   "description": r.get("summary", ""),
                   "url": r.get("source_url", "")}
            good, reason = A.check(k, hit)
            if good:
                ish, hy = A.homonym_check(k, hit)
                if ish:
                    good, reason = False, hy
            if good:
                keep.append(r)
            else:
                r = dict(r)
                r["removed_reason"] = reason
                r["removed_from"] = fn
                drop.append(r)
        if drop:
            print(f"{fn}: 剔除 {len(drop)} / {len(recs)}")
            for d in drop:
                print(f"   {d['kol']} | {d.get('title','')[:60]} | "
                      f"{d.get('source_url','')} | {d['removed_reason']}")
            removed_all.extend(drop)
            if args.apply:
                json.dump(keep, open(path, "w", encoding="utf-8"),
                          ensure_ascii=False, indent=1)

    print(f"\n合计剔除 {len(removed_all)} 条（{'已落地' if args.apply else 'dry-run'}）")
    if args.apply and removed_all:
        log = os.path.join(ROOT, "data",
                           f"removed_attribution_{date.today()}.json")
        prev = []
        if os.path.exists(log):
            prev = json.load(open(log, encoding="utf-8"))
        json.dump(prev + removed_all, open(log, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"留痕 → {log}（累计 {len(prev) + len(removed_all)} 条）")


if __name__ == "__main__":
    main()
