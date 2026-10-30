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
  # ⚠️ publish_cloudflare.sh 与 publish.sh 【故意不列入扫描】：
  #    这两个文件本身就含红线关键词的正则字面量，扫自己必然自伤，
  #    会把整条发布链永久卡死。它们仍会被下面的 git add 单独收进版本库。
  docs/HANDOVER.md docs/PENDING_AGENTS_MD_UPDATE.md
  data/kol_registry.json data/roster_final.json
  data/candidates_rejected.json data/candidates_raw.json
  data/translations.json data/stance_changes.json
  data/weekly/*.json
  data/removed_attribution_*.json data/removed_homonym_*.json
  data/removed_directory_*.json data/removed_nobody_*.json
  data/removed_no_thesis_*.json
  data/layers/*.json
)
# ⚠️ 下方内部技术栈关键词必须带词边界 \b：2026-09-05 实测被播客主持人姓氏「Preston」误伤，
#    中止了整次 push。放宽关键词是危险的，加边界不是——它只是不再匹配单词内部。
if grep -rniE "code\.uber\.internal|uberinternal|\baifx\b|\bpresto\b|chao\.jin|hermeschao|ChaoProjects|ntn_[A-Za-z0-9]{15}|secret_[A-Za-z0-9]{15}" \
   "${SCAN_FILES[@]}" data/statements/*.json 2>/dev/null | grep -v notion_ids; then
  echo "RED-LINE HIT — 中止个人端 push"; exit 2
fi

# 3. 个人端 push（公网）
git add "${SCAN_FILES[@]}" 2>/dev/null
# 发布脚本自身：不进扫描清单（会自伤，见上），但必须进版本库
git add scripts/publish.sh scripts/publish_cloudflare.sh .gitignore 2>/dev/null
git add -A data/statements/ 2>/dev/null
# 归属/同名清理留痕：删了就查不到「为什么这条消失了」
git add -A data/removed_attribution_*.json data/removed_homonym_*.json 2>/dev/null
# 方向快照：删了就没法算立场转向，必须进版本库
git add -A data/stance/ 2>/dev/null
# 五要素抽取产物：dashboard 的 L2 内容全靠它，不进库线上就空
git add -A data/thesis/ 2>/dev/null
# 四层内容产物：一句话/总结/原文翻译，dashboard 的 L1-L3 全靠它
git add -A data/layers/ 2>/dev/null
# 周度汇总产物：周报/月报的输入，删了就没法回溯当周口径
git add -A data/weekly/ 2>/dev/null
if ! git diff --cached --quiet; then
  if ! git -c commit.gpgsign=false commit -q -m "Daily update: refresh war KOL statements and dashboard $(date +%F)"; then
    echo "个人端 commit 失败 — 重试一次"
    git -c commit.gpgsign=false commit -q -m "Daily update: refresh war KOL statements and dashboard $(date +%F)" || {
      echo "个人端 commit 仍失败 — 未 push"; exit 3; }
  fi
fi
# ★2026-10-30: 公网 GitHub 改为每两周推一次(提交仍每天做; 内网 / 内网 vibe / Cloudflare 不受影响)。
#   闸在 ~/.hermes/scripts/public_push_gate.sh; 推送失败不再中断后面的内网同步与发布, 只在脚本末尾返回失败码。
PUB_RC=0
bash "$HOME/.hermes/scripts/public_push_gate.sh" push war-kol "$ROOT" main || PUB_RC=$?
[ "$PUB_RC" -ne 0 ] && echo "⚠ 公网 GitHub 推送异常 rc=$PUB_RC(内网与 Cloudflare 照常发布)"
cd "$ROOT" || exit 1

# 4. 内网 monorepo 同步（子目录 War-KOL/）—— 内网每天同步, 不受公网两周闸影响
# ★2026-10-30 重写: 原先依赖环境变量 WARKOL_INTERNAL_MONOREPO, 该变量没有设置处,
#   内网同步自 09-14 起停摆(内网副本最新文件停在 10-01)。现改为与 Science-KOL 相同的固定路径。
# data/thesis/_body_cache_all.json(~77MB, 可再生缓存, 公网 .gitignore 也排除)不进内网;
#   --delete 不会删除被排除的文件, 内网里已有的旧版原样保留。
# 内网 monorepo 的本机路径只从环境变量读取，不在公网脚本里写任何字面量。
#   WARKOL_MONO 的设置位置与默认值见内网补充文件（只在内网 repo）。
#   两个变量任一已设置即可；都未设置则跳过内网同步（不报错）。
# 本机路径配置（不在仓库里；换机器要自己建，见 HANDOVER 第 12.3 节）
[ -f "$HOME/.hermes/war_kol_publish.env" ] && . "$HOME/.hermes/war_kol_publish.env"
MONO="${WARKOL_MONO:-${WARKOL_INTERNAL_MONOREPO:-}}"
if [ -n "$MONO" ] && [ -d "$MONO/.git" ]; then
  mkdir -p "$MONO/War-KOL"
  rsync -a --delete --exclude='.git/' --exclude='.venv*/' --exclude='scratch/' \
        --exclude='__pycache__/' --exclude='.env' --exclude='.secrets/' --exclude='node_modules/' \
        --exclude='data/thesis/_body_cache_all.json' \
        "$ROOT/" "$MONO/War-KOL/"
  cd "$MONO" || exit 1
  BRANCH=$(git rev-parse --abbrev-ref HEAD)   # 不硬编码 main: 内网 monorepo 常在特性分支上
  git add War-KOL/ 2>/dev/null
  git add -f War-KOL/data/notion_ids.json 2>/dev/null
  if ! git diff --cached --quiet -- War-KOL/ 2>/dev/null; then
    # pathspec 限定 War-KOL/: 不把别的 agent 暂存在同一仓库里的东西卷进来
    if git -c commit.gpgsign=false commit -q -m "War-KOL daily update $(date +%F)" -- War-KOL/ 2>&1 | grep -vE "duplicate proto"; [ "${PIPESTATUS[0]}" -eq 0 ]; then
      [ -n "${WARKOL_CERT_ENV:-}" ] && [ -f "$WARKOL_CERT_ENV" ] && source "$WARKOL_CERT_ENV" 2>/dev/null
      PUSH_OUT=$(git push -q origin "HEAD:$BRANCH" 2>&1); PRC=$?
      if [ "$PRC" -eq 0 ]; then echo "内网 monorepo 已同步 (分支 $BRANCH)"
      else echo "内网 monorepo push 失败 rc=$PRC (commit 已在本地): $(echo "$PUSH_OUT" | grep -vE 'duplicate proto|Found cert|session_id|username' | tail -2)"; fi
    else
      echo "内网 monorepo commit 失败"
    fi
  else
    echo "内网 monorepo 无变更"
  fi
