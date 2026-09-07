#!/usr/bin/env python3
"""War-KOL 评分重构：C 维度只认【可验证的已到期预测】。

背景（Chao 2026-09-07 质疑，我核查后确认他是对的）：
  Ronald O'Rourke 零言论却拿 5★ / 9.55 分。
  「他零条记录怎么会有任何一条是准确的？」

  核查结果——AGENTS.md 白纸黑字写着 C 维度（权重 30%）应当是
  「过去公开预测 vs 实际结果的对照证据」，实际执行时全部落空：
    · 62 人里只有 8 人的评分理由含预测应验类证据
    · 20 人的理由只有「持续更新 / 定期发布 / 多次作证」——那是【产出勤勉度】
    · 34 人两者都没有
    · C 分数分布：8分42人 + 9分16人，几乎人人高分 = 这个维度没在区分任何东西
    · rating_provisional 全是 False，AGENTS.md 里写的「暂定」机制从未生效
  O'Rourke 拿 C=9 的原文理由是「四十余年持续更新 CRS 报告、定期简报作证」——
  没有一个字是预测命中。

本脚本的口径（Chao 2026-09-07 拍板）：
  1. C 维度【只判已到期的预测】：从入库言论里取 horizon 可解析且已过期的，
     逐条判 hit / miss / unclear；表述模糊无法客观验证的一律 unclear 不强判
     （沿用 Forecast-Checker 的口径）。
  2. judged < 3 → C 维度【置空不给分】，rating_provisional=True，
     加权分只按 A/B/D 三维重新归一，前端显示「暂定·命中率样本不足」。
     ——不再拿产量冒充命中率。
  3. 零言论的人【移出主榜】，进「监测中·待验证」区，不给星级。
  4. 星级仍是群体内百分位，但【只在有正式评分的人之间】排，
     暂定与监测中的人不参与排名，避免稀释。

用法：
  python3 scripts/rescore_kols.py            # dry-run，只打印
  python3 scripts/rescore_kols.py --apply    # 写回 data/kol_registry.json
"""
import argparse
import glob
import json
import os
import re
import socket
import sys
import time
import urllib.request
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
REGISTRY = os.path.join(DATA, "kol_registry.json")
THESIS_DIR = os.path.join(DATA, "thesis")

API = os.environ.get("GENAI_PROXY", "http://127.0.0.1:8800") + "/v1/chat/completions"
MODEL = os.environ.get("SCORE_MODEL", "claude-sonnet-4-5")
GAP = 1.5
LLM_TIMEOUT = 150
MIN_JUDGED = 3          # 少于这么多条已判定 → C 置空标暂定（AGENTS.md 口径）

W = {"A": 0.30, "B": 0.25, "C": 0.30, "D": 0.15}


def call_llm(system, user, max_tokens=1200, retries=3):
    payload = json.dumps({
        "model": MODEL, "max_tokens": max_tokens, "temperature": 0.1,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }).encode("utf-8")
    last = ""
    for attempt in range(retries):
        resp = None
        old = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(LLM_TIMEOUT)
            req = urllib.request.Request(
                API, data=payload, headers={"Content-Type": "application/json"})
            resp = urllib.request.urlopen(req, timeout=LLM_TIMEOUT)
            d = json.loads(resp.read().decode("utf-8"))
            return d["choices"][0]["message"]["content"].strip(), None
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(2 + attempt * 3)
        finally:
            socket.setdefaulttimeout(old)
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass
    return None, last


# ── 到期判定：horizon 文本 → 截止日 ───────────────────────────
_UNIT_DAYS = {"天": 1, "日": 1, "周": 7, "个月": 30, "月": 30, "年": 365,
              "季度": 90, "季": 90}


def horizon_deadline(pub, horizon):
    """发表日 + 时间视野 → 截止日。解析不出返回 None（不猜）。"""
    if not pub or not horizon:
        return None
    try:
        p = date.fromisoformat(pub[:10])
    except Exception:
        return None
    h = str(horizon)
    # 「2026年内」「2026年底前」
    m = re.search(r"(20[2-3]\d)\s*年", h)
    if m and ("内" in h or "底" in h or "前" in h):
        return date(int(m.group(1)), 12, 31)
    # 「3个月内」「未来1-2周」「6-12个月」——取上界，宁可判晚不判早
    m = re.search(r"(\d+)\s*[-~至]\s*(\d+)\s*(天|日|周|个月|月|年|季度|季)", h)
    if m:
        return p + timedelta(days=int(m.group(2)) * _UNIT_DAYS[m.group(3)])
    m = re.search(r"(\d+)\s*(天|日|周|个月|月|年|季度|季)", h)
    if m:
        return p + timedelta(days=int(m.group(1)) * _UNIT_DAYS[m.group(2)])
    if "短期" in h:
        return p + timedelta(days=90)
    if "中期" in h:
        return p + timedelta(days=365)
    if "长期" in h:
        return p + timedelta(days=365 * 3)
    return None                     # 「未指明」等一律不猜


