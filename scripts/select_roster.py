#!/usr/bin/env python3
"""War-KOL 选名册：在 60 人上限内做【战区配额均衡】选取。

为什么不能纯按分数取前 60（实测数据）：
  纯分数前 60 的战区分布 = 军工23 / 俄乌13 / 中东12 / 印太12 / 非洲7 / 拉美4 / 南亚0
  → 南亚整个战区被清零，军工与战略独占 38%。
  原因是结构性的：智库型分析者（军工/预算/核态势）天然机构分高、
  出版物多、方法透明，而区域战地型分析者（南亚、非洲、拉美）
  即便是该领域最权威的人，A/D 维度也吃亏。
  一个「全球战争看板」缺了整个南亚战区是硬伤，不是优化问题。

做法：两段式
  1) 每个战区先保底 MIN_PER_THEATER 人（按该战区分数排序取头部）
  2) 剩余名额全局按分数补齐
  跨战区人物（如 Kofman 同时在俄乌+军工）只占一个名额，但为两个战区都记覆盖。

输出 data/roster_final.json，供 write_roster_to_notion.py 写入 Notion。
"""
import json
import os
import re
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SRC = os.path.join(DATA, "candidates_raw.json")
OUT = os.path.join(DATA, "roster_final.json")
OUT_REJ = os.path.join(DATA, "candidates_rejected.json")

CAP = 60               # Chao 明确要求控制在 60 以内
MIN_PER_THEATER = 5    # 每战区保底，避免小战区被清零
MIN_STARS = 3          # 入库门槛：只收 3★ 及以上

# ── 破例名单（均为 Chao 明确拍板，不是脚本自作主张）──────────────
# 1) 南亚放宽（Chao 2026-09-02）：南亚达 3★ 者仅 2 人（结构性——区域战地型
#    分析者在 A 机构根基 / D 方法透明度两维天然吃亏，即便是该领域最权威者
#    也卡在 2★）。放宽到 2★ 补至 5 人，卡片标「区域代表·评分较低」。
RELAX_THEATER = {"南亚": {"min_stars": 2, "target": 5}}

# 2) Chao 点名必须入库的人（原话：「这个 YouTube 博主，和他提到的一个伊朗人
#    都加入」）。两人评分均低于门槛（Taghvaee 4.4 排 121/123；
#    听风的蚕 2.3 排 123/123 全池垫底），故【不占 3★ 名额】，
#    单列为 watchlist（监测对象），卡片必须显示低可信度警示。
#    依据：Taghvaee 战时速报多为不可核验匿名消息、有被公开要求删帖记录，
#    其「32枚导弹/96-128枚PAC-3」说法检索不到独立佐证；
#    听风的蚕内容为二手转引再解读，无自采数据无来源清单。
WATCHLIST_NAMES = {"babak taghvaee", "zhu weiyi (\"ting feng de can\")"}
WATCHLIST_NOTE = "低可信度·需交叉验证（Chao 指定纳入监测，不计入 3★ 名额）"
W = {"score_A": 0.30, "score_B": 0.25, "score_C": 0.30, "score_D": 0.15}
BANDS = [(0.10, 5), (0.30, 4), (0.60, 3), (0.85, 2), (1.01, 1)]


def norm_name(name):
    s = (name or "").strip().lower()
    return re.sub(r"\s+", " ", s)


def weighted(r):
    return round(sum(float(r[k]) * v for k, v in W.items()), 3)


