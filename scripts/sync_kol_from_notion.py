#!/usr/bin/env python3
"""War-KOL 名册单向镜像：Notion「War KOL List」→ 本地 data/kol_registry.json。

★ 名册铁律（AGENTS.md，最高优先级）：
  SSOT = Notion。本脚本【只读 Notion、只写本地】，绝不反向写 Notion，
  也绝不自行增删任何 KOL。挂在每日 cron 的步骤 0（所有抓取之前）。

★ 匹配坑（Eco 项目实测教训，务必保留此逻辑）：
  Notion 名常带机构后缀，如「Nomi Prins（… 前 Goldman Sachs MD）」。
  若用双向子串模糊匹配，本地「Goldman Sachs」会抢先吃掉这一行，
  导致 Nomi Prins 被误判为「Notion 无」而错误移出。
  正解：先全量精确匹配 → 模糊只认「本地名 ⊂ Notion 名」单方向
        → 取最短候选 → 已配对者不再参与模糊。

★ 本地独有采集配置（search_terms / youtube / x_handle 等）保留不被覆盖。
★ 移出者落盘 data/kol_removed_<date>.json 留痕，其历史抓取文件一律保留不删。
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
IDS_PATH = os.path.join(DATA, "notion_ids.json")
REGISTRY = os.path.join(DATA, "kol_registry.json")
DB_KEY = "War KOL List"

# 本地独有、不被 Notion 覆盖的采集配置字段
LOCAL_ONLY = ("search_terms", "rss", "last_fetched", "fetch_notes")


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
if not TOKEN:
    sys.exit("缺 NOTION_TOKEN")
H = {
    "Authorization": f"Bearer {TOKEN}",
    "Notion-Version": ENV.get("NOTION_VERSION") or "2022-06-28",
    "Content-Type": "application/json",
}


def api(method, path, payload=None):
    req = urllib.request.Request(
        f"https://api.notion.com/v1/{path}",
        data=json.dumps(payload).encode() if payload else None,
        headers=H,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> {e.code}: {e.read().decode()[:400]}")


def txt(prop):
    if not prop:
        return ""
    t = prop.get("type")
    if t == "title":
        return "".join(x.get("plain_text", "") for x in prop["title"]).strip()
    if t == "rich_text":
        return "".join(x.get("plain_text", "") for x in prop["rich_text"]).strip()
    if t == "select":
        return (prop.get("select") or {}).get("name", "")
    if t == "multi_select":
        return [x["name"] for x in prop.get("multi_select", [])]
    if t == "number":
        return prop.get("number")
    if t == "checkbox":
        return prop.get("checkbox", False)
    if t == "url":
        return prop.get("url") or ""
    if t == "date":
        d = prop.get("date") or {}
        return d.get("start", "")
    return ""


def fetch_notion():
    db_id = json.load(open(IDS_PATH, encoding="utf-8"))[DB_KEY]
    rows, cursor = [], None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        res = api("POST", f"databases/{db_id}/query", payload)
        for row in res["results"]:
            p = row["properties"]
            name = txt(p.get("Name"))
            if not name:
                continue
            rows.append({
                "page_id": row["id"],
                "name_en": name,
                "name_zh": txt(p.get("Name ZH")),
                "affiliation": txt(p.get("Affiliation")),
                "role": txt(p.get("Role")),
                "theater": txt(p.get("Theater")) or [],
                "language": txt(p.get("Language")),
                "specialty": txt(p.get("Specialty")),
                "rating": txt(p.get("Rating")),
                "weighted_score": txt(p.get("Weighted Score")),
                "score_A": txt(p.get("Score A Institutional")),
                "score_B": txt(p.get("Score B FirstHand")),
                "score_C": txt(p.get("Score C TrackRecord")),
                "score_D": txt(p.get("Score D Transparency")),
                "rating_provisional": txt(p.get("Rating Provisional")),
                "rating_reason": txt(p.get("Rating Reason")),
                "controversies": txt(p.get("Controversies")),
                "primary_url": txt(p.get("Primary URL")),
                "x_handle": txt(p.get("X Handle")),
                "youtube": txt(p.get("YouTube")),
                "platforms": txt(p.get("Other Platforms")),
                "search_terms_notion": txt(p.get("Search Terms")),
                "active": txt(p.get("Active")),
                "watchlist": txt(p.get("Watchlist")),
                "quality_flag": txt(p.get("Quality Flag")),
                "sources": txt(p.get("Sources")),
            })
        if not res.get("has_more"):
            break
        cursor = res["next_cursor"]
    return rows


def norm(s):
    s = (s or "").strip().lower()
    s = re.sub(r"[.\-_'’,()（）]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def match_local_to_notion(local, notion):
    """返回 {本地名: notion记录}。见文件头「匹配坑」。"""
    pairs = {}
    n_by_norm = {norm(n["name_en"]): n for n in notion}
    used = set()

    # 阶段 1：全量精确匹配（先做完，避免被模糊抢走）
    for lo in local:
        key = norm(lo.get("name_en"))
        if key in n_by_norm and id(n_by_norm[key]) not in used:
            pairs[lo["name_en"]] = n_by_norm[key]
            used.add(id(n_by_norm[key]))

    # 阶段 2：模糊只认「本地名 ⊂ Notion 名」单方向，取最短候选
    for lo in local:
        if lo["name_en"] in pairs:
            continue
        lkey = norm(lo.get("name_en"))
        if not lkey:
            continue
        cands = [
            n for n in notion
            if id(n) not in used and lkey in norm(n["name_en"])
        ]
        if cands:
            best = min(cands, key=lambda n: len(n["name_en"]))
            pairs[lo["name_en"]] = best
            used.add(id(best))
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写入本地 registry")
    args = ap.parse_args()

    notion = fetch_notion()
    active = [n for n in notion if n["active"]]
    print(f"Notion: {len(notion)} 行，其中 active {len(active)}")

    local = []
    if os.path.exists(REGISTRY):
        local = json.load(open(REGISTRY, encoding="utf-8"))
    print(f"本地 registry: {len(local)} 人")

    pairs = match_local_to_notion(local, notion)
    matched_notion_ids = {n["page_id"] for n in pairs.values()}

    new_registry = []
    for n in active:
        rec = dict(n)
        # 找回本地独有采集配置
        for lo in local:
            if pairs.get(lo.get("name_en", "")) is n:
                for k in LOCAL_ONLY:
                    if lo.get(k):
                        rec[k] = lo[k]
                break
        rec.setdefault("search_terms", rec.get("search_terms_notion") or rec["name_en"])
        new_registry.append(rec)

    # 移出者 = 本地有、但 Notion 侧已非 active（或已删）
    active_ids = {n["page_id"] for n in active}
    removed = []
    for lo in local:
        n = pairs.get(lo.get("name_en", ""))
        if n is None or n["page_id"] not in active_ids:
            removed.append(lo)

    added = [n["name_en"] for n in active
             if n["page_id"] not in matched_notion_ids]

    print(f"\n镜像结果：registry 将有 {len(new_registry)} 人")
    if added:
        print(f"  新增 {len(added)}: {added[:8]}{' ...' if len(added) > 8 else ''}")
    if removed:
        print(f"  移出 {len(removed)}: {[r.get('name_en') for r in removed][:8]}")

    if not args.apply:
        print("\n(dry-run，未写入。加 --apply 生效)")
        return

    if removed:
        rm_path = os.path.join(DATA, f"kol_removed_{date.today().isoformat()}.json")
        json.dump(removed, open(rm_path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print(f"  移出者留痕 → {rm_path}（历史抓取文件一律保留不删）")

    json.dump(new_registry, open(REGISTRY, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n✓ 已写入 {REGISTRY}（{len(new_registry)} 人）")


if __name__ == "__main__":
    main()
