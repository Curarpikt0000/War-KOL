#!/usr/bin/env bash
# War-KOL 四层完成后的自动收尾（Chao 2026-09-08 选「乙：等全量」）
#
# ★ 为什么要这个脚本：
#   Chao 选了「等四层全量跑完再发布」，预计今晚 ~23:20。
#   但 agent 的 turn 只由用户消息驱动——我不会在 23:20 自动醒来。
#   四层生成本身是 daemon（layers_watchdog.sh 兜底会自己跑完），
#   可后面的「重新打分 → 重建 dashboard → 发布」如果只等我，
#   Chao 明早看到的会是「数据齐了但线上还是旧版」。
#   ⇒ 把收尾也做成无人值守的，由 crontab 每 10 分钟探一次。
#
# 触发条件（三个都满足才动手）：
#   1. 四层已追平（缺口 = 0）
#   2. cron 的五要素抽取已结束（没有 extract_thesis 进程）
#   3. 本轮尚未收尾过（哨兵文件不存在）
#
# 动作：rescore_kols.py --apply → build_dashboard.py → publish.sh
# 每步失败都留痕并中止，不硬着头皮往下走。
set -u
cd "$(dirname "$0")/.." || exit 1

LOCK=scratch/finalize.lock
LOG=scratch/finalize.log
SENTINEL=scratch/.finalized_$(date +%F)

exec 9>"$LOCK" || exit 1
flock -n 9 || exit 0                      # 上一轮还在跑

[ -f "$SENTINEL" ] && exit 0              # 今天已收尾

# ── 条件 1：四层是否追平 ──
GAP=$(python3 - <<'EOF' 2>/dev/null || echo 9999
import json, glob, os
p = 'data/layers/layers_2026-09-07.json'
lay = json.load(open(p)) if os.path.exists(p) else {}
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
[ "$GAP" = "0" ] || exit 0

# ── 条件 2：抽取/生成进程都已退出 ──
pgrep -f '^python3 -u scripts/extract_thesis.py' >/dev/null && exit 0
pgrep -f '^python3 -u scripts/build_layers.py'   >/dev/null && exit 0

say() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }
say "════ 四层已追平（缺口 0），开始自动收尾 ════"

# 1) 重新打分（C 维度只认已到期预测；新入库言论会让更多人脱离「监测中」）
say "① rescore_kols.py --apply"
if ! python3 -u scripts/rescore_kols.py --apply >> "$LOG" 2>&1; then
  say "✗ 打分失败，中止（不发布半成品）"; exit 1
fi

# 2) 重建 dashboard
say "② build_dashboard.py"
if ! python3 -u scripts/build_dashboard.py >> "$LOG" 2>&1; then
  say "✗ 构建失败，中止"; exit 1
fi

# 3) 四层渲染自检：产物里必须真有四层结构，别发个空壳上去
say "③ 渲染自检"
python3 - >> "$LOG" 2>&1 <<'EOF' || { echo "✗ 自检未通过"; exit 1; }
import re, sys
h = open('dashboard/index.html', encoding='utf-8').read()
checks = {
    'layerBody 渲染器': h.count('function layerBody') == 1,
    '四层折叠钮': h.count('data-ly=') > 0 or 'ly-btn' in h,
    '一句话层': 'ly-one' in h,
    'STMTS 20 字段': bool(re.search(r'var STMTS', h)),
}
bad = [k for k, v in checks.items() if not v]
print('渲染自检:', '全部通过' if not bad else f'未通过 {bad}')
sys.exit(1 if bad else 0)
EOF

# 4) 发布（publish.sh 自带红线扫描 + 双端 push + remote 读回）
say "④ publish.sh"
if ! bash scripts/publish.sh >> "$LOG" 2>&1; then
  say "✗ 发布失败（多半是红线扫描拦截，看上面日志）"; exit 1
fi

touch "$SENTINEL"
say "✓ 收尾完成。线上已更新，等 Chao 验收。"
