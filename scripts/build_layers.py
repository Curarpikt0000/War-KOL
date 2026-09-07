#!/usr/bin/env python3
"""War-KOL 四层内容生成器：一句话 / 总结 / 原文全文翻译 / 出处链接。

背景（Chao 2026-09-07 拍板）：
  「我现在只能看到 title，但展开之后就直接是原文了，中间这层缺失了。
    而且原文这层我不需要原文链接，我需要的是原文翻译。」
  旧结构的问题：
    L1 只有 18 字主题短语，光秃秃一行
    L2 最长的「论证」才 143 字，远不够「两三百到五六百字」
    L3 是英文摘要（搜索引擎 description，190 字），根本不是原文翻译
  Chao 要的四层：
    1 Title + 一句话
    2 总结 200-600 字
    3 原文翻译（原文多长译多长）
    4 原文链接（可有可无，放最后）

三条已拍板的口径：
  - 超长文【全文翻译，分段拼接】，不封顶（Chao 明确选了这个，代价约 5 小时）
  - 四层【都默认折叠】，逐层点开
  - 原有论点/论证/论据/数据【抽掉】，并入「总结」那一层

产物 data/layers/layers_<date>.json，按 source_url 建键，带 src_hash 增量：
  {"<url>": {"oneline":..., "summary":..., "translation":...,
             "src_hash":..., "trans_parts":N, "truncated":false}}

★ 串行 + GAP：本机 genai 代理并发必 429（skill llm-batch-via-local-proxy 实测）。
★ LLM 硬超时必须配 socket.setdefaulttimeout —— 只写 urlopen(timeout=) 挡不住
  半死连接，2026-09-03 实测卡死 35 分钟（判据是 /proc/<pid>/io 计数器不动）。
★ 绝不编造：正文取不到就跳过并标注，不用摘要伪造「翻译」。

用法：
  python3 scripts/build_layers.py --theater 中东      # 单战区样板
  python3 scripts/build_layers.py --all               # 全量
  python3 scripts/build_layers.py --all --limit 20    # 调试
"""
import argparse
import glob
import hashlib
import json
import os
import re
import socket
import sys
import time
import urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
THESIS_DIR = os.path.join(DATA, "thesis")
LAYER_DIR = os.path.join(DATA, "layers")
os.makedirs(LAYER_DIR, exist_ok=True)

API = os.environ.get("GENAI_PROXY", "http://127.0.0.1:8800") + "/v1/chat/completions"
MODEL = os.environ.get("LAYER_MODEL", "claude-sonnet-4-5")
GAP = 1.5
LLM_TIMEOUT = 180
SAVE_EVERY = 3

# 翻译分段：一段送多少原文字符。8000 字符 ≈ 2000 tokens 输入，
# 中文输出约 5000-6000 tokens，留足 max_tokens=8000 的余量。
CHUNK = 8000
MAX_TOKENS_TRANS = 8000
MAX_TOKENS_SUM = 2000


def _hash(*parts):
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p or "").encode("utf-8"))
    return h.hexdigest()[:16]


