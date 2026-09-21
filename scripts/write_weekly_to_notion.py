#!/usr/bin/env python3
"""War-KOL: 把周度汇总写进 Notion「War KOL By Week」（幂等 upsert）。

纪律（AGENTS.md）：
- DB id 从 data/notion_ids.json 读，禁止硬编码任何 page id。
- 幂等：按 (Week Start + Theater) 去重；已存在则 PATCH，不新建重复行。
- ★ skip_none：PATCH 时剔除 None 值，绝不把 Notion 已有真值覆盖成空。
- 本周无数据的战区照样占位（Statements=0），保骨架完整，但 Summary 如实写「无合格言论」。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
IDS_PATH = os.path.join(DATA, "notion_ids.json")
DB_KEY = "War KOL By Week"
THEATERS = ["俄乌", "中东", "印太", "南亚", "非洲", "拉美", "军工与战略"]


def load_env() -> dict:
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


def api(method: str, path: str, payload=None, retries: int = 3):
    last = None
    for a in range(retries):
        req = urllib.request.Request(
            f"https://api.notion.com/v1/{path}",
            data=json.dumps(payload).encode() if payload else None,
            headers=H, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            last = f"HTTP {e.code}: {body[:400]}"
            if e.code in (429, 502, 503, 504):
                time.sleep(2 * (a + 1))
                continue
            raise RuntimeError(last) from e
        except Exception as e:  # noqa: BLE001
            last = repr(e)
            time.sleep(2 * (a + 1))
    raise RuntimeError(f"Notion API 失败：{last}")


def rt(text: str) -> list:
    text = (text or "")[:1900]
    return [{"type": "text", "text": {"content": text}}] if text else []


def skip_none(props: dict) -> dict:
    return {k: v for k, v in props.items() if v is not None}


def query_existing(db_id: str, week_start: str) -> dict:
    """返回 {theater: page_id}，只查本周。"""
    out, cursor = {}, None
    while True:
        payload = {
            "filter": {"property": "Week Start", "date": {"equals": week_start}},
            "page_size": 100,
        }
        if cursor:
            payload["start_cursor"] = cursor
        res = api("POST", f"databases/{db_id}/query", payload)
        for pg in res.get("results", []):
            sel = (pg["properties"].get("Theater") or {}).get("select")
            if sel:
                out[sel["name"]] = pg["id"]
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return out


def build_summary(th: str, agg: dict, rows: list, changes: list,
                  changes30: list | None = None, win30: dict | None = None) -> str:
    n = agg["n_statements"]
    if n == 0:
        head = (f"{th}：本周（7日窗口）无发表日落在本周且通过五要素门槛的言论。"
                f"本项目日均合格言论个位数，低频战区空周属正常，非管道故障。")
    else:
        head = (f"{th}：本周合格言论 {n} 条，活跃 KOL {agg['n_kol']} 人，"
                f"主导方向「{agg['dominant']}」。方向分布 {agg['dir_counts']}。")
    parts = [head]
    for r in rows[:3]:
        parts.append(
            f"· {r.get('kol')}（{r.get('published_on')}）：{(r.get('claim') or '')[:180]}")
    if changes:
        parts.append("7日窗口立场转向：" + "；".join(
            f"{c['kol']} {c['from']}→{c['to']}" for c in changes))
    if changes30:
        w = ""
        if win30:
            w = f"（{win30['cur'][0]}..{win30['cur'][1]} vs {win30['prev'][0]}..{win30['prev'][1]}）"
        parts.append(f"30日窗口立场转向{w}：" + "；".join(
            f"{c['kol']} {c['from']}→{c['to']}" for c in changes30))
    return "\n".join(parts)


def build_keydev(rows: list) -> str:
    lines = []
    for r in rows[:5]:
        d = r.get("data") or []
        dstr = ""
        if d and isinstance(d[0], dict):
            dstr = f" [{d[0].get('metric')}={d[0].get('value')}]"
        lines.append(f"{r.get('kol')} | {r.get('published_on')} | "
                     f"{(r.get('topic') or '')[:60]}{dstr} | {r.get('source_url')}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week-file", help="data/weekly/week_*.json；默认取最新")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = args.week_file
    if not path:
        cands = sorted(glob.glob(os.path.join(DATA, "weekly", "week_*.json")))
        if not cands:
            sys.exit("找不到 data/weekly/week_*.json，先跑 scripts/weekly_rollup.py")
        path = cands[-1]
    week = json.load(open(path, encoding="utf-8"))

    ids = json.load(open(IDS_PATH, encoding="utf-8"))
    db_id = ids.get(DB_KEY)
    if not db_id:
        sys.exit(f"notion_ids.json 缺 key: {DB_KEY}")

    ws, we = week["week_start"], week["week_end"]
    rows_all = week.get("rows_in_week", [])
    changes_all = week.get("stance_changes", [])
    changes30_all = week.get("stance_changes_30d", [])
    win30 = week.get("window30", {})

    existing = {} if args.dry_run else query_existing(db_id, ws)
    print(f"[{DB_KEY}] week {ws}..{we}  已存在 {len(existing)} 行")

    n_new = n_upd = 0
    for th in THEATERS:
        agg = week["theaters"][th]
        rows = [r for r in rows_all if r.get("theater") == th]
        rows.sort(key=lambda r: r.get("published_on") or "", reverse=True)
        ch = [c for c in changes_all if c.get("theater") == th]
        ch30 = [c for c in changes30_all if c.get("theater") == th]

        props = skip_none({
            "Title": {"title": rt(f"{ws} · {th}")},
            "Week Start": {"date": {"start": ws, "end": we}},
            "Theater": {"select": {"name": th}},
            "Statements": {"number": agg["n_statements"]},
            "Active KOLs": {"number": agg["n_kol"]},
            "Consensus Direction": ({"select": {"name": agg["dominant"]}}
                                    if agg["dominant"] in
                                    ("升级", "僵持", "降级", "未表态") else None),
            "Stance Changes": {"number": len(ch) + len(ch30)},
            "Summary": {"rich_text": rt(build_summary(th, agg, rows, ch, ch30, win30))},
            "Key Developments": ({"rich_text": rt(build_keydev(rows))}
                                 if rows else None),
        })

        if args.dry_run:
            print(f"  [dry] {th}: n={agg['n_statements']} "
                  f"dom={agg['dominant']} chg7={len(ch)} chg30={len(ch30)}")
            continue

        pid = existing.get(th)
        if pid:
            api("PATCH", f"pages/{pid}", {"properties": props})
            n_upd += 1
            print(f"  [upd] {th}  page_id={pid}")
        else:
            res = api("POST", "pages",
                      {"parent": {"database_id": db_id}, "properties": props})
            n_new += 1
            print(f"  [new] {th}  page_id={res['id']}")
        time.sleep(0.35)

    print(f"\n完成：新建 {n_new} / 更新 {n_upd}（共 {len(THEATERS)} 战区）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