JUDGE_SYS = """你是战争预测的事后核验员。给定一条 KOL 在过去做出的方向性判断，
以及它的发表日与到期日（都已过去），请判定这条预测是否应验。

严格输出 JSON：
 verdict  — 只能是 hit / miss / unclear 三者之一
 reason   — 40-80 字中文，说清判据

判定规则（极重要）：
1. 只依据你确知的公开事实判定。你【不确定】后续实际发生了什么，
   一律判 unclear，绝不猜。
2. 表述模糊、无法客观验证的（如「局势可能变化」「风险上升」而无具体门槛），
   一律判 unclear，【不强判】。
3. hit = 他说的具体事情确实发生了；miss = 明确没发生或发生了相反的事。
4. 判 hit/miss 时 reason 里必须点出【具体的事实依据】，说不出就改判 unclear。
JSON 字符串值内禁止直双引号，需要引号用「」。"""


def judge_one(rec, deadline):
    u = (f"KOL: {rec.get('kol')}\n战区: {rec.get('theater')}\n"
         f"发表日: {rec.get('published_on')}\n到期日: {deadline}\n"
         f"今天: {date.today().isoformat()}\n"
         f"论点: {rec.get('claim')}\n"
         f"论证: {rec.get('reasoning')}\n"
         f"时间视野: {rec.get('horizon')}")
    txt, err = call_llm(JUDGE_SYS, u, max_tokens=600)
    if err or not txt:
        return None, err or "空响应"
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return None, "无法解析"
    try:
        j = json.loads(m.group(0))
    except Exception:
        return None, "JSON 解析失败"
    v = j.get("verdict")
    if v not in ("hit", "miss", "unclear"):
        return None, f"verdict 非法 {v}"
    return (v, j.get("reason", "")), None


def wilson_lower(hits, n, z=1.96):
    """Wilson 95% 置信下界（AGENTS.md 指定口径，沿用 Forecast-Checker）。
    小样本会被自动惩罚——这正是我们要的：3 中 3 不该等同 30 中 30。"""
    if n == 0:
        return 0.0
    p = hits / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return max(0.0, (c - m) / d)


def load_thesis():
    out = {}
    for fn in sorted(os.listdir(THESIS_DIR)):
        if not (fn.startswith("thesis_") and fn.endswith(".json")):
            continue
        try:
            rows = json.load(open(os.path.join(THESIS_DIR, fn), encoding="utf-8"))
        except Exception:
            continue
        if isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict) and r.get("kol"):
                    out[(r["kol"], r.get("source_url"))] = r
    return out


