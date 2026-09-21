#!/usr/bin/env python3
"""War-KOL: 把审定后的名册写进 Notion「War KOL List」DB（增量 upsert，只增不删）。

纪律（AGENTS.md）：
- **绝不 archive 全量重写**（Forecast-Checker 的 sync_notion_full.py 就是反面教材：
  先 archive 全部行再重写，会抹掉人工编辑过的字段，违反「只增不删」）。
- 幂等 upsert：按 Name 精确匹配已有行 → PATCH；无则新建。
- ★ skip_none：PATCH 已有行时剔除空值字段，**不覆盖 Notion 上已有真值**
  （Eco 的 BofA 类回归根因：prop_num(None) 生成 {"number":None} 会把真值清空）。
- 禁止硬编码 page id，一律从 gitignored 的 data/notion_ids.json 读。
- 写后读回验证。

用法：
  python3 scripts/write_roster_to_notion.py --dry-run   # 只看会写什么
  python3 scripts/write_roster_to_notion.py             # 实写
"""
import argparse
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
ROSTER = os.path.join(DATA, "roster_final.json")
DB_KEY = "War KOL List"


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


def api(method, path, payload=None, retries=3):
    url = f"https://api.notion.com/v1/{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=HEADERS, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:500]
            if e.code == 429 and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"{method} {path} -> {e.code}: {body}") from None
        except Exception:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError(f"{method} {path} 重试 {retries} 次仍失败")


# ── prop 构造：空值一律返回 None，由 skip_none 过滤掉 ──────────────
def p_title(v):
    return {"title": [{"text": {"content": str(v)[:2000]}}]} if v else None


def p_text(v):
    if v is None or v == "" or v == []:
        return None
    if isinstance(v, (list, tuple)):
        v = " | ".join(str(x) for x in v if x)
    return {"rich_text": [{"text": {"content": str(v)[:2000]}}]} if v else None


def p_num(v):
    return {"number": float(v)} if v is not None and v != "" else None


def p_select(v):
    return {"select": {"name": str(v)[:100]}} if v else None


def p_multi(vs):
    vs = [str(x)[:100] for x in (vs or []) if x]
    return {"multi_select": [{"name": x} for x in vs]} if vs else None


def p_url(v):
    v = (v or "").strip()
    return {"url": v} if v.startswith(("http://", "https://")) else None


def p_check(v):
    return {"checkbox": bool(v)}


def p_date(v):
    return {"date": {"start": str(v)}} if v else None


def build_props(r):
    stars = r.get("stars")
    return {
        "Name": p_title(r.get("name_en") or r.get("name_zh")),
        "Name ZH": p_text(r.get("name_zh")),
        "Affiliation": p_text(r.get("affiliation")),
        "Role": p_text(r.get("role")),
        "Theater": p_multi(
            r.get("theater") if isinstance(r.get("theater"), list) else [r.get("theater")]
        ),
        "Language": p_text(r.get("language")),
        "Specialty": p_text(r.get("specialty")),
        "Rating": p_select(f"{stars}★" if stars else None),
        "Weighted Score": p_num(r.get("weighted_score_recomputed") or r.get("weighted_score")),
        "Score A Institutional": p_num(r.get("score_A")),
        "Score B FirstHand": p_num(r.get("score_B")),
        "Score C TrackRecord": p_num(r.get("score_C")),
        "Score D Transparency": p_num(r.get("score_D")),
        "Rating Provisional": p_check(r.get("rating_provisional")),
        "Rating Reason": p_text(r.get("rating_reason")),
        "Controversies": p_text(r.get("controversies")),
        "Primary URL": p_url(r.get("primary_url") or (r.get("sources") or [None])[0]),
        "X Handle": p_text(r.get("x_handle")),
        "YouTube": p_url(r.get("youtube")),
        "Other Platforms": p_text(r.get("platforms")),
        "Search Terms": p_text(r.get("search_terms")),
        "Active": p_check(r.get("active", True)),
        "Watchlist": p_check(r.get("watchlist")),
        "Quality Flag": p_text(r.get("quality_flag")),
        "Added On": p_date(r.get("added_on") or date.today().isoformat()),
        "Sources": p_text(r.get("sources")),
    }


def strip_none(props, skip_none=True):
    if not skip_none:
        return {k: v for k, v in props.items() if v is not None}
    return {k: v for k, v in props.items() if v is not None}


def fetch_existing(db_id):
    """返回 {Name(小写去空格): page_id}。"""
    out, cursor = {}, None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        res = api("POST", f"databases/{db_id}/query", payload)
        for row in res.get("results", []):
            t = row.get("properties", {}).get("Name", {}).get("title", [])
            nm = "".join(x.get("plain_text", "") for x in t).strip()
            if nm:
                out[nm.lower()] = row["id"]
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--roster", default=ROSTER)
    args = ap.parse_args()

    if not os.path.exists(IDS_PATH):
        sys.exit(f"缺 {IDS_PATH}，先跑 scripts/build_notion_dbs.py")
    db_id = json.load(open(IDS_PATH, encoding="utf-8"))[DB_KEY]

    if not os.path.exists(args.roster):
        sys.exit(f"缺名册 {args.roster}")
    roster = json.load(open(args.roster, encoding="utf-8"))
    print(f"名册 {len(roster)} 人  →  DB {db_id}")

    existing = fetch_existing(db_id)
    print(f"Notion 已有 {len(existing)} 行")

    created = updated = 0
    for r in roster:
        name = (r.get("name_en") or r.get("name_zh") or "").strip()
        if not name:
            print("  [跳过] 无名字段")
            continue
        props = strip_none(build_props(r))
        pid = existing.get(name.lower())
        if args.dry_run:
            print(f"  [{'PATCH' if pid else 'CREATE'}] {name}  ({len(props)} 字段)")
            continue
        if pid:
            api("PATCH", f"pages/{pid}", {"properties": props})
            updated += 1
        else:
            api("POST", "pages", {"parent": {"database_id": db_id}, "properties": props})
            created += 1
        time.sleep(0.35)  # Notion 限速 ~3 req/s

    if args.dry_run:
        print("\n(dry-run，未写入)")
        return

    print(f"\n新建 {created}  更新 {updated}")
    # 写后读回验证
    after = fetch_existing(db_id)
    print(f"读回验证：Notion 现有 {len(after)} 行")
    missing = [
        (r.get("name_en") or r.get("name_zh"))
        for r in roster
        if (r.get("name_en") or r.get("name_zh", "")).lower() not in after
    ]
    if missing:
        print(f"⚠ 以下 {len(missing)} 人未在 Notion 读到：{missing}")
    else:
        print("✓ 名册全部人员已在 Notion 确认")


if __name__ == "__main__":
    main()
