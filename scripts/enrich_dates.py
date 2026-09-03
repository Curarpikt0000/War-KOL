#!/usr/bin/env python3
"""补发表日：从 URL 路径 + 页面正文里抽日期，提高 date_status=verified 覆盖率。

为什么需要：ddgs 摘要常不含日期，仅靠摘要抽取核实率只有 ~14%，
时间线会几乎是空的。但很多来源的日期就明明白白写在 URL 路径里
（/2026/09/... 是新闻站通用惯例），或页面 <time> 标签里。

纪律不变：抽不到就【留空】，标 unverified，绝不用 collected_on 顶替。
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import date
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(ROOT, "data", "statements")

# URL 路径里的日期：/2026/09/02/  或 /2026-09-02-  或 /20260902/
URL_PATS = [
    re.compile(r"/(20[12]\d)[/-](\d{1,2})[/-](\d{1,2})(?:[/-]|$)"),
    re.compile(r"/(20[12]\d)(\d{2})(\d{2})[/-]"),
    re.compile(r"[?&]date=(20[12]\d)-(\d{1,2})-(\d{1,2})"),
]
# 页面里的机器可读日期（优先，最可靠）
META_PATS = [
    re.compile(r'<time[^>]+datetime="(20[12]\d)-(\d{2})-(\d{2})', re.I),
    re.compile(r'"datePublished"\s*:\s*"(20[12]\d)-(\d{2})-(\d{2})', re.I),
    re.compile(r'property="article:published_time"\s+content="(20[12]\d)-(\d{2})-(\d{2})', re.I),
    re.compile(r'name="pubdate"\s+content="(20[12]\d)-(\d{2})-(\d{2})', re.I),
]


def mk(y, m, d):
    try:
        dt = date(int(y), int(m), int(d))
    except ValueError:
        return None
    if date(2015, 1, 1) <= dt <= date.today():
        return dt.isoformat()
    return None


def from_url(url):
    for p in URL_PATS:
        m = p.search(url or "")
        if m:
            got = mk(*m.groups())
            if got:
                return got
    return None


def from_page(url, timeout=12):
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/122 Safari/537.36"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            head = r.read(200_000).decode("utf-8", "replace")
    except Exception:
        return None
    for p in META_PATS:
        m = p.search(head)
        if m:
            got = mk(*m.groups())
            if got:
                return got
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--fetch-pages", action="store_true",
                    help="对 URL 抽不到的条目实际访问页面（慢但覆盖率高）")
    ap.add_argument("--limit-fetch", type=int, default=250)
    args = ap.parse_args()

    path = args.file if os.path.isabs(args.file) else os.path.join(STORE, args.file)
    recs = json.load(open(path, encoding="utf-8"))
    before = sum(1 for r in recs if r.get("published_on"))

    # 阶段 1：URL 路径（免费、瞬时）
    n_url = 0
    for r in recs:
        if r.get("published_on") or r.get("status") != "ok":
            continue
        got = from_url(r.get("source_url", ""))
        if got:
            r["published_on"] = got
            r["date_status"] = "verified"
            r["date_source"] = "url_path"
            n_url += 1
    json.dump(recs, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"阶段1 URL 路径：+{n_url} 条")

    # 阶段 2：抓页面 meta（慢，增量落盘）
    n_page = 0
    if args.fetch_pages:
        todo = [r for r in recs
                if not r.get("published_on") and r.get("status") == "ok"
                and r.get("source_url")][:args.limit_fetch]
        print(f"阶段2 抓页面 meta：{len(todo)} 条待查")
        for i, r in enumerate(todo, 1):
            got = from_page(r["source_url"])
            if got:
                r["published_on"] = got
                r["date_status"] = "verified"
                r["date_source"] = "page_meta"
                n_page += 1
            if i % 25 == 0:
                json.dump(recs, open(path, "w", encoding="utf-8"),
                          ensure_ascii=False, indent=2)
                print(f"  ... {i}/{len(todo)}  已补 {n_page}")
            time.sleep(0.25)
        json.dump(recs, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"阶段2 页面 meta：+{n_page} 条")

    after = sum(1 for r in recs if r.get("published_on"))
    ok = sum(1 for r in recs if r.get("status") == "ok")
    print(f"\n发表日核实：{before} → {after} / {ok} 条有效（{after*100//max(ok,1)}%）")
    print("抽不到的一律留空标 unverified，未用抓取日顶替")


if __name__ == "__main__":
    main()
