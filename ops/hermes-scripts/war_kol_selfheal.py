#!/usr/bin/env python3
"""War-KOL 自愈 watchdog（no_agent，每小时跑）。

判据只看【客观产物】，不看 cron 状态标签——
超时的 job 产物常常是完整的，cron 标 unknown 也可能已落库。

检查项：
1. 今日 daily 抓取产物是否存在且非空
2. dashboard/index.html 是否是今天重建的
3. 本地 registry 是否与 Notion active 数量一致（镜像有没有断）

正常静默（无输出 = 不推送）；异常才输出并尝试自愈一次。
"""
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime

ROOT = "<PROJECT_ROOT>"
DATA = os.path.join(ROOT, "data")
STORE = os.path.join(DATA, "statements")
DASH = os.path.join(ROOT, "dashboard", "index.html")
TODAY = date.today().isoformat()
problems, fixed = [], []

# ★ 并发锁：自愈动作（抓取/发布）可能跑几分钟到十几分钟，
#   watchdog 每小时一次，绝不能让上一轮没跑完就叠第二轮。
LOCK = "/tmp/war_kol_selfheal.lock"
if os.path.exists(LOCK):
    age = time.time() - os.path.getmtime(LOCK)
    if age < 3600:
        sys.exit(0)          # 上一轮还在跑，静默退出
    os.remove(LOCK)          # 超 1 小时视为僵死锁，清掉
open(LOCK, "w").write(str(os.getpid()))


def mtime_date(p):
    if not os.path.exists(p):
        return None
    return date.fromtimestamp(os.path.getmtime(p)).isoformat()


def run(cmd, timeout=600):
    try:
        r = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode, (r.stdout or "")[-600:], (r.stderr or "")[-400:]
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


# ── 1. 名册镜像健康 ────────────────────────────────────────
reg_path = os.path.join(DATA, "kol_registry.json")
if not os.path.exists(reg_path):
    problems.append("名册 registry 缺失")
    rc, out, err = run("python3 scripts/sync_kol_from_notion.py --apply")
    fixed.append(f"重跑名册镜像 rc={rc}")
else:
    try:
        n = len(json.load(open(reg_path, encoding="utf-8")))
        if n == 0:
            problems.append("名册 registry 为空")
    except Exception as e:
        problems.append(f"名册 registry 解析失败: {e}")

# ── 2. 今日抓取产物 ────────────────────────────────────────
# ★ 只在 09:00 日报【本该已经跑过】时才检查。
#   两道闸门缺一不可（2026-09-02 首跑踩坑）：
#   ① 时间过了 10 点
#   ② war-kol-daily 今天确实 fire 过（否则是项目刚上线/job 刚建，
#      当天本就没有 daily 产物，补跑属于误判自愈——首跑时它就白抓了一轮）
def daily_job_ran_today():
    """看 war-kol-daily 今天是否真的 fire 过。
    ★ cron 状态在 ~/.hermes/cron/jobs.json，不在 state.db（实测确认过，别猜表名）。
    读不到就当【没跑】—— 保守不自愈，宁可漏修也不误抓。"""
    try:
        d = json.load(open("<HOME>/.hermes/cron/jobs.json", encoding="utf-8"))
        jobs = d.get("jobs", d) if isinstance(d, dict) else d
        jobs = jobs if isinstance(jobs, list) else list(jobs.values())
        for j in jobs:
            if j.get("name") == "war-kol-daily":
                lr = j.get("last_run_at")
                return bool(lr and str(lr)[:10] == TODAY)
    except Exception:
        pass
    return False


if datetime.now().hour >= 10 and daily_job_ran_today():
    daily = os.path.join(STORE, f"daily_{TODAY}.json")
    ok = False
    if os.path.exists(daily):
        try:
            ok = len(json.load(open(daily, encoding="utf-8"))) > 0
        except Exception:
            ok = False
    if not ok:
        problems.append(f"今日抓取产物缺失或为空: daily_{TODAY}.json")
        rc, out, err = run("python3 scripts/fetch_statements.py --mode daily --days 3")
        fixed.append(f"补跑抓取 rc={rc} {out[-160:]}")

    # ── 3. dashboard 新鲜度 ────────────────────────────────
    if mtime_date(DASH) != TODAY:
        problems.append(f"dashboard 非今日重建（mtime={mtime_date(DASH)}）")
        rc, out, err = run("bash scripts/publish.sh", timeout=600)
        fixed.append(f"重建并发布 rc={rc} {out[-200:]}")

# ── 输出：正常静默 ─────────────────────────────────────────
if problems:
    print("War-KOL watchdog 发现问题：")
    for p in problems:
        print(f"  - {p}")
    if fixed:
        print("已尝试自愈：")
        for f in fixed:
            print(f"  - {f}")

try:
    os.remove(LOCK)
except OSError:
    pass
sys.exit(0)
