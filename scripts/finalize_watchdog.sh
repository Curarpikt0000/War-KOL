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
# ★ 2026-09-10 Chao 拍板：去重从「按日期」改为「按内容指纹」。
#   旧的 scratch/.finalized_<date> 会让「凌晨发了昨天数据」把当天成果永久挡掉
#   （详见 scripts/publish_fingerprint.sh 抬头）。现在只问一句：
#   线上那份，是不是【当前数据】做出来的？不是就发，是就跳过。
FPFILE=scratch/.published_fingerprint

exec 9>"$LOCK" || exit 1
flock -n 9 || exit 0                      # 上一轮还在跑

FP=$(bash scripts/publish_fingerprint.sh 2>/dev/null || echo ERR)
[ "$FP" = "ERR" ] && exit 0               # 指纹算不出来就别乱发
[ "$FP" = "EMPTY" ] && exit 0             # 没有任何数据文件，不发
[ "$FP" = "$(cat "$FPFILE" 2>/dev/null)" ] && exit 0   # 线上已是当前数据

# ── 条件 1：四层是否追平 ──
GAP=$(python3 - <<'EOF' 2>/dev/null || echo 9999
import json, glob, os
# ★ 2026-09-08 踩坑：build_layers.py 按【当天日期】写产物
#   （layers_2026-09-07.json / layers_2026-09-08.json ...），
#   读取时才合并全部。只看单个文件会把跨天续跑的产量算丢，
#   导致缺口永远不为 0 → 收尾永远不触发。必须合并所有 layers_*.json。
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
[ "$GAP" = "0" ] || exit 0

# ── 条件 2：抽取/生成进程都已退出 ──
# ★ 2026-09-08 实测踩坑：pgrep 的 '^python3 -u scripts/xxx.py' 锚定模式
#   在本机匹配不到真实进程（容器 PID 命名空间下 ps -eo 也看不到，
#   但 pgrep -cf 'build_layers' 能返回 1，且日志确实在推进）。
#   用失效模式判活 = 误判成「已退出」→ 会在四层没跑完时提前发布残缺版。
#   ⇒ 改用宽松子串匹配，并【额外用日志时间戳兜底】：
#     只要产物文件 5 分钟内被写过，就认为还在跑，绝不动手。
pgrep -f 'extract_thesis' >/dev/null && exit 0
pgrep -f 'build_layers'   >/dev/null && exit 0

# 双保险：产物 5 分钟内有写入 = 还在跑（防 pgrep 模式再次失效）
FRESH=$(python3 - <<'EOF' 2>/dev/null || echo 1
import os, time, glob
# 看【最新的】那个 layers_*.json（跨天会换文件，见上）
fs = glob.glob('data/layers/layers_*.json')
newest = max((os.path.getmtime(p) for p in fs), default=0)
print(1 if time.time() - newest < 300 else 0)
EOF
)
[ "$FRESH" = "0" ] || exit 0

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

# ★ 记录【发布前那一刻】算出的 FP，不重算：
#   若发布过程中数据又变了（cron 同时在写），重算会把新数据也标成"已发"，
#   那批新内容就永远发不出去——正是这次要修的病，别换个形式再犯一遍。
echo "$FP" > "$FPFILE"
say "✓ 收尾完成（指纹 $FP）。线上已更新，等 Chao 验收。"