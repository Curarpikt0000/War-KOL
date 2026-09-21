#!/usr/bin/env python3
"""每日方向快照 + 立场变化检测（借鉴 Eco 的 kol_stance_changes / AI-News 的 30 日环比）。

为什么需要：
  目前 dashboard 只有静态快照，看得到「谁现在怎么判断」，看不到「谁改了判断」。
  对战争走势预测，**转向本身就是最强信号**——一个长期说「僵持」的分析师
  突然改口「升级」，比十个一直喊升级的人更值得注意。

做法（刻意做成确定性脚本，不交给 LLM 每天现判，否则结果会随模型状态漂移）：
  1. 每天把「每位 KOL 在每个战区的主导方向」落盘 data/stance/YYYY-MM-DD.json
  2. 对比最近一次与 N 天前的快照，输出转向清单
  3. 快照不足 2 份时返回空并标 reason，**绝不编造转向**（Eco 踩过）

★ 主导方向的口径：取该 KOL 在该战区【最近 30 天内】言论的方向众数，
  排除「未表态」；全是未表态则不计入（不是「他判断中立」，是「没判断」）。
"""
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SNAP_DIR = os.path.join(DATA, "stance")
WINDOW_DAYS = 30       # 主导方向的取样窗口
DIR_RANK = {"降级": -1, "僵持": 0, "升级": 1}


def all_statements():
    d = os.path.join(DATA, "statements")
    if not os.path.isdir(d):
        return []
    recs = []
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".json"):
            try:
                recs.extend(json.load(open(os.path.join(d, fn), encoding="utf-8")))
            except Exception:
                continue
    seen, out = set(), []
    for r in recs:
        k = (r.get("kol"), r.get("source_url"))
        if r.get("status") != "ok" or not r.get("source_url") or k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def compute_stance(stmts, as_of=None):
    """{kol: {theater: {"dir":..., "n":..., "last":...}}}

    只用【已核实发表日】且在窗口内的言论——发表日未知的条目无法定位时间，
    拿它算「当前立场」等于用不知何时的话冒充今天的判断。
    """
    as_of = as_of or date.today()
    cutoff = as_of - timedelta(days=WINDOW_DAYS)
    bag = defaultdict(lambda: defaultdict(list))
    for s in stmts:
        p = s.get("published_on")
        if not p:
            continue
        try:
            d = date.fromisoformat(p)
        except Exception:
            continue
        if not (cutoff <= d <= as_of):
            continue
        dirn = s.get("direction")
        if dirn not in DIR_RANK:      # 排除「未表态」与空值
            continue
        bag[s.get("kol")][s.get("theater") or "未分类"].append((d, dirn))
    out = {}
    for kol, per_t in bag.items():
        out[kol] = {}
        for t, items in per_t.items():
            c = Counter(x[1] for x in items)
            top = c.most_common()
            # 众数并列时取时间最近的那条（最新判断优先）
            if len(top) > 1 and top[0][1] == top[1][1]:
                dirn = max(items, key=lambda x: x[0])[1]
            else:
                dirn = top[0][0]
            out[kol][t] = {"dir": dirn, "n": len(items),
                           "last": max(x[0] for x in items).isoformat()}
    return out


def snap_path(d):
    return os.path.join(SNAP_DIR, f"{d}.json")


def save_snapshot(stance, d=None):
    d = d or date.today()
    os.makedirs(SNAP_DIR, exist_ok=True)
    json.dump({"date": str(d), "window_days": WINDOW_DAYS, "stance": stance},
              open(snap_path(d), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return snap_path(d)


def load_baseline(target_days=7):
    """找最接近 target_days 天前的快照（AI-News load_baseline 同款思路）。"""
    if not os.path.isdir(SNAP_DIR):
        return None, None
    files = sorted(f for f in os.listdir(SNAP_DIR) if f.endswith(".json"))
    if not files:
        return None, None
    today = date.today()
    target = today - timedelta(days=target_days)
    best, gap = None, 10 ** 6
    for f in files:
        try:
            fd = datetime.strptime(f[:-5], "%Y-%m-%d").date()
        except Exception:
            continue
        if fd >= today:
            continue
        g = abs((fd - target).days)
        if g < gap:
            gap, best = g, f
    if not best:
        return None, None
    d = json.load(open(os.path.join(SNAP_DIR, best), encoding="utf-8"))
    return d.get("stance") or {}, d.get("date")


def diff_stance(cur, base):
    """输出转向清单。base 为空 → 返回空列表 + reason，绝不编造。"""
    if not base:
        return [], "尚无历史快照可比对（首次运行或快照不足），按纪律不编造转向"
    changes = []
    for kol, per_t in cur.items():
        for t, info in per_t.items():
            b = (base.get(kol) or {}).get(t)
            if not b:
                changes.append({"kol": kol, "theater": t, "from": None,
                                "to": info["dir"], "kind": "new",
                                "n": info["n"], "last": info["last"]})
                continue
            if b["dir"] != info["dir"]:
                delta = DIR_RANK[info["dir"]] - DIR_RANK[b["dir"]]
                changes.append({"kol": kol, "theater": t, "from": b["dir"],
                                "to": info["dir"],
                                "kind": "escalate" if delta > 0 else "deescalate",
                                "n": info["n"], "last": info["last"]})
    # 排序：升级转向 > 降级转向 > 新增；同类按最近发言日倒序
    order = {"escalate": 0, "deescalate": 1, "new": 2}
    changes.sort(key=lambda c: (order[c["kind"]], c["last"]), reverse=False)
    return changes, ""


def main():
    stmts = all_statements()
    cur = compute_stance(stmts)
    p = save_snapshot(cur)
    base, base_date = load_baseline(7)
    changes, reason = diff_stance(cur, base)
    out = {"generated_on": str(date.today()), "baseline_date": base_date,
           "window_days": WINDOW_DAYS, "reason": reason, "changes": changes,
           "n_kol_with_stance": len(cur)}
    op = os.path.join(DATA, "stance_changes.json")
    json.dump(out, open(op, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"快照 → {p}")
    print(f"有明确立场的 KOL：{len(cur)} 位；基线日期：{base_date or '（无）'}")
    print(f"转向 {len(changes)} 条" + (f"｜{reason}" if reason else ""))
    for c in changes[:10]:
        print(f"  {c['kol'][:28]:<30} {c['theater']:<6} "
              f"{c['from'] or '（新增）'} → {c['to']}")


if __name__ == "__main__":
    sys.exit(main())
