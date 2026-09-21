#!/usr/bin/env bash
# War-KOL 每日链式驱动：等 fetch 结束 → enrich_dates → extract_thesis → notion → publish
# 每步写独立状态文件，便于 agent 轮询判断进度与失败点。
set -u
cd /home/user/Projects/War-KOL
D=$(date +%Y-%m-%d)
ST=logs/chain_${D}.status

# ★ 本机实测：数小时级后台任务会被外部整组收割（日志戛然而止、无报错）。
#   对策 = crontab 每 5 分钟拉起 + flock 单实例互斥 + 每步可重入。
#   重入安全性：enrich 只填空、extract_thesis 增量跳过已抽、notion 幂等 upsert、
#   publish 由 finalize.lock + 日哨兵去重。所以整脚本重跑不会重复消耗或写坏。
mkdir -p logs scratch
exec 8> scratch/daily_chain.lock
flock -n 8 || exit 0          # 上一实例还在跑

echo "[$(date +%H:%M:%S)] CHAIN_START pid=$$" >> "$ST"
[ -f "scratch/.chain_done_${D}" ] && { echo "already done" >> "$ST"; exit 0; }

note() { echo "[$(date +%H:%M:%S)] $*" >> "$ST"; }

# --- 等待 fetch 结束；若 fetch 已死且产物未落盘，自动重启 fetch ---
note "WAIT_FETCH begin"
if ! pgrep -f "fetch_statements.py" > /dev/null && [ ! -f "data/statements/daily_${D}.json" ]; then
  note "fetch 不在跑且无产物 → 重启 fetch"
  python3 scripts/fetch_statements.py --mode daily --days 3 >> "logs/fetch_${D}.log" 2>&1
  note "FETCH exit=$?"
fi
while pgrep -f "fetch_statements.py" > /dev/null; do sleep 30; done
note "WAIT_FETCH done"

if [ ! -f "data/statements/daily_${D}.json" ]; then
  note "FATAL no daily_${D}.json"
  exit 1
fi

# --- 步骤 1.2 覆盖率闸（Chao 2026-09-14 拍板）---
# ★ 病根：上面两个条件（进程不在跑 + 产物存在）只回答「fetch 跑过没」，
#   从不回答「抓全了没」。2026-09-14 实际翻车：01:10 selfheal 遇 ddgs 大面积
#   ConnectTimeout，62 人只抓出 27 人，但文件存在、进程已退 → 链子照常走完
#   → 01:54 落下 .chain_done 哨兵 → 之后每 5 分钟起来全部 "already done"
#   直接退出，整天锁死在残缺数据上，而系统认为自己今天已干完活。
#
#   这与 2026-09-10「凌晨发了昨天数据」是同一个病的两种表现：
#   用「做过了」代替「做对了」。发布端已改内容指纹治好了后半段，
#   fetch 端这里仍是布尔判断，现在补上。
#
# 阈值依据（实测，非拍脑袋）：09-02 至 09-13 共 12 天覆盖率为
#   62/62 ×11 天、61/62 ×1 天，从未低于 61（98%）。取 90% 留足余量，
#   容得下个别 KOL 当天真的没有新言论。
#
# ★ 逃生阀：若某天真有大批 KOL 全天无言论，不能卡成永不发布。
#   超过 MAX_WAIT_H 小时仍不达标 → 放行，但写 DEGRADED 标记，
#   下游日报据此如实标注覆盖率不足，宁可发残缺+标注，不要静默停更。
COV_RATIO=0.90
MAX_WAIT_H=6
COVSTATE="scratch/.coverage_wait_${D}"

