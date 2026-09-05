#!/usr/bin/env python3
"""War-KOL: 把抓到的言论写进 Notion「War KOL By Day」（幂等 upsert，只增不删）。

纪律（AGENTS.md）：
- 幂等：按 (KOL + Source URL) 去重；已存在则 PATCH，不新建重复行。
- ★ skip_none：PATCH 已有行时剔除空值，绝不把 Notion 已有真值覆盖成空
  （Eco 的 BofA 类回归根因）。
- 绝不 archive 全量重写。
- status != ok 的占位记录（本轮没抓到）不写 Notion，只留本地留痕。
- 发表日查不到者 Published On 留空、Date Status=unverified，
  【绝不用 collected_on 顶替】。
"""
import argparse
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
IDS_PATH = os.path.join(DATA, "notion_ids.json")
STORE = os.path.join(DATA, "statements")
DB_KEY = "War KOL By Day"


def load_env():
    env = {}
    p = os.path.join(ROOT, ".env")
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()
TOKEN = ENV.get("NOTION_TOKEN") or os.environ.get("NOTION_TOKEN")
if not TOKEN:
    sys.exit("缺 NOTION_TOKEN")
H = {
    "Authorization": f"Bearer {TOKEN}",
    "Notion-Version": ENV.get("NOTION_VERSION") or "2022-06-28",
    "Content-Type": "application/json",
}


def api(method, path, payload=None, retries=3):
    for a in range(retries):
        req = urllib.request.Request(
            f"https://api.notion.com/v1/{path}",
            data=json.dumps(payload).encode() if payload else None,
            headers=H, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and a < retries - 1:
                time.sleep(2 ** a)
                continue
            raise RuntimeError(f"{method} {path} -> {e.code}: {e.read().decode()[:400]}")
        except Exception:
            if a < retries - 1:
                time.sleep(2 ** a)
                continue
            raise
    raise RuntimeError(f"{method} {path} 重试耗尽")


def p_title(v):
    return {"title": [{"text": {"content": str(v)[:2000]}}]} if v else None


def p_text(v):
    v = "" if v is None else str(v)
    return {"rich_text": [{"text": {"content": v[:2000]}}]} if v.strip() else None


def p_sel(v):
    return {"select": {"name": str(v)[:100]}} if v else None


def p_url(v):
    v = (v or "").strip()
    return {"url": v} if v.startswith("http") else None


def p_date(v):
    return {"date": {"start": str(v)}} if v else None


def build(r):
    kol = r.get("kol", "")
    title = (r.get("title") or "")[:180]
    return {
        "Title": p_title(f"{kol} · {title}" if title else kol),
        "Date": p_date(r.get("published_on") or r.get("collected_on")),
        "KOL": p_text(kol),
        "Theater": p_sel(r.get("theater")),
        "Direction": p_sel(r.get("direction")),
        "Summary": p_text(r.get("summary")),
        "Detail": p_text(r.get("detail")),
        "Quote": p_text(r.get("quote")),
        "Quote EN": p_text(r.get("quote_en")),
        "Source URL": p_url(r.get("source_url")),
        # ★ 查不到发表日就留空，绝不用 collected_on 顶替
        "Published On": p_date(r.get("published_on")),
        "Date Status": p_sel(r.get("date_status") or "unverified"),
        "Collected On": p_date(r.get("collected_on")),
    }


def strip_none(d):
    return {k: v for k, v in d.items() if v is not None}


def existing_keys(db_id):
    """{(kol, url): page_id}"""
    out, cur = {}, None
    while True:
        pl = {"page_size": 100}
        if cur:
            pl["start_cursor"] = cur
        res = api("POST", f"databases/{db_id}/query", pl)
        for row in res["results"]:
            p = row["properties"]
            kol = "".join(x.get("plain_text", "")
                          for x in p.get("KOL", {}).get("rich_text", []))
            url = p.get("Source URL", {}).get("url") or ""
            if kol or url:
                out[(kol.strip(), url.strip())] = row["id"]
        if not res.get("has_more"):
            break
        cur = res["next_cursor"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None, help="指定 statements json；默认全量合并")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    db_id = json.load(open(IDS_PATH, encoding="utf-8"))[DB_KEY]

    files = [args.file] if args.file else sorted(glob.glob(os.path.join(STORE, "*.json")))
    recs = []
    for f in files:
        try:
            recs.extend(json.load(open(f, encoding="utf-8")))
        except Exception as e:
            print(f"  [跳过] {f}: {e}")

    # 只写有效条目；占位记录（本轮没抓到）不进 Notion，只留本地
    valid, seen = [], set()
    for r in recs:
        if r.get("status") != "ok" or not r.get("source_url"):
            continue
        k = (r.get("kol", "").strip(), r.get("source_url", "").strip())
        if k in seen:
            continue
        seen.add(k)
        valid.append(r)

    print(f"读入 {len(recs)} 条 → 有效去重后 {len(valid)} 条")
    if args.limit:
        valid = valid[:args.limit]

    have = existing_keys(db_id)
    print(f"Notion By Day 已有 {len(have)} 行")

    created = updated = 0
    for i, r in enumerate(valid, 1):
        key = (r.get("kol", "").strip(), r.get("source_url", "").strip())
        props = strip_none(build(r))
        pid = have.get(key)
        if args.dry_run:
            if i <= 8:
                print(f"  [{'PATCH' if pid else 'CREATE'}] {key[0][:22]} | {r.get('title','')[:48]}")
            continue
        if pid:
            api("PATCH", f"pages/{pid}", {"properties": props})
            updated += 1
        else:
            api("POST", "pages", {"parent": {"database_id": db_id}, "properties": props})
            created += 1
        if i % 25 == 0:
            print(f"  ... {i}/{len(valid)}")
        time.sleep(0.35)

    if args.dry_run:
        print("(dry-run，未写入)")
        return
    print(f"\n新建 {created}  更新 {updated}")
    after = existing_keys(db_id)
    print(f"读回验证：Notion 现有 {len(after)} 行")


if __name__ == "__main__":
    main()
