#!/bin/bash
# War-KOL 发布：镜像名册 → 建 dashboard → IP 红线扫描 → 双端 push。
# 幂等：无变更则静默跳过 push。供每日 cron 末尾调用。
#
# ⚠️ Pages 入口是【根目录 index.html】，不是 dashboard/index.html —— 本脚本负责 cp。
#    手动 commit 会漏掉这一步 → 本地重建了但公网没变（Forecast-Checker 实际踩过）。
# ⚠️ 红线扫描清单必须与下面 git add 清单【保持同步】。只加 git add 而忘了加扫描
#    = 让新文件绕过安全门（Forecast-Checker 2026-08-24 踩过）。
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
PY="python3"

# 1. 重建 dashboard（名册镜像由 cron 步骤 0 单独跑，这里不重复）
$PY scripts/build_dashboard.py || { echo "build 失败"; exit 1; }
cp dashboard/index.html index.html

# 2. IP 红线扫描（个人端安全）—— 清单与第 3 步 git add 同步
# ⚠️ AGENTS.md 不进公网：内含内网 monorepo 路径与双端同步架构，属内部信息。
#    它只随 rsync 进内部端。公网侧用 README.md 说明项目。
SCAN_FILES=(
  README.md index.html dashboard/index.html
  scripts/build_dashboard.py scripts/world_map.py scripts/fetch_statements.py
  scripts/attribution.py scripts/merge_raw.py scripts/select_roster.py
  scripts/compute_ratings.py scripts/sync_kol_from_notion.py
  scripts/translate.py scripts/stance_tracker.py scripts/purge_homonyms.py
  scripts/revalidate_attribution.py scripts/enrich_dates.py
  scripts/extract_thesis.py
  scripts/weekly_rollup.py scripts/write_weekly_to_notion.py
  scripts/propagate_dates_to_thesis.py scripts/patch_daily_cron_prompt.py
  docs/HANDOVER.md docs/PENDING_AGENTS_MD_UPDATE.md
  data/kol_registry.json data/roster_final.json
  data/candidates_rejected.json data/candidates_raw.json
  data/translations.json data/stance_changes.json
  data/weekly/*.json
  data/removed_attribution_*.json data/removed_homonym_*.json
  data/removed_directory_*.json data/removed_nobody_*.json
  data/removed_no_thesis_*.json
)
# ⚠️ presto 必须带词边界 \b：2026-09-05 实测被播客主持人姓氏「Preston」误伤，
#    中止了整次 push。放宽关键词是危险的，加边界不是——它只是不再匹配单词内部。
if grep -rniE "code\.uber\.internal|uberinternal|\baifx\b|\bpresto\b|chao\.jin|hermeschao|ChaoProjects|ntn_[A-Za-z0-9]{15}|secret_[A-Za-z0-9]{15}" \
   "${SCAN_FILES[@]}" data/statements/*.json 2>/dev/null | grep -v notion_ids; then
  echo "RED-LINE HIT — 中止个人端 push"; exit 2
fi

# 3. 个人端 push（公网）
git add "${SCAN_FILES[@]}" 2>/dev/null
git add -A data/statements/ 2>/dev/null
# 归属/同名清理留痕：删了就查不到「为什么这条消失了」
git add -A data/removed_attribution_*.json data/removed_homonym_*.json 2>/dev/null
# 方向快照：删了就没法算立场转向，必须进版本库
git add -A data/stance/ 2>/dev/null
# 五要素抽取产物：dashboard 的 L2 内容全靠它，不进库线上就空
git add -A data/thesis/ 2>/dev/null
# 周度汇总产物：周报/月报的输入，删了就没法回溯当周口径
git add -A data/weekly/ 2>/dev/null
if ! git diff --cached --quiet; then
  if ! git -c commit.gpgsign=false commit -q -m "Daily update: refresh war KOL statements and dashboard $(date +%F)"; then
    echo "个人端 commit 失败 — 重试一次"
    git -c commit.gpgsign=false commit -q -m "Daily update: refresh war KOL statements and dashboard $(date +%F)" || {
      echo "个人端 commit 仍失败 — 未 push"; exit 3; }
  fi
  git push -q origin main 2>&1 | grep -vE "duplicate proto" || true
  # 读回 remote 校验，避免假阳性
  if [ "$(git rev-parse HEAD)" = "$(git ls-remote origin HEAD 2>/dev/null | awk '{print $1}')" ]; then
    echo "个人端已 push"
  else
    echo "个人端 push 未生效 — remote HEAD 与本地不一致"; exit 4
  fi
else
  echo "个人端无变更"
fi

# 4. 内部端同步（monorepo 子目录）
INT="$HOME/Projects/ChaoProjects"
if [ -d "$INT/.git" ]; then
  rsync -a --delete --exclude='.git/' --exclude='.venv/' --exclude='scratch/' \
        --exclude='__pycache__/' --exclude='.env' --exclude='.secrets/' \
        "$ROOT/" "$INT/War-KOL/"
  cd "$INT" || exit 1
  git add War-KOL/ 2>/dev/null
  git add -f War-KOL/data/notion_ids.json 2>/dev/null
  if ! git diff --cached --quiet War-KOL/ 2>/dev/null; then
    git -c commit.gpgsign=false commit War-KOL/ -q -m "War-KOL daily update $(date +%F)" 2>&1 | grep -vE "duplicate proto" || true
    if [ -f "$HOME/.certenv" ]; then
      source "$HOME/.certenv" 2>/dev/null
      git push origin HEAD 2>&1 | grep -vE "duplicate proto|Found cert|session_id|username" | tail -2 || true
      echo "内部端已 push"
    fi
  else
    echo "内部端无变更"
  fi
fi
echo "publish 完成"