COV=$(python3 - "$D" <<'EOF'
import json, sys, os
d = sys.argv[1]
try:
    roster = json.load(open("data/kol_registry.json", encoding="utf-8"))
    active = sum(1 for k in roster if k.get("active", True))
    recs = json.load(open(f"data/statements/daily_{d}.json", encoding="utf-8"))
    got = len({r.get("kol") for r in recs if r.get("kol")})
    print(f"{got} {active}")
except Exception as e:
    print(f"ERR {e}", file=sys.stderr)
    print("0 0")
EOF
)
COV_GOT=${COV%% *}
COV_ACTIVE=${COV##* }

if [ "$COV_ACTIVE" -gt 0 ]; then
  NEED=$(python3 -c "import math;print(math.ceil($COV_ACTIVE*$COV_RATIO))")
  if [ "$COV_GOT" -lt "$NEED" ]; then
    # 记录首次不达标时刻，用于逃生阀计时
    [ -f "$COVSTATE" ] || date +%s > "$COVSTATE"
    WAITED=$(( ( $(date +%s) - $(cat "$COVSTATE") ) / 3600 ))
    if [ "$WAITED" -lt "$MAX_WAIT_H" ]; then
      note "COVERAGE_GATE 拦截: ${COV_GOT}/${COV_ACTIVE} < ${NEED} (已等 ${WAITED}h/${MAX_WAIT_H}h) → 不落哨兵不发布，下轮重试 fetch"
      # ★ 关键：不 touch .chain_done，让下一轮 5 分钟后重入。
      #   fetch 是按 KOL 续跑的（已抓到的留在文件里），重试只补缺不重来。
      exit 0
    fi
    note "COVERAGE_GATE 逃生阀放行: ${COV_GOT}/${COV_ACTIVE} 已等 ${WAITED}h ≥ ${MAX_WAIT_H}h → 降级发布并标注"
    echo "${COV_GOT}/${COV_ACTIVE}" > "scratch/.coverage_degraded_${D}"
  else
    note "COVERAGE_GATE 通过: ${COV_GOT}/${COV_ACTIVE} ≥ ${NEED}"
    rm -f "$COVSTATE"
  fi
else
  note "COVERAGE_GATE 跳过（名册读取失败，不阻塞管道）"
fi

# --- 步骤 1.5 回补发表日 ---
# ★ 必须与 scripts/enrich_extra.sh 互斥：两个 enrich 同时写同一个
#   daily_<date>.json 会把文件写截断/损坏。共用同一把锁串行化。
note "ENRICH begin"
exec 7> scratch/enrich_extra.lock
flock -w 3600 7
python3 scripts/enrich_dates.py --file "daily_${D}.json" --fetch-pages --limit-fetch 400 \
  >> "logs/enrich_${D}.log" 2>&1
note "ENRICH exit=$?"
flock -u 7

# --- 步骤 2 五要素抽取 ---
note "THESIS begin"
python3 scripts/extract_thesis.py --all --workers 8 > "logs/thesis_${D}.log" 2>&1
note "THESIS exit=$?"

# 保险：把 statements 的发表日回填进 thesis（只填空不覆盖）
python3 scripts/propagate_dates_to_thesis.py >> "logs/enrich_${D}.log" 2>&1
note "PROPAGATE exit=$?"

# --- 步骤 3 写 Notion ---
note "NOTION begin"
python3 scripts/write_statements_to_notion.py > "logs/notion_${D}.log" 2>&1
note "NOTION exit=$?"

# --- 步骤 4 dashboard + 双端发布 ---
# ★ crontab 里 finalize_watchdog.sh 每 10 分钟也会做 rescore→build→publish。
#   两边同时 publish 会撞 git（并发 commit/push），所以复用同一把 finalize.lock。
# ★ 2026-09-10 Chao 拍板：去重改为「内容指纹」，不再用 .finalized_<date>。
#   旧日期哨兵让「凌晨发了昨天数据」把当天成果永久挡掉（详见
#   scripts/publish_fingerprint.sh 抬头）。现在只问：线上是不是当前数据做的。
FPFILE="scratch/.published_fingerprint"
mkdir -p scratch
exec 9> scratch/finalize.lock
if flock -w 1800 9; then
  FP=$(bash scripts/publish_fingerprint.sh 2>/dev/null || echo ERR)
  if [ "$FP" = "ERR" ] || [ "$FP" = "EMPTY" ]; then
    note "PUBLISH skipped (指纹不可用: $FP)"
  elif [ "$FP" = "$(cat "$FPFILE" 2>/dev/null)" ]; then
    note "PUBLISH skipped (线上已是当前数据 $FP)"
  else
    note "PUBLISH begin (指纹 $FP)"
    python3 scripts/rescore_kols.py --apply   >  "logs/publish_${D}.log" 2>&1
    note "RESCORE exit=$?"
    bash scripts/publish.sh                   >> "logs/publish_${D}.log" 2>&1
    rc=$?
    note "PUBLISH exit=$rc"
    # 记录发布前那一刻的 FP，不重算（期间数据若又变，下轮会再发）
    [ "$rc" = "0" ] && echo "$FP" > "$FPFILE"
  fi
  flock -u 9
else
  note "PUBLISH skipped (拿不到 finalize.lock)"
fi

note "CHAIN_COMPLETE"
touch "scratch/.chain_done_${D}"
