#!/usr/bin/env python3
"""War-KOL 接手自检（只读，不改任何东西，不调用任何 LLM，不联网写入）。

用法（在项目根目录）：
    python3 ops/handover_check.py

它回答接手者最需要的 8 个问题，每项给 [OK] / [WARN] / [FAIL] 与一句原因：
  1. 项目根与关键文件在不在
  2. 原文缓存在不在（缺它跑 build_layers --all 会洗空译文，见 HANDOVER §8）
  3. 名册数 / 星级分布 / 在册但 0 言论
  4. 五个 Hermes cron 的启停状态与模型
  5. 系统 crontab 里有没有数据管线
  6. 今天的 chain 走到哪一步
  7. 本地看板与线上 md5 是否一致
  8. 受跟踪文件里有没有内网标识 / 凭证形态

退出码：有 FAIL 返回 1，否则 0。
"""
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import Counter
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")
OK, WARN, FAIL = "[OK]  ", "[WARN]", "[FAIL]"
fails = 0
warns = 0


def say(level, msg):
    global fails, warns
    if level == FAIL:
        fails += 1
    elif level == WARN:
        warns += 1
    print(f"{level} {msg}")


def run(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, timeout=timeout)
        return (r.stdout + r.stderr).decode("utf-8", "replace").strip()
    except Exception as e:  # noqa: BLE001
        return f"ERR {type(e).__name__}"


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


print(f"== War-KOL 接手自检  {date.today()}  根目录={ROOT} ==\n")

# 1 关键文件 ----------------------------------------------------------------
print("-- 1. 关键文件")
need = ["HANDOVER.md", "SETUP.md", "ops/cron-jobs.json", "scripts/daily_chain.sh",
        "scripts/build_dashboard.py", "scripts/publish.sh", "data/kol_registry.json"]
for p in need:
    say(OK if os.path.exists(os.path.join(ROOT, p)) else FAIL, p)
for p, why in [("data/notion_ids.json", "Notion 库 id（gitignored，向 Chao 要）"),
               (".env", "凭证（gitignored，见 SETUP.md §0）")]:
    say(OK if os.path.exists(os.path.join(ROOT, p)) else WARN, f"{p} — {why}")
gate = os.path.join(HOME, ".hermes/scripts/public_push_gate.sh")
say(OK if os.path.exists(gate) else WARN,
    "~/.hermes/scripts/public_push_gate.sh — publish.sh 调用它；不在仓库里，换机器要另拷")

# 2 原文缓存 ----------------------------------------------------------------
print("\n-- 2. 原文缓存（全新克隆陷阱）")
bc = os.path.join(ROOT, "data/thesis/_body_cache_all.json")
if os.path.exists(bc):
    sz = os.path.getsize(bc) // 1024 // 1024
    say(OK, f"_body_cache_all.json 存在（{sz}MB）")
else:
    say(FAIL, "缺 data/thesis/_body_cache_all.json —— 此时运行 `build_layers.py --all` 会把已有译文/总结覆盖成空"
              "（隔离副本实测洗空 1203 条）。先从原机拷过来；在此之前不要运行它，也别让 layers_watchdog 拉起它。")

# 3 名册 --------------------------------------------------------------------
print("\n-- 3. 名册与言论")
reg = load(os.path.join(ROOT, "data/kol_registry.json"), [])
act = [k for k in reg if k.get("active", True)]
star = Counter(k.get("rating") for k in act)
say(OK if act else FAIL, f"名册 active {len(act)} 人；星级 {dict(star)}")
if len(act) > 60:
    say(WARN, f"超过 60 人上限（{len(act)}），不要自行删人，等 Chao 定")
quals = {}
for f in glob.glob(os.path.join(ROOT, "data/thesis/thesis_*.json")):
    for r in load(f, []):
        if isinstance(r, dict) and r.get("kol") and r.get("source_url"):
            quals[(r["kol"], r["source_url"])] = r
say(OK if quals else FAIL, f"合格言论 {len(quals)} 条（去重）；有发表日 {sum(1 for r in quals.values() if r.get('published_on'))} 条")
have = {k for k, _ in quals}
zero = [k["name_en"] for k in act if k["name_en"] not in have]
say(OK if not zero else WARN, f"在册但 0 言论：{zero or '无'}（监测对象 tier=monitor 属正常）")
below = [(k["name_en"], k.get("rating"), k.get("weighted_score")) for k in act if k.get("rating") in ("1★", "2★")]
say(OK if not below else WARN, f"低于 3★ 的在册者 {len(below)} 位（不自动移出，名册增删归 Chao）")

# 4 Hermes cron --------------------------------------------------------------
print("\n-- 4. Hermes cron（~/.hermes/cron/jobs.json）")
J = load(os.path.join(HOME, ".hermes/cron/jobs.json"))
if J is None:
    say(WARN, "读不到 ~/.hermes/cron/jobs.json（不是 Hermes 机器？）")
else:
    jobs = J["jobs"] if isinstance(J, dict) and "jobs" in J else J
    mine = [j for j in jobs if "War-KOL" in (j.get("workdir") or "") or "war-kol" in (j.get("name") or "").lower()
            or "war_kol" in (j.get("script") or "")]
    want = {"war-kol-daily", "war-kol-weekly", "war-kol-monthly", "war-kol-selfheal", "war-kol-context-distill"}
    got = {j["name"] for j in mine}
    say(OK if want <= got else FAIL, f"5 个 job {'齐全' if want <= got else '缺：' + str(sorted(want - got))}")
    for j in sorted(mine, key=lambda x: x["name"]):
        en = j.get("enabled", True)
        model = j.get("model") or ("(no_agent)" if j.get("no_agent") else "(默认)")
        flag = "在跑" if en else "暂停"
        lvl = OK
        if j["name"] == "war-kol-daily" and not en:
            flag += "（2026-10-30 Chao 要求停；恢复前别擅自启用）"
        if (not j.get("no_agent")) and "opus" in str(model).lower():
            lvl = WARN
            flag += " ← 用了 opus，应为 sonnet-5-5"
        say(lvl, f"{j['name']:26s} {flag:8s} model={model}")

