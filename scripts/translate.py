#!/usr/bin/env python3
"""把言论条目与 KOL 档案翻译成中文，供 dashboard 三级钻取使用。

产物 = data/translations.json（增量缓存，SSOT 之外的派生数据）：
  {"stmt": {<source_url>: {"title_cn":..., "summary_cn":..., "src_hash":...}},
   "kol":  {<kol_name>:   {"aff_cn":..., "role_cn":..., ...,"src_hash":...}}}

为什么按 source_url / kol_name 做键 + 存 src_hash：
  每日 cron 只翻【新增或原文变了】的条目，已翻过的直接复用，
  不重复烧 LLM 配额（647 条全量重翻 ≈ 27 分钟，增量通常几十秒）。

★ 串行 + 1.5s 间隔：本机 genai 代理并发会大量 429（skill
  llm-batch-via-local-proxy 实测：并发 4 → 11/16；串行 1.5s → 10/10）。
  不要把它"优化"成并发。
★ 翻不出来就留空标 status，绝不手写编造中文（AGENTS.md 数据纪律）。
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CACHE = os.path.join(DATA, "translations.json")
API = os.environ.get("GENAI_PROXY", "http://127.0.0.1:8800") + "/v1/chat/completions"
MODEL = os.environ.get("TRANSLATE_MODEL", "claude-sonnet-4-5")
GAP = 1.5          # 串行间隔，见文件头注释
SAVE_EVERY = 10    # 中途落盘频率：长任务中断不全丢


def has_cjk(s):
    return any("\u4e00" <= c <= "\u9fff" for c in str(s or ""))


def _hash(*parts):
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p or "").encode("utf-8"))
    return h.hexdigest()[:16]


def load_cache():
    if os.path.exists(CACHE):
        try:
            c = json.load(open(CACHE, encoding="utf-8"))
            c.setdefault("stmt", {})
            c.setdefault("kol", {})
            return c
        except Exception:
            pass
    return {"stmt": {}, "kol": {}}


def save_cache(c):
    tmp = CACHE + ".tmp"
    json.dump(c, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if os.path.exists(CACHE):
        os.replace(CACHE, CACHE + ".bak")
    os.replace(tmp, CACHE)


def call_llm(system, user, retries=3, max_tokens=1200):
    body = json.dumps({
        "model": MODEL, "max_tokens": max_tokens, "temperature": 0.2,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }).encode("utf-8")
    last = ""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                API, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read().decode("utf-8"))
            return d["choices"][0]["message"]["content"].strip()
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(2 + attempt * 3)
    print(f"    ! LLM 失败 {last}", file=sys.stderr)
    return None


def parse_json_blob(txt):
    """模型偶尔会用 ```json 包裹或前后带闲话，容错抽取第一个 JSON 对象。

    ★ 实测坑：模型在中文正文里写直双引号（如 宣称的"胜利"）会破坏 JSON 字符串
      → json.loads 抛错。这不是模型失败，是解析太脆。所以：
      标准解析失败后，退回用正则直接抠 title_cn / summary_cn 的值。
    """
    if not txt:
        return None
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return None
    blob = m.group(0)
    try:
        return json.loads(blob)
    except Exception:
        pass
    # 退路：逐字段抠值，值一直吃到「", 下一个字段名」或「"\n}」为止
    out = {}
    for key in ("title_cn", "summary_cn", "aff_cn", "role_cn", "spec_cn",
                "why_cn", "ctr_cn"):
        km = re.search(
            r'"%s"\s*:\s*"(.*?)"\s*(?:,\s*"[a-z_]+_cn"\s*:|\}\s*$|\}\s*```)' % key,
            blob, re.S)
        if km:
            out[key] = (km.group(1).replace('\\n', '\n').replace('\\"', '"')
                        .replace('\\\\', '\\').strip())
    return out or None


# ── 言论条目翻译 ──────────────────────────────────────────────
STMT_SYS = (
    "你是战争与国防领域的专业译者。把英文新闻/智库条目译写成简体中文。\n"
    "输出严格的 JSON，不要任何解释文字，字段：\n"
    '  title_cn  — 中文标题，18-30 字，名词短语，不要虚浮修辞，'
    "去掉「| 机构名」这类站点后缀。\n"
    '  summary_cn — 中文要点总结，80-160 字，说清「谁 + 判断了什么 + 依据」，'
    "只依据给定原文，原文信息不足就照实写得短，绝不脑补补充事实。\n"
    "硬性要求：句子主体必须是简体中文；人名、机构名、武器型号、地名的通用"
    "英文缩写（如 CSIS、JASSM-ER、HIMARS）保留原文，其余一律译出。"
    "禁止整句英文。\n"
    "★ JSON 字符串值内部禁止出现直双引号 \"，需要引号时一律用中文引号「」。"
)


def translate_stmt(rec):
    u = (f"标题: {rec.get('title') or '（无）'}\n"
         f"发布者/KOL: {rec.get('kol') or ''}\n"
         f"战区: {rec.get('theater') or ''}\n"
         f"原文摘要: {(rec.get('summary') or '（该来源无摘要）')[:1500]}")
    # ★ 实测坑（skill llm-batch-via-local-proxy 记过）：标题本身就是
    #   「人名 | 站点名」这种纯专名时，模型会稳定原样回吐英文，重跑无效。
    #   第 3 轮起改用强化提示，明确要求把纯专名标题改写成中文描述句。
    for i in range(4):
        sys_p = STMT_SYS
        if i >= 2:
            sys_p += (
                "\n★★ 上一轮你把 title_cn 原样输出成了英文，这是错的。"
                "若原标题只是「人名 | 站点名」这类纯专名，不要照抄——"
                "请根据摘要内容改写成中文描述句，例如"
                "「<人名>：<其身份/所述议题>」。title_cn 必须含中文。")
        obj = parse_json_blob(call_llm(sys_p, u))
        if not obj:
            continue
        t, s = str(obj.get("title_cn") or "").strip(), str(obj.get("summary_cn") or "").strip()
        if has_cjk(t) and has_cjk(s):
            return {"title_cn": t, "summary_cn": s, "status": "ok"}
    return None