def call_llm(system, user, max_tokens=2000, retries=3):
    payload = json.dumps({
        "model": MODEL, "max_tokens": max_tokens, "temperature": 0.2,
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


# ── L1：一句话 ────────────────────────────────────────────────
SYS_ONE = (
    "你是战争与国防情报编辑。给定一篇文章的要点，写【一句话】中文导语。\n"
    "要求：35-55 字；必须点明「谁 + 对什么 + 判断了什么」；\n"
    "是完整陈述句，不是名词短语；不要虚浮修辞，不要「本文探讨」这类空话。\n"
    "直接输出这句话本身，不要引号、不要任何前后缀。"
)


def gen_oneline(rec):
    u = (f"KOL: {rec.get('kol')}\n战区: {rec.get('theater')}\n"
         f"主题: {rec.get('topic')}\n论点: {rec.get('claim')}\n"
         f"走势: {rec.get('direction')}")
    txt, err = call_llm(SYS_ONE, u, max_tokens=300)
    if err or not txt:
        return None
    return re.sub(r'^["「\']|["」\']$', "", txt.strip().split("\n")[0]).strip()


# ── L2：总结 ─────────────────────────────────────────────────
SYS_SUM = (
    "你是战争与国防情报分析师。给定一篇文章的正文和已抽取的要点，"
    "写一段【中文总结】。\n"
    "硬性要求：\n"
    "1. 长度 300-600 字。这是硬要求——太短没有信息量，"
    "读者点开就是为了看这一层。\n"
    "2. 必须包含四件事，融进行文里、不要写小标题：\n"
    "   · 这位 KOL 的核心判断是什么（可证伪的方向性结论）\n"
    "   · 他凭什么这么判断（论证逻辑）\n"
    "   · 支撑的具体事实（事件、部署、协议、组织行为）\n"
    "   · 文中出现的确切数字（数值 + 单位 + 时间限定），"
    "原文没有数字就不要编，写「原文未给出确切数字」\n"
    "3. 只依据给定材料，绝不用你自己的知识补充事实。\n"
    "4. 句子主体是简体中文；武器型号、机构缩写（CSIS、HIMARS、IRGC）保留原文。\n"
    "直接输出总结正文，不要标题、不要 JSON、不要任何前后缀。"
)


def gen_summary(rec, body):
    ev = "\n".join(f"- {x}" for x in (rec.get("evidence") or []))
    da = "\n".join(
        f"- {d.get('metric','')}：{d.get('value','')}（{d.get('context','')}）"
        for d in (rec.get("data") or []))
    u = (f"KOL: {rec.get('kol')}\n战区: {rec.get('theater')}\n"
         f"主题: {rec.get('topic')}\n"
         f"核心论点: {rec.get('claim')}\n"
         f"论证: {rec.get('reasoning')}\n"
         f"论据:\n{ev or '（无）'}\n"
         f"数据:\n{da or '（原文未给出确切数字）'}\n"
         f"时间视野: {rec.get('horizon')}\n\n"
         f"文章正文（节选）:\n{body[:12000]}")
    txt, err = call_llm(SYS_SUM, u, max_tokens=MAX_TOKENS_SUM)
    if err or not txt:
        return None
    return txt.strip()


# ── L3：原文全文翻译 ──────────────────────────────────────────
SYS_TRANS = (
    "你是战争与国防领域的专业译者。把给定的英文原文段落完整译成简体中文。\n"
    "硬性要求：\n"
    "1. 【完整翻译，不做摘要、不省略、不合并段落】。原文多长就译多长。\n"
    "2. 保留原文的段落结构，段落之间空一行。\n"
    "3. 人名、机构名、武器型号、地名的通用英文缩写（CSIS、JASSM-ER、HIMARS、"
    "IRGC、NATO）保留原文，其余一律译出。\n"
    "4. 遇到网页导航、订阅提示、Cookie 声明、社交分享按钮这类非正文噪音，"
    "直接跳过不译。\n"
    "5. 直接输出译文，不要任何说明、不要「以下是翻译」这类前缀。"
)


def split_chunks(body, size=CHUNK):
    """按段落边界切块，避免把句子劈开。"""
    paras = re.split(r"(?<=[.!?。！？])\s+", body)
    out, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 1 > size and cur:
            out.append(cur)
            cur = p
        else:
            cur = (cur + " " + p).strip() if cur else p
    if cur:
        out.append(cur)
    return out


def gen_translation(body, log_prefix=""):
    """全文翻译，长文分段拼接。返回 (译文, 段数, 失败段数)。"""
    chunks = split_chunks(body)
    parts, fails = [], 0
    for i, ch in enumerate(chunks, 1):
        head = (f"这是同一篇文章的第 {i}/{len(chunks)} 段，"
                f"请只翻译本段，不要重复前文也不要预告后文。\n\n"
                if len(chunks) > 1 else "")
        txt, err = call_llm(SYS_TRANS, head + ch, max_tokens=MAX_TOKENS_TRANS)
        if err or not txt:
            fails += 1
            parts.append(f"（第 {i} 段翻译失败：{(err or '空响应')[:60]}）")
        else:
            parts.append(txt.strip())
        if len(chunks) > 1:
            print(f"{log_prefix}    译 {i}/{len(chunks)}", flush=True)
        time.sleep(GAP)
    return "\n\n".join(parts), len(chunks), fails


# ── 装载 ─────────────────────────────────────────────────────
def load_thesis(theater=None):
    out = {}
    for fn in sorted(os.listdir(THESIS_DIR)):
        if not (fn.startswith("thesis_") and fn.endswith(".json")):
            continue
        try:
            rows = json.load(open(os.path.join(THESIS_DIR, fn), encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(rows, list):
            continue
        for r in rows:
            if isinstance(r, dict) and r.get("kol") and r.get("source_url"):
                if theater and r.get("theater") != theater:
                    continue
                out[r["source_url"]] = r
    return out


def load_bodies():
    p = os.path.join(THESIS_DIR, "_body_cache_all.json")
    if not os.path.exists(p):
        return {}
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}


def load_layers():
    """合并所有历史 layers 文件（增量复用，不重复烧配额）。"""
    out = {}
    for f in sorted(glob.glob(os.path.join(LAYER_DIR, "layers_*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if isinstance(d, dict):
            out.update(d)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--theater", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip-translation", action="store_true",
                    help="只生成一句话+总结（快速验收用）")
    args = ap.parse_args()

    today = date.today().isoformat()
    thesis = load_thesis(args.theater)
    bodies = load_bodies()
    layers = load_layers()
    out_path = os.path.join(LAYER_DIR, f"layers_{today}.json")
    today_out = {}
    if os.path.exists(out_path):
        try:
            today_out = json.load(open(out_path, encoding="utf-8"))
        except Exception:
            today_out = {}

    todo = []
    for url, rec in thesis.items():
        b = (bodies.get(url) or {}).get("body") or ""
        h = _hash(rec.get("claim"), b[:2000], len(b))
        old = layers.get(url)
        if old and old.get("src_hash") == h and old.get("translation"):
            continue                      # 已生成且原文未变
        todo.append((url, rec, b, h))
    if args.limit:
        todo = todo[:args.limit]

    scope = args.theater or "全量"
    print(f"入库言论 {len(thesis)}（{scope}）｜已有四层 {len(layers)}｜"
          f"本轮待生成 {len(todo)}")
    if not todo:
        print("无待办，退出")
        return

    nobody = sum(1 for _, _, b, _ in todo if len(b) < 200)
    print(f"其中正文不可用 {nobody} 条（只生成一句话+总结，翻译如实标注缺失）")

    t0 = time.time()
    done = 0
    for i, (url, rec, body, h) in enumerate(todo, 1):
        pre = f"[{i}/{len(todo)}]"
        entry = dict(layers.get(url) or {})

        one = gen_oneline(rec)
        time.sleep(GAP)
        summ = gen_summary(rec, body) if len(body) >= 200 else None
        time.sleep(GAP)

        if args.skip_translation:
            trans, nparts, fails = entry.get("translation"), 0, 0
        elif len(body) < 200:
            trans, nparts, fails = None, 0, 0
        else:
            trans, nparts, fails = gen_translation(body, log_prefix=pre)

        entry.update({
            "kol": rec.get("kol"), "theater": rec.get("theater"),
            "oneline": one, "summary": summ, "translation": trans,
            "trans_parts": nparts, "trans_fails": fails,
            "body_chars": len(body),
            "no_body": len(body) < 200,
            "src_hash": h, "built_on": today,
        })
        today_out[url] = entry
        layers[url] = entry
        done += 1

        print(f"{pre} {rec.get('kol','')[:18]}｜一句话{len(one or '')}字"
              f"｜总结{len(summ or '')}字｜译文{len(trans or '')}字"
              f"（{nparts}段，失败{fails}）", flush=True)

        if i % SAVE_EVERY == 0:
            json.dump(today_out, open(out_path, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=1)
        if i % 10 == 0:
            el = time.time() - t0
            eta = (len(todo) - i) * el / i / 60
            print(f"  ── 进度 {i}/{len(todo)}｜已用 {el/60:.0f}min"
                  f"｜ETA {eta:.0f}min", flush=True)

    json.dump(today_out, open(out_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    el = time.time() - t0
    ok_one = sum(1 for v in today_out.values() if v.get("oneline"))
    ok_sum = sum(1 for v in today_out.values() if v.get("summary"))
    ok_tr = sum(1 for v in today_out.values() if v.get("translation"))
    print(f"\n完成 {done} 条，用时 {el/60:.1f} 分钟")
    print(f"一句话 {ok_one} ｜总结 {ok_sum} ｜译文 {ok_tr} → {out_path}")


if __name__ == "__main__":
    main()