# 5 系统 crontab -------------------------------------------------------------
print("\n-- 5. 系统 crontab（数据管线，不在 jobs.json 里）")
ct = run("crontab -l 2>/dev/null")
for name in ["daily_chain.sh", "layers_watchdog.sh", "finalize_watchdog.sh"]:
    lines = [l for l in ct.split("\n") if name in l]
    live = [l for l in lines if not l.strip().startswith("#")]
    if live:
        say(WARN, f"{name} 在跑（2026-10-30 Chao 已批准整条管线停；若不是你恢复的，先问 Chao）")
    elif lines:
        say(OK, f"{name} 已被注释停用（预期状态；恢复见 HANDOVER §12.2）")
    else:
        say(WARN, f"{name} 不在 crontab（SETUP.md §3 有恢复行）")
if "delivery_fallback.sh" not in ct:
    say(OK, "delivery_fallback.sh 未调度（日报已停，属预期）")

# 5b 发布配置文件（publish.sh 读它；缺则静默跳过内网同步）
cfgp = os.path.join(HOME, ".hermes/war_kol_publish.env")
say(OK if os.path.exists(cfgp) else WARN,
    "~/.hermes/war_kol_publish.env 存在" if os.path.exists(cfgp)
    else "缺 ~/.hermes/war_kol_publish.env —— 换机器要自建，否则 publish.sh 会静默跳过内网同步（HANDOVER §12.3）")

# 6 今日 chain ---------------------------------------------------------------
print("\n-- 6. 今日 chain")
st = os.path.join(ROOT, f"logs/chain_{date.today()}.status")
if os.path.exists(st):
    lines = [l for l in open(st, encoding="utf-8").read().split("\n") if l and "already done" not in l and "CHAIN_START" not in l]
    last = lines[-1] if lines else "(空)"
    say(OK, f"最后一步：{last}")
else:
    say(WARN, f"今天还没有 {os.path.basename(st)}（00:00 起才会生成；或 chain 被停）")

# 7 看板 md5 ----------------------------------------------------------------
print("\n-- 7. 看板 md5（本地 vs 线上）")
idx = os.path.join(ROOT, "index.html")
if os.path.exists(idx):
    loc = hashlib.md5(open(idx, "rb").read()).hexdigest()[:12]
    try:
        req = urllib.request.Request("https://war-kol.pages.dev/", headers={"User-Agent": "Mozilla/5.0"})
        live = hashlib.md5(urllib.request.urlopen(req, timeout=60).read()).hexdigest()[:12]
        say(OK if live == loc else WARN, f"本地 {loc} / 线上 {live}" + ("" if live == loc else "（不一致：可能刚重建未发布，或 CDN 缓存，等 60–90 秒复验）"))
    except Exception as e:  # noqa: BLE001
        say(WARN, f"线上读取失败 {type(e).__name__}（本机网络？）；本地 {loc}")
else:
    say(WARN, "无本地 index.html")

# 8 受跟踪文件的内部标识 -----------------------------------------------------
print("\n-- 8. 受跟踪文件里的内部标识 / 凭证形态（公网仓库不能有）")
_J = lambda *a: "".join(a)
_W = [_J("code\\.uber\\.", "internal"), _J("uber", "internal"), _J("vibe", "-mcp"), r"\bpresto\b",
      _J("chao", r"\.jin"), _J("hermes", "chao"), _J("Chao", "Projects"), _J(r"\.cert", "env"), r"\bussh\b",
      _J("ntn", "_[A-Za-z0-9]{15}"), _J("secret", "_[A-Za-z0-9]{15}"), _J("bot", "[0-9]{8,}:")]
pat = "|".join(_W)
# publish*.sh / rebuild 脚本本身含红线正则字面量，排除（与 publish.sh 的口径一致）
files = run("git ls-files -- scripts ops SETUP.md HANDOVER.md README.md self-skill | grep -vE 'publish.*\\.sh|rebuild_public_repo|handover_check\\.py'").split("\n")
hits = []
for f in files:
    p = os.path.join(ROOT, f)
    if not f or not os.path.isfile(p):
        continue
    try:
        for i, l in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
            if re.search(pat, l, re.I):
                hits.append(f"{f}:{i}")
    except Exception:
        pass
say(OK if not hits else FAIL, "0 命中" if not hits else f"{len(hits)} 处命中：{hits[:6]}")
_K = _J("Chao", "Projects") + "|" + _J(r"\\.cert", "env")
pub = run(f"git show origin/main:scripts/publish.sh 2>/dev/null | grep -nE '{_K}' | head -3")
# 第 46 行是 publish.sh 自己的红线扫描正则（本来就含这些词，公网版也有），按「含 grep -rniE」排除
loc = run(f"grep -nE '{_K}' scripts/publish.sh | grep -v 'grep -rniE' | head -3")
if loc:
    say(FAIL, f"本地 publish.sh 含内网路径或证书环境文件的字面量：{loc[:80]} —— 推公网会带出去（HANDOVER §7.2）")

print(f"\n== 汇总：FAIL {fails}  WARN {warns} ==")
sys.exit(1 if fails else 0)