def main():
    recs = json.load(open(SRC, encoding="utf-8"))
    for r in recs:
        r["weighted_score_recomputed"] = weighted(r)
    recs.sort(key=lambda x: -x["weighted_score_recomputed"])

    # ★ 星级在【全量候选池】内定（百分位口径，AGENTS.md）。
    #   绝不在入选后的 60 人里重算——那 60 人全是头部，
    #   再切百分位会把 7.6 分的人标成 1★，既自相矛盾又违背「只收 3★ 以上」。
    total = len(recs)
    for i, r in enumerate(recs):
        pct = (i + 1) / total
        for upper, stars in BANDS:
            if pct <= upper:
                r["stars"] = stars
                break
        r["percentile"] = round(pct, 4)
        blob = f"{r.get('rating_reason','')} {r.get('controversies','')}".lower()
        r["rating_provisional"] = "insufficient_evidence" in blob

    # 只有 >= MIN_STARS 才有资格进名册（入库门槛）
    eligible = [r for r in recs if r["stars"] >= MIN_STARS]
    below = [r for r in recs if r["stars"] < MIN_STARS]
    print(f"全量 {total} 人定星后，达 {MIN_STARS}★ 门槛者 {len(eligible)} 人")

    theaters = sorted({t for r in recs for t in r["theater"]})
    by_theater = defaultdict(list)
    for r in eligible:
        for t in r["theater"]:
            by_theater[t].append(r)

    picked, picked_ids = [], set()

    # 1) 每战区保底（RELAX_THEATER 里的战区可放宽星级门槛补足）
    for t in theaters:
        pool = by_theater[t]
        target = MIN_PER_THEATER
        if t in RELAX_THEATER:
            cfg = RELAX_THEATER[t]
            target = cfg["target"]
            # 放宽：把该战区 >= 放宽门槛的人也纳入候选池（按分数序）
            pool = [r for r in recs if t in r["theater"] and r["stars"] >= cfg["min_stars"]]
        n = 0
        for r in pool:
            if n >= target:
                break
            if id(r) not in picked_ids:
                picked.append(r)
                picked_ids.add(id(r))
                if t in RELAX_THEATER and r["stars"] < MIN_STARS:
                    r["_pick_reason"] = f"{t}战区保底（放宽至 {RELAX_THEATER[t]['min_stars']}★）"
                    r["regional_representative"] = True
                    r["quality_flag"] = "区域代表·评分较低"
                else:
                    r["_pick_reason"] = f"{t}战区保底"
            n += 1

    # 2) 剩余名额在 eligible 内按分数补齐（星级已在全量池定好，不重算）
    for r in eligible:
        if len(picked) >= CAP:
            break
        if id(r) not in picked_ids:
            picked.append(r)
            picked_ids.add(id(r))
            r["_pick_reason"] = "全局分数"

    picked.sort(key=lambda x: -x["weighted_score_recomputed"])
    for r in picked:
        r["active"] = True

    # 3) watchlist：Chao 点名纳入的低分监测对象，附加在 CAP 之外，
    #    标 watchlist=True 供 dashboard 渲染低可信度警示。
    watch = []
    for r in recs:
        if norm_name(r.get("name_en")) in WATCHLIST_NAMES and id(r) not in picked_ids:
            r["watchlist"] = True
            r["active"] = True
            r["quality_flag"] = WATCHLIST_NOTE
            r["_pick_reason"] = "Chao 点名纳入（监测对象）"
            watch.append(r)
            picked_ids.add(id(r))
    picked.extend(watch)

    rejected = [r for r in recs if id(r) not in picked_ids]
    for r in rejected:
        if r["stars"] < MIN_STARS:
            r["reject_reason"] = f"星级 {r['stars']}★ < 入库门槛 {MIN_STARS}★"
        else:
            r["reject_reason"] = f"够格但未入选（分 {r['weighted_score_recomputed']}，{CAP} 人上限）"

    json.dump(picked, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(rejected, open(OUT_REJ, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"候选 {len(recs)} → 入选 {len(picked)} / 上限 {CAP}，留痕 {len(rejected)}")
    print(f"\n战区覆盖（一人可跨战区）：")
    c = Counter(t for r in picked for t in r["theater"])
    call = Counter(t for r in recs for t in r["theater"])
    for t in theaters:
        print(f"  {t}: {c.get(t,0)} / {call[t]}")
    print(f"\n星级分布：")
    for s, k in sorted(Counter(r["stars"] for r in picked).items(), reverse=True):
        print(f"  {s}★: {k} 人")
    prov = sum(1 for r in picked if r["rating_provisional"])
    print(f"  （其中 {prov} 人星级暂定：C 维度证据不足）")
    print(f"\n分数区间：{picked[-1]['weighted_score_recomputed']} ~ {picked[0]['weighted_score_recomputed']}")
    print(f"\n→ {OUT}\n→ {OUT_REJ}")


if __name__ == "__main__":
    main()
