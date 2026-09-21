#!/usr/bin/env bash
# 发布去重的「内容指纹」——被 finalize_watchdog.sh 与 daily_chain.sh 共用。
#
# ★ 为什么不再用「按日期」的哨兵（Chao 2026-09-10 拍板改）：
#   旧逻辑是 scratch/.finalized_<date>：当天发过一次就不再发。
#   2026-09-10 实际翻车：凌晨 02:31 watchdog 先发了一次（发的是【昨天】的数据），
#   放下当日哨兵；中午 12:01 今天的真数据才抓完；13:02 该发今天的了，
#   系统看见哨兵 → 跳过 → 线上停在昨天，而系统认为自己今天已干过活。
#   门口贴着「今日已送报」，可那是凌晨送的昨天的旧报纸。
#
#   根子在于：日期回答的是「今天发过没」，
#            我们真正要问的是「线上这份，是不是【当前数据】做出来的」。
#
# ⇒ 改为内容指纹：对决定看板内容的数据文件取 mtime+size 汇总哈希。
#   数据没变 → 指纹不变 → 不重发（幂等，防刷 git）
#   数据变新 → 指纹变化 → 立即重发（哪怕今天已经发过 5 次）
#
# 用法：
#   fp="$(bash scripts/publish_fingerprint.sh)"        # 取当前数据指纹
#   记录：echo "$fp" > scratch/.published_fingerprint
#   比对：[ "$fp" = "$(cat scratch/.published_fingerprint 2>/dev/null)" ] && 已是最新
set -u
cd "$(dirname "$0")/.." || exit 1

python3 - <<'EOF'
import glob, hashlib, os

# 只纳入【真正决定看板内容】的数据；日志/锁/缓存不算。
PATTERNS = [
    'data/thesis/thesis_*.json',     # 五要素言论（看板主体）
    'data/layers/layers_*.json',     # 四层内容
]
# ★ 注意：这里【故意不含】data/kol_registry.json。
#   收尾流程第一步就是 rescore_kols.py --apply，它会改写 registry。
#   若把 registry 计入指纹，则「发布 → registry 变 → 指纹变 → 下轮又发」
#   变成每 10 分钟自我触发的死循环（2026-09-10 实测撞到）。
#   registry 是发布的【产物】不是【输入】，看板内容由 thesis + layers 决定。

items = []
for pat in PATTERNS:
    for p in sorted(glob.glob(pat)):
        try:
            st = os.stat(p)
            # mtime 取整到秒 + size：内容变了这两者几乎不可能都不变，
            # 又不必读全量 JSON（thesis 已有几十 MB，每 5 分钟全读太重）。
            items.append(f"{p}:{int(st.st_mtime)}:{st.st_size}")
        except OSError:
            pass

if not items:
    print("EMPTY")
else:
    print(hashlib.sha256("\n".join(items).encode()).hexdigest()[:16])
EOF