else
  echo "内网 monorepo 未配置或路径不存在, 跳过内网同步"
fi
# 5. 内网 vibe 镜像（Chao 2026-09-19：公网打不开时的替代入口）
#    幂等——产物没变就秒退不重传；失败也永不连累公网发布（自身恒 exit 0）。
#    地址见内网脚本 publish_vibe_mirror.sh（该文件不进公网 repo）
#
# ⚠️ 2026-09-20 回归：这里原本写相对路径 `scripts/publish_vibe_mirror.sh`，
#    但上面第 4 步 `cd "$INT"` 切进了内网 monorepo【且没切回】，
#    于是首次随 publish.sh 实跑时报 `No such file or directory`（rc=127），
#    内网镜像整天没同步、台账停在前一天。单测脚本本身通过 ≠ 在宿主流程里通过。
#    ⇒ 一律用 $ROOT 绝对路径，并显式切回。
cd "$ROOT" || exit 1
bash "$ROOT/scripts/publish_vibe_mirror.sh" || true

# 6. 公网 Cloudflare Pages（★ 2026-09-25 补上的真正公网入口）
#    GitHub Pages 已死：Curarpikt0000 账号被封，curarpikt0000.github.io/War-KOL/
#    实测返回 404。git push 仍会成功（仓库还在），但【push 成功 ≠ 公网看得到】。
#    Cloudflare 那份此前靠手工传，停在 09-19 五天没动，日报却一直贴 Pages 链接。
#    ⇒ 固化进流程，幂等（线上 md5 相同就跳过），失败不连累已完成的 git push。
cd "$ROOT" || exit 1
bash "$ROOT/scripts/publish_cloudflare.sh" || echo "⚠ Cloudflare 发布未成功（详见 scratch/cloudflare.log）"

echo "publish 完成"
exit ${PUB_RC:-0}
