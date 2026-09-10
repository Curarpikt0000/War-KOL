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
