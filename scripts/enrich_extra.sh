#!/usr/bin/env bash
# 追加 enrich 轮次：单进程串行，绝不并发（并发写同一 json 会截断损坏）。
# ★ 2026-09-10 实测：--limit-fetch 400 对 2095 条语料形成硬截断，
#   覆盖率卡在 14%（400/1950 页）。多轮串行可把覆盖推到 30%+。
#   每轮只处理仍缺日期的条目，天然增量、可重入。
set -u
cd /home/user/Projects/War-KOL
D=$(date +%Y-%m-%d)
exec 7> scratch/enrich_extra.lock
flock -n 7 || { echo "another enrich running"; exit 0; }
for i in 1 2 3 4; do
  echo "===== 追加轮 $i =====" >> "logs/enrich_${D}.log"
  python3 scripts/enrich_dates.py --file "daily_${D}.json" --fetch-pages --limit-fetch 400 \
    >> "logs/enrich_${D}.log" 2>&1 || break
done
echo "追加 enrich 结束" >> "logs/enrich_${D}.log"
