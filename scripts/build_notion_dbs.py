#!/usr/bin/env python3
"""War-KOL: 幂等建 4 个 Notion DB（名册 SSOT + 日/周/月三级时序）。

纪律：
- 禁止硬编码 page id 到脚本以外的地方；本脚本只硬编码【父页 id】(Chao 给的 War KOL page)，
  建出来的 DB id 一律写进 gitignored 的 data/notion_ids.json。
- 幂等：父页下已存在同名 DB 就复用，不重复建。
"""
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT_PAGE_ID = "3cf47eb5-fd3c-80e4-a2f2-d3619149c35f"  # War KOL page (Chao 提供)
IDS_PATH = os.path.join(ROOT, "data", "notion_ids.json")


def load_env():
    env = {}
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()
TOKEN = ENV.get("NOTION_TOKEN") or os.environ.get("NOTION_TOKEN")
NOTION_VERSION = ENV.get("NOTION_VERSION") or "2022-06-28"
if not TOKEN:
    sys.exit("缺 NOTION_TOKEN（.env）")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}


def api(method, path, payload=None):
    url = f"https://api.notion.com/v1/{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:800]
        raise RuntimeError(f"{method} {path} -> {e.code}: {body}") from None


THEATERS = ["俄乌", "中东", "印太", "南亚", "非洲", "拉美", "军工与战略"]
STARS = ["5★", "4★", "3★", "2★", "1★"]
# 立场方向：战争走势判断，不是多空。升级/僵持/降级 三分 + 未表态
DIRECTIONS = ["升级", "僵持", "降级", "未表态"]

SCHEMAS = {
    # ── 名册 SSOT ──────────────────────────────────────────────
    "War KOL List": {
        "Name": {"title": {}},
        "Name ZH": {"rich_text": {}},
        "Affiliation": {"rich_text": {}},
        "Role": {"rich_text": {}},
        "Theater": {"multi_select": {"options": [{"name": t} for t in THEATERS]}},
        "Language": {"rich_text": {}},
        "Specialty": {"rich_text": {}},
        "Rating": {"select": {"options": [{"name": s} for s in STARS]}},
        "Weighted Score": {"number": {"format": "number"}},
        "Score A Institutional": {"number": {"format": "number"}},
        "Score B FirstHand": {"number": {"format": "number"}},
        "Score C TrackRecord": {"number": {"format": "number"}},
        "Score D Transparency": {"number": {"format": "number"}},
        "Rating Provisional": {"checkbox": {}},
        "Rating Reason": {"rich_text": {}},
        "Controversies": {"rich_text": {}},
        "Primary URL": {"url": {}},
        "X Handle": {"rich_text": {}},
        "YouTube": {"url": {}},
        "Other Platforms": {"rich_text": {}},
        "Search Terms": {"rich_text": {}},
        "Active": {"checkbox": {}},
        "Watchlist": {"checkbox": {}},
        "Quality Flag": {"rich_text": {}},
        "Added On": {"date": {}},
        "Sources": {"rich_text": {}},
    },
    # ── 每日言论时序 ────────────────────────────────────────────
    "War KOL By Day": {
        "Title": {"title": {}},
        "Date": {"date": {}},
        "KOL": {"rich_text": {}},
        "Theater": {"select": {"options": [{"name": t} for t in THEATERS]}},
        "Direction": {"select": {"options": [{"name": d} for d in DIRECTIONS]}},
        "Summary": {"rich_text": {}},
        "Detail": {"rich_text": {}},
        "Quote": {"rich_text": {}},
        "Quote EN": {"rich_text": {}},
        "Source URL": {"url": {}},
        "Published On": {"date": {}},
        "Date Status": {
            "select": {
                "options": [
                    {"name": "verified"},
                    {"name": "unverified"},
                    {"name": "approx"},
                ]
            }
        },
        "Collected On": {"date": {}},
    },
    # ── 周度汇总 ────────────────────────────────────────────────
    "War KOL By Week": {
        "Title": {"title": {}},
        "Week Start": {"date": {}},
        "Theater": {"select": {"options": [{"name": t} for t in THEATERS]}},
        "Consensus Direction": {"select": {"options": [{"name": d} for d in DIRECTIONS]}},
        "Stance Changes": {"number": {"format": "number"}},
        "Active KOLs": {"number": {"format": "number"}},
        "Statements": {"number": {"format": "number"}},
        "Summary": {"rich_text": {}},
        "Key Developments": {"rich_text": {}},
    },
    # ── 月度汇总 ────────────────────────────────────────────────
    "War KOL By Month": {
        "Title": {"title": {}},
        "Month": {"date": {}},
        "Theater": {"select": {"options": [{"name": t} for t in THEATERS]}},
        "Consensus Direction": {"select": {"options": [{"name": d} for d in DIRECTIONS]}},
        "Statements": {"number": {"format": "number"}},
        "Predictions Due": {"number": {"format": "number"}},
        "Predictions Hit": {"number": {"format": "number"}},
        "Predictions Miss": {"number": {"format": "number"}},
        "Predictions Unclear": {"number": {"format": "number"}},
        "Summary": {"rich_text": {}},
        "Trend Notes": {"rich_text": {}},
    },
}


def existing_dbs():
    """列父页下已有的 child_database，返回 {标题: id}。"""
    found, cursor = {}, None
    while True:
        path = f"blocks/{PARENT_PAGE_ID}/children?page_size=100"
        if cursor:
            path += f"&start_cursor={cursor}"
        res = api("GET", path)
        for b in res.get("results", []):
            if b.get("type") == "child_database":
                found[b["child_database"]["title"]] = b["id"]
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return found


def main():
    have = existing_dbs()
    print(f"父页下已有 DB: {list(have) or '（无）'}")
    ids = {}
    if os.path.exists(IDS_PATH):
        ids = json.load(open(IDS_PATH, encoding="utf-8"))

    for title, props in SCHEMAS.items():
        if title in have:
            ids[title] = have[title]
            print(f"[复用] {title} -> {have[title]}")
            continue
        res = api(
            "POST",
            "databases",
            {
                "parent": {"type": "page_id", "page_id": PARENT_PAGE_ID},
                "title": [{"type": "text", "text": {"content": title}}],
                "properties": props,
            },
        )
        ids[title] = res["id"]
        print(f"[新建] {title} -> {res['id']}")

    os.makedirs(os.path.dirname(IDS_PATH), exist_ok=True)
    json.dump(ids, open(IDS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n已写入 {IDS_PATH}")

    # 写后读回验证
    print("\n── 读回验证 ──")
    for title, db_id in ids.items():
        got = api("GET", f"databases/{db_id}")
        got_title = "".join(t.get("plain_text", "") for t in got.get("title", []))
        print(f"  {got_title}: {len(got.get('properties', {}))} 个字段  id={db_id}")


if __name__ == "__main__":
    main()
