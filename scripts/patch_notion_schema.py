#!/usr/bin/env python3
"""给已存在的 Notion DB 增补属性（幂等）。

build_notion_dbs.py 遇到同名 DB 是【复用】而非改 schema，
所以后加的字段要用本脚本 PATCH 上去。已存在的属性不动。
"""
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDS = os.path.join(ROOT, "data", "notion_ids.json")


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
H = {
    "Authorization": f"Bearer {ENV['NOTION_TOKEN']}",
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
        sys.exit(f"{method} {path} -> {e.code}: {e.read().decode()[:500]}")


# 要确保存在的属性：{DB 名: {属性名: 定义}}
WANT = {
    "War KOL List": {
        "Watchlist": {"checkbox": {}},
        "Quality Flag": {"rich_text": {}},
    }
}


def main():
    ids = json.load(open(IDS, encoding="utf-8"))
    for db_name, props in WANT.items():
        db_id = ids[db_name]
        cur = api("GET", f"databases/{db_id}")["properties"]
        add = {k: v for k, v in props.items() if k not in cur}
        if not add:
            print(f"[跳过] {db_name}: {list(props)} 均已存在")
            continue
        api("PATCH", f"databases/{db_id}", {"properties": add})
        after = api("GET", f"databases/{db_id}")["properties"]
        ok = [k for k in add if k in after]
        print(f"[已加] {db_name}: {ok}  (现共 {len(after)} 字段)")


if __name__ == "__main__":
    main()
