#!/usr/bin/env bash
# War-KOL 四层内容生成 · 自愈守护
#
# ★ 背景（2026-09-07 血泪）：build_layers.py 要跑 ~11 小时，
#   本机上【三种】后台方式都保不住它：
#     · terminal(background=true) → EXIT=143 (SIGTERM)，44/521 被杀
#     · tmux new-session -d       → 整个 tmux server 连锅端，13/480 被杀
#     · systemd-run --user        → 容器无 user bus，Failed to connect to bus
#   共同点：日志戛然而止、无报错、内存磁盘都充裕 = 外部整组收割。
#
# 对策：不跟收割机制对抗，改为【被杀了就自动拉起】。
#   build_layers.py 本身是断点续跑的（已生成的会跳过），
#   所以反复重启不会重复烧配额，只损失当前那一条。
#
# 由 crontab 每 5 分钟调一次；已在跑就立刻退出（靠 flock 互斥，不靠 pgrep 猜）。
set -u
cd "$(dirname "$0")/.." || exit 1
LOCK=scratch/layers.lock
LOG=scratch/layers.log

# flock 非阻塞：拿不到锁说明另一个实例在跑，直接退
exec 9>"$LOCK" || exit 1
flock -n 9 || exit 0

# 全部生成完就自我停用（避免空转刷日志）
REMAIN=$(python3 - <<'EOF' 2>/dev/null || echo 1
import json, os, glob
# ★ 2026-09-08：产物按当天日期分文件，必须合并全部再算剩余，
#   否则跨天后会把昨天做完的当成没做（虽然 build_layers 自己会跳过，
#   但这里的判据会永远认为还有剩，守护无法自我停用）。
lay = {}
for p in glob.glob('data/layers/layers_*.json'):
    try:
        lay.update(json.load(open(p)))
    except Exception:
        pass
need = set()
for f in glob.glob('data/thesis/thesis_*.json'):
    try:
        for r in json.load(open(f)):
            if isinstance(r, dict) and r.get('source_url'):
                need.add(r['source_url'])
    except Exception:
        pass
print(len(need - set(lay)))
EOF
)
if [ "$REMAIN" = "0" ]; then
  echo "[$(date '+%F %T')] 四层已全部生成，守护退出" >> "$LOG"
  exit 0
fi

echo "[$(date '+%F %T')] 守护拉起 build_layers（剩 $REMAIN 条）" >> "$LOG"
exec python3 -u scripts/build_layers.py --all >> "$LOG" 2>&1
