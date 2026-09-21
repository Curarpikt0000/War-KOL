#!/usr/bin/env python3
"""War-KOL 评级：四维加权分 → 群体内百分位 → 1-5★，只放行 3★ 以上。

口径（AGENTS.md「入库门槛与评级体系」，Chao 2026-09-02 拍板）：
- 四维权重：A 机构根基 30% / B 一手性 25% / C 历史命中率 30% / D 方法透明度 15%
- 星级用【群体内百分位】而非绝对切点：
  前10%=5★ / 10-30%=4★ / 30-60%=3★ / 60-85%=2★ / 其余=1★
  理由：「命中率 30% 算好算坏」没有客观答案，相对位次才可解释。
- 入库门槛 >= 3★；未达标写 candidates_rejected.json 留痕，不进 Notion 名册。
- C 维度证据不足者标 rating_provisional（前端显示「暂定」灰色），
  沿用 Forecast-Checker「judged<3 即暂定」的精神：分数照给，但标明置信不足。

输入：data/candidates_raw.json （子 agent 调研产物合并）
输出：data/roster_candidates.json（>=3★，待 Chao 审）
      data/candidates_rejected.json（<3★，留痕备查）
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(DATA, "candidates_raw.json")
OUT_PASS = os.path.join(DATA, "roster_candidates.json")
OUT_REJECT = os.path.join(DATA, "candidates_rejected.json")

WEIGHTS = {"score_A": 0.30, "score_B": 0.25, "score_C": 0.30, "score_D": 0.15}

# 百分位 → 星级。(累计占比上界, 星级)
BANDS = [(0.10, 5), (0.30, 4), (0.60, 3), (0.85, 2), (1.01, 1)]
MIN_STARS = 3


def weighted(rec):
    """按权重重算总分——不信任子 agent 自报的 weighted_score，自己算。"""
    total = 0.0
    for k, w in WEIGHTS.items():
        v = rec.get(k)
        if v is None:
            return None  # 维度缺失 → 无法定分
        total += float(v) * w
    return round(total, 3)


def is_provisional(rec):
    """C 维度证据不足 → 暂定星级。"""
    blob = " ".join(
        str(rec.get(k, "")) for k in ("rating_reason", "score_C_reason", "controversies")
    ).lower()
    return "insufficient_evidence" in blob or rec.get("score_C") is None


def main():
    if not os.path.exists(RAW):
        sys.exit(f"缺输入 {RAW}")
    recs = json.load(open(RAW, encoding="utf-8"))
    if not isinstance(recs, list) or not recs:
        sys.exit("candidates_raw.json 为空或格式不对")

    # 1) 重算加权分；缺维度的直接进 rejected（不猜分）
    scored, unscorable = [], []
    for r in recs:
        w = weighted(r)
        if w is None:
            r["reject_reason"] = "四维评分不完整，无法定级（不猜分）"
            unscorable.append(r)
            continue
        r["weighted_score_recomputed"] = w
        scored.append(r)

    # 2) 群体内百分位定星（降序，排名靠前 = 分高）
    scored.sort(key=lambda r: -r["weighted_score_recomputed"])
    n = len(scored)
    for i, r in enumerate(scored):
        pct = (i + 1) / n  # 1/n = 最高分
        for upper, stars in BANDS:
            if pct <= upper:
                r["stars"] = stars
                break
        r["percentile"] = round(pct, 4)
        r["rating_provisional"] = is_provisional(r)

    passed = [r for r in scored if r["stars"] >= MIN_STARS]
    rejected = [r for r in scored if r["stars"] < MIN_STARS] + unscorable
    for r in rejected:
        r.setdefault("reject_reason", f"星级 {r.get('stars')} < 入库门槛 {MIN_STARS}★")

    json.dump(passed, open(OUT_PASS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(rejected, open(OUT_REJECT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"候选总数 {len(recs)}  可定级 {n}  维度不全 {len(unscorable)}")
    dist = {}
    for r in scored:
        dist[r["stars"]] = dist.get(r["stars"], 0) + 1
    for s in sorted(dist, reverse=True):
        print(f"  {s}★: {dist[s]} 人")
    prov = sum(1 for r in passed if r["rating_provisional"])
    print(f"\n通过门槛(>={MIN_STARS}★): {len(passed)} 人（其中 {prov} 人星级暂定）")
    print(f"未通过留痕: {len(rejected)} 人")
    print(f"\n→ {OUT_PASS}\n→ {OUT_REJECT}")


if __name__ == "__main__":
    main()