def pct_star(rank, total):
    """群体内百分位 → 星级（AGENTS.md 口径）。rank 从 0 起（0 = 最高分）。"""
    if total <= 0:
        return 1
    p = rank / total
    if p < 0.10:
        return 5
    if p < 0.30:
        return 4
    if p < 0.60:
        return 3
    if p < 0.85:
        return 2
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit-judge", type=int, default=0,
                    help="最多判定多少条（调试）")
    args = ap.parse_args()

    reg = json.load(open(REGISTRY, encoding="utf-8"))
    thesis = load_thesis()
    by_kol = {}
    for (k, _), r in thesis.items():
        by_kol.setdefault(k, []).append(r)

    today = date.today()
    # 1. 找出所有【已到期】的预测
    due = []
    for k, recs in by_kol.items():
        for r in recs:
            dl = horizon_deadline(r.get("published_on"), r.get("horizon"))
            if dl and dl < today:
                due.append((k, r, dl))
    print(f"入库言论 {len(thesis)} 条 / {len(by_kol)} 人")
    print(f"其中【时间视野可解析且已到期】的预测：{len(due)} 条")
    if args.limit_judge:
        due = due[:args.limit_judge]

    # 2. 逐条判定
    cache_path = os.path.join(DATA, "prediction_verdicts.json")
    verdicts = {}
    if os.path.exists(cache_path):
        try:
            verdicts = json.load(open(cache_path, encoding="utf-8"))
        except Exception:
            verdicts = {}
    todo = [(k, r, dl) for k, r, dl in due
            if r.get("source_url") not in verdicts]
    print(f"已有判定 {len(verdicts)}｜本轮待判 {len(todo)}")
    for i, (k, r, dl) in enumerate(todo, 1):
        res, err = judge_one(r, dl.isoformat())
        if err:
            print(f"  [{i}/{len(todo)}] {k[:20]} 判定失败 {err[:40]}")
        else:
            v, why = res
            verdicts[r["source_url"]] = {
                "kol": k, "verdict": v, "reason": why,
                "published_on": r.get("published_on"),
                "deadline": dl.isoformat(), "claim": r.get("claim"),
                "judged_on": today.isoformat(),
            }
            print(f"  [{i}/{len(todo)}] {k[:20]:22s} {v:8s} {(why or '')[:50]}")
        if i % 5 == 0:
            json.dump(verdicts, open(cache_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        time.sleep(GAP)
    json.dump(verdicts, open(cache_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # 3. 汇总每人的命中统计
    stat = {}
    for v in verdicts.values():
        s = stat.setdefault(v["kol"], {"hit": 0, "miss": 0, "unclear": 0})
        s[v["verdict"]] += 1

    # 4. 重算分数
    out, monitor, provisional = [], [], []
    for k in reg:
        nm = k.get("name_en") or k.get("name_zh")
        n_stmt = len(by_kol.get(nm, []))
        s = stat.get(nm, {"hit": 0, "miss": 0, "unclear": 0})
        judged = s["hit"] + s["miss"]          # unclear 不进分母
        k["n_statements"] = n_stmt
        k["pred_hit"], k["pred_miss"], k["pred_unclear"] = \
            s["hit"], s["miss"], s["unclear"]
        k["pred_judged"] = judged

        if n_stmt == 0:
            # ★ Chao 2026-09-07：零言论不进主榜
            k["tier"] = "monitor"
            k["rating"] = None
            k["weighted_score"] = None
            k["score_C"] = None
            k["rating_provisional"] = True
            k["score_note"] = "零入库言论 —— 移出主榜，进「监测中·待验证」区"
            monitor.append(nm)
            continue

        A, B, D = k.get("score_A"), k.get("score_B"), k.get("score_D")
        if judged >= MIN_JUDGED:
            C = round(wilson_lower(s["hit"], judged) * 10, 2)
            k["score_C"] = C
            w = (A * W["A"] + B * W["B"] + C * W["C"] + D * W["D"])
            k["rating_provisional"] = False
            k["tier"] = "rated"
            k["score_note"] = (f"命中率经 {judged} 条已到期预测验证："
                               f"{s['hit']} 中 / {s['miss']} 失"
                               f"（另 {s['unclear']} 条表述模糊不强判），"
                               f"Wilson 95% 下界 {C/10:.2f}")
        else:
            # ★ C 置空，只按 A/B/D 三维归一 —— 绝不拿产量冒充命中率
            k["score_C"] = None
            denom = W["A"] + W["B"] + W["D"]
            w = (A * W["A"] + B * W["B"] + D * W["D"]) / denom
            k["rating_provisional"] = True
            k["tier"] = "provisional"
            k["score_note"] = (f"命中率样本不足（已到期预测 {judged} 条 < {MIN_JUDGED}），"
                               f"C 维度置空，加权分仅按机构根基/一手性/方法透明度三维计算")
            provisional.append(nm)
        k["weighted_score"] = round(w, 2)
        out.append(k)

    # 5. 星级 = 群体内百分位（Chao 2026-09-07 口径）
    #    · rated（命中率已核验）与 provisional（样本不足）【分开各自排名】，
    #      否则两种口径的分数混在一起排，百分位没有意义
    #      （rated 的 C 走 Wilson 下界会被小样本重罚，硬混排会让被验证者吃亏）
    #    · provisional 给【临时星级】并标明「未经命中率验证」，
    #      rated 额外带 verified=True，前端打「✓已核验」徽章
    rated = [k for k in out if k.get("tier") == "rated"]
    prov = [k for k in out if k.get("tier") == "provisional"]
    for group, verified in ((rated, True), (prov, False)):
        group.sort(key=lambda x: -x["weighted_score"])
        for i, k in enumerate(group):
            k["rating"] = f"{pct_star(i, len(group))}★"
            k["hit_verified"] = verified
            if not verified:
                k["rating_label"] = "临时·未经命中率验证"
            else:
                k["rating_label"] = "✓ 命中率已核验"

    print(f"\n{'='*62}")
    print(f"正式评分 {len(rated)} 人｜暂定（命中率样本不足）{len(provisional)} 人"
          f"｜监测中（零言论）{len(monitor)} 人")
    print(f"\n监测中: {monitor}")
    print(f"\n=== 正式评分 Top 10 ===")
    for k in rated[:10]:
        nm = k.get("name_en") or k.get("name_zh")
        print(f"  {k['rating']} {k['weighted_score']:5.2f}  {nm[:34]:36s} "
              f"C={k['score_C']} ({k['pred_hit']}/{k['pred_judged']})")
    if provisional:
        print(f"\n=== 暂定（前 8）===")
        for k in out:
            if k.get("tier") == "provisional" and provisional.index(
                    k.get("name_en") or k.get("name_zh")) < 8:
                nm = k.get("name_en") or k.get("name_zh")
                print(f"  暂定 {k['weighted_score']:5.2f}  {nm[:34]:36s} "
                      f"已到期预测 {k['pred_judged']} 条")

    if args.apply:
        bak = REGISTRY + f".bak-rescore-{today.isoformat()}"
        if not os.path.exists(bak):
            json.dump(json.load(open(REGISTRY, encoding="utf-8")),
                      open(bak, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"\n已备份 → {bak}")
        json.dump(reg, open(REGISTRY, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"已写回 {REGISTRY}")
    else:
        print("\n（dry-run，未写回。加 --apply 生效）")


if __name__ == "__main__":
    main()