# ── KOL 档案翻译 ──────────────────────────────────────────────
KOL_SYS = (
    "你是战争与国防领域的专业译者。把 KOL 档案字段译成简体中文。\n"
    "输出严格 JSON，不要解释文字，字段（原字段为空则输出空字符串）：\n"
    "  aff_cn（所属机构）role_cn（角色职务）spec_cn（专长领域，≤40字）\n"
    "  why_cn（评级依据，≤120字）ctr_cn（争议记录，≤120字；"
    "原文是 none/无 时输出「暂无公开争议记录」）\n"
    "硬性要求：句子主体必须是简体中文；机构名首次可写「中文（English）」，"
    "人名、武器型号保留英文。禁止整句英文。\n"
    "★ JSON 字符串值内部禁止出现直双引号 \"，需要引号时一律用中文引号「」。"
)


def translate_kol(k):
    u = (f"姓名: {k.get('name_en') or k.get('name_zh')}\n"
         f"机构: {k.get('affiliation') or ''}\n"
         f"角色: {k.get('role') or ''}\n"
         f"专长: {k.get('specialty') or ''}\n"
         f"评级依据: {(k.get('rating_reason') or '')[:900]}\n"
         f"争议: {(k.get('controversies') or 'none')[:600]}")
    for _ in range(3):
        obj = parse_json_blob(call_llm(KOL_SYS, u))
        if not obj:
            continue
        out = {f"{a}_cn": str(obj.get(f"{a}_cn") or "").strip()
               for a in ("aff", "role", "spec", "why", "ctr")}
        # 只要主要字段是中文即可（机构名可能本就是英文缩写）
        if has_cjk(out["why_cn"]) or has_cjk(out["spec_cn"]) or has_cjk(out["role_cn"]):
            out["status"] = "ok"
            return out
    return None


def all_statements():
    d = os.path.join(DATA, "statements")
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（试跑用）")
    ap.add_argument("--force", action="store_true", help="忽略缓存全量重翻")
    ap.add_argument("--only", choices=["stmt", "kol"], help="只翻某一类")
    a = ap.parse_args()

    cache = load_cache()
    stmts = all_statements()
    roster = json.load(open(os.path.join(DATA, "kol_registry.json"), encoding="utf-8"))

    todo_s = []
    if a.only != "kol":
        for r in stmts:
            key = r["source_url"]
            h = _hash(r.get("title"), r.get("summary"))
            c = cache["stmt"].get(key)
            # ★「已处理」判据要覆盖所有终态；这里只有 ok 一态，失败不写缓存
            if c and c.get("src_hash") == h and not a.force:
                continue
            todo_s.append((key, h, r))
    todo_k = []
    if a.only != "stmt":
        for k in roster:
            name = k.get("name_en") or k.get("name_zh")
            h = _hash(k.get("affiliation"), k.get("role"), k.get("specialty"),
                      k.get("rating_reason"), k.get("controversies"))
            c = cache["kol"].get(name)
            if c and c.get("src_hash") == h and not a.force:
                continue
            todo_k.append((name, h, k))

    if a.limit:
        todo_s, todo_k = todo_s[:a.limit], todo_k[:a.limit]
    print(f"待翻：言论 {len(todo_s)} 条 / KOL {len(todo_k)} 人"
          f"（缓存已有 言论 {len(cache['stmt'])} / KOL {len(cache['kol'])}）")

    okc = failc = 0
    for i, (key, h, r) in enumerate(todo_s, 1):
        res = translate_stmt(r)
        if res:
            res["src_hash"] = h
            cache["stmt"][key] = res
            okc += 1
        else:
            failc += 1
            print(f"  [{i}/{len(todo_s)}] 失败: {(r.get('title') or '')[:50]}")
        if i % SAVE_EVERY == 0:
            save_cache(cache)
            print(f"  [{i}/{len(todo_s)}] 已落盘 ok={okc} fail={failc}", flush=True)
        time.sleep(GAP)
    save_cache(cache)

    kok = kfail = 0
    for i, (name, h, k) in enumerate(todo_k, 1):
        res = translate_kol(k)
        if res:
            res["src_hash"] = h
            cache["kol"][name] = res
            kok += 1
        else:
            kfail += 1
            print(f"  [KOL {i}/{len(todo_k)}] 失败: {name}")
        if i % SAVE_EVERY == 0:
            save_cache(cache)
            print(f"  [KOL {i}/{len(todo_k)}] 已落盘 ok={kok} fail={kfail}", flush=True)
        time.sleep(GAP)
    save_cache(cache)

    print(f"完成：言论 ok={okc} fail={failc} | KOL ok={kok} fail={kfail}")
    print(f"缓存总量：言论 {len(cache['stmt'])} / KOL {len(cache['kol'])} → {CACHE}")
    # 失败不静默：非零退出，避免空跑报成功
    sys.exit(1 if (failc or kfail) else 0)


if __name__ == "__main__":
    main()
