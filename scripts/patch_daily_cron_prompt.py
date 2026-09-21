#!/usr/bin/env python3
"""把缺失的「发表日回补」步骤补进 war-kol-daily cron prompt。

背景（2026-09-05 周报官实测）：
daily prompt 只有步骤 0/1/2/3/4，唯独没有 enrich_dates.py。09-02/09-03 的
41.6%/42.2% 发表日覆盖率是人工手跑出来的；09-04 起无人跑 → 覆盖率塌到 0.3%/0.0%，
导致按 published_on 筛选的周报/时间线全部落空。

同时 extract_thesis 在进程启动时快照读 statements，必须排在 enrich_dates 之后，
否则 thesis 侧残留 published_on=null（09-05 实测唯一合格言论因此不可见）。
故插入顺序：步骤1 抓取 → 步骤1.5 回补发表日 → 步骤2 五要素抽取。
"""
import json
import shutil
import sys
from datetime import datetime

JOBS = "/home/user/.hermes/cron/jobs.json"
JOB_ID = "bebf9f3b45ba"  # war-kol-daily

NEW_STEP = """**步骤 1.5 · 回补发表日（不可跳过，必须在五要素抽取之前）**
```
python3 scripts/enrich_dates.py --file daily_$(date +%Y-%m-%d).json --fetch-pages --limit-fetch 400
```
★ 为什么必须有这一步（2026-09-05 实测事故）：
ddgs 摘要普遍不含日期，抓取产物的 published_on 原始覆盖率仅 0%-8%。
不跑这一步，发表日覆盖率就是 0，**所有按发表日筛选的下游（周报 / 月报 / 时间线）
全部落空**。跑完典型覆盖率约 40%。
★ 顺序铁律：必须排在步骤 2 之前。extract_thesis.py 在进程启动时快照读入
statements，若它先跑，thesis 产物里会残留 published_on=null，即使 statements
侧事后补上也不会自动同步。
★ 若步骤 2 已经先跑了（例如自愈脚本触发），补跑：
```
python3 scripts/propagate_dates_to_thesis.py
```
它按 source_url 精确 join 把 statements 的发表日回填进 thesis，只填空、不覆盖、
冲突只报告不改写。
★ 纪律不变：抽不到就留空标 unverified，**绝不用 collected_on 顶替**。

"""

ANCHOR = "**步骤 2 · 五要素抽取"


def main() -> int:
    data = json.load(open(JOBS, encoding="utf-8"))
    jobs = data if isinstance(data, list) else data.get("jobs", [])

    job = next((j for j in jobs if j.get("id") == JOB_ID), None)
    if not job:
        print(f"找不到 job {JOB_ID}", file=sys.stderr)
        return 1

    p = job.get("prompt") or ""
    if "步骤 1.5" in p or "enrich_dates" in p:
        print("prompt 已含发表日回补步骤，无需改动")
        return 0
    if ANCHOR not in p:
        print(f"找不到锚点 {ANCHOR!r}，中止（不盲改）", file=sys.stderr)
        return 1

    bak = f"{JOBS}.bak-enrichdates-{datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(JOBS, bak)
    print(f"已备份 → {bak}")

    job["prompt"] = p.replace(ANCHOR, NEW_STEP + ANCHOR, 1)
    json.dump(data, open(JOBS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    check = json.load(open(JOBS, encoding="utf-8"))
    cjobs = check if isinstance(check, list) else check.get("jobs", [])
    cj = next(j for j in cjobs if j.get("id") == JOB_ID)
    ok = "步骤 1.5" in cj["prompt"] and "enrich_dates" in cj["prompt"]
    print(f"写回校验：{'通过' if ok else '失败'}；prompt {len(p)} → {len(cj['prompt'])} 字符")
    print(f"job 总数 {len(jobs)} → {len(cjobs)}（应相等）")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
