#!/usr/bin/env python3
"""War-KOL 言论「五要素」抽取器：搜索结果 → 抓正文 → LLM 抽判断 → 落盘。

背景（Chao 2026-09-03 拍板）：
  旧管道把【搜索引擎结果】直接当言论入库，于是专家简介页、机构名录页、
  作者归档页全都进了 dashboard（Aaron Y. Zelin 11 条里 10 条是简介）。
  且 quote 字段全库 1086 条全空 —— 从来没抓过一次正文，
  所谓 summary 只是搜索引擎 150-250 字的 description。
  结论：没有正文 = 没有论点论据 = 这条消息没有意义。

本脚本给每条候选加三道闸：
  闸 1  名录/简介页过滤（URL 特征 + 标题特征），纯规则、零成本
  闸 2  正文抓取，取不到（付费墙 / 403 / 正文过短）直接剔除
        —— Chao 明确选「直接剔除，不进 dashboard」，不做「仅存目」区
  闸 3  LLM 抽取七要素；模型判定正文里没有【该 KOL 本人】的方向性判断
        就输出 skip，同样剔除

三道闸的剔除物【全部落盘留痕】，不静默丢弃：
  data/removed_directory_<date>.json    闸 1
  data/removed_nobody_<date>.json       闸 2
  data/removed_no_thesis_<date>.json    闸 3

★ 串行 + GAP 间隔：本机 genai 代理并发必 429
  （skill llm-batch-via-local-proxy 实测：并发 4 → 11/16；串行 1.5s → 10/10）。
  正文抓取可以并发（走的是外网各站，不是同一个代理），LLM 调用绝不能。

★ 绝不脑补：抽不出就剔除并留痕，不用摘要凑一个「论点」。

用法：
  python3 scripts/extract_thesis.py --theater 中东 --out data/thesis/mideast.json
  python3 scripts/extract_thesis.py --all --limit 50
"""
import argparse
import json
import os
import re
import socket
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
STORE = os.path.join(DATA, "statements")
THESIS_DIR = os.path.join(DATA, "thesis")
os.makedirs(THESIS_DIR, exist_ok=True)

API = os.environ.get("GENAI_PROXY", "http://127.0.0.1:8800") + "/v1/chat/completions"
MODEL = os.environ.get("THESIS_MODEL", "claude-sonnet-4-5")
GAP = 1.5
SAVE_EVERY = 5
MIN_BODY = 800          # 正文字符下限，低于此视为抓取失败（实测：简介页普遍 <500）
MIN_EVIDENCE = 3        # 论据条数下限。Chao 2026-09-03 从 2 抬到 3 —— 现有 138 条
                        # 最少的就是 3 条，抬高零损失，但挡住未来的凑数条目。
BODY_CAP = 14000        # 送进 LLM 的正文上限
LLM_TIMEOUT = 120       # LLM 单次调用硬超时（秒）。见 call_llm 的踩坑注释：
                        # 光靠 urlopen(timeout=) 挡不住半死连接，必须配
                        # socket.setdefaulttimeout 才真正生效。

UA = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}

# ── 闸 1：名录 / 简介 / 索引页特征 ────────────────────────────
# 这些 URL 路径段几乎必然是「关于这个人」而不是「这个人说了什么」
DIRECTORY_URL = re.compile(
    r"/(experts?|people|staff|authors?|scholars?|fellows?|profiles?|about|bio|"
    r"team|contributors?|tags?|topics?|category|categories|search|archive|"
    r"newsroom|press-room|our-work|programs?)(/|$|\?)", re.I)
# 站点首页（无路径）同样不是言论：jihadology.net/ 抓回来的是网站 slogan
ROOT_PAGE = re.compile(r"^https?://[^/]+/?$", re.I)
DIRECTORY_TITLE = re.compile(
    r"(\|\s*(The Washington Institute|CSIS|RUSI|SIPRI|Hudson Institute|Lawfare|"
    r"Foreign Affairs|Atlantic Council|Chatham House|IISS|Brookings|Carnegie)\s*$|"
    r"^[A-Z][a-z]+ [A-Z]\.? ?[A-Za-z]*\s*[-–|]\s*|"
    r"\b(Expert|Experts|Profile|Biography|Staff|Author at|Authors|Archives?|"
    r"Tag:|Topics?:|Search results|All Articles|Publications by|About Us|"
    r"Read All The Stories|Latest News & Videos|Bookshelf|Reading List|"
    r"Curriculum Vitae|CV\b|Upcoming Event|Webinar with|Register Now|"
    r"Podcast Preview|Episode Guide|Speaker Series)\b)", re.I)
# ★ 2026-09-03 闸3 复盘补的：LLM 花了配额才判出「这是书单/预告页」的，
#   规则层能免费挡掉 19 条简介/书单/目录 + 3 条播客预告。
DIRECTORY_URL2 = re.compile(
    r"/(bookshelf|reading-list|cv|curriculum-vitae|events?|webinars?|"
    r"podcast-preview|speakers?|register|subscribe|newsletter)(/|$|\?|-)", re.I)


def is_directory_page(rec):
    """返回 (是否名录页, 理由)。纯规则判定，不烧 LLM。"""
    url = rec.get("source_url") or ""
    title = rec.get("title") or ""
    if not url:
        return True, "无 URL"
    if ROOT_PAGE.match(url):
        return True, "站点首页（非具体文章）"
    m = DIRECTORY_URL.search(url)
    if m:
        return True, f"URL 名录路径段 /{m.group(1)}/"
    m = DIRECTORY_URL2.search(url)
    if m:
        return True, f"URL 书单/预告路径段 /{m.group(1)}/"
    m = DIRECTORY_TITLE.search(title)
    if m:
        return True, f"标题名录特征「{m.group(0).strip()[:30]}」"
    return False, ""


# ── 闸 2：正文抓取 ────────────────────────────────────────────
def _pdf_text(content, max_pages=15):
    """PDF 正文抽取。★ 2026-09-03 实测：闸2 失败里 25 条是 PDF，
    闸3「无本人判断」里 23 条 LLM 说「正文乱码/二进制损坏」——
    那不是没内容，是我们把 PDF 字节喂给了 HTML 解析器。"""
    try:
        import fitz  # pymupdf
    except Exception:
        return ""
    try:
        doc = fitz.open(stream=content, filetype="pdf")
        txt = " ".join(p.get_text() for p in doc[:max_pages])
        return re.sub(r"\s+", " ", txt).strip()
    except Exception:
        return ""


def fetch_body(url, timeout=20):
    """返回 (status, body)。status 为 int 或异常类名。

    ★ 三层提取（2026-09-03 实测得出，每层都有回收率数字）：
      1) PDF 走 pymupdf —— 抽样 12 条可读 58%
      2) HTML 严格法：只取 <p>/<li> 且 >60 字符（干净但漏）
      3) HTML 宽松兜底：article / main / [role=main] / body 全文
         —— 对「200 但正文<800」的 111 条抽样，可回收 40%
      严格法够长就用严格法，不够才降级到宽松法，避免把导航栏当正文。
    """
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
    except Exception as e:
        return type(e).__name__, ""
    if r.status_code != 200:
        return r.status_code, ""

    ctype = (r.headers.get("Content-Type") or "").lower()
    if "pdf" in ctype or url.lower().split("?")[0].endswith(".pdf"):
        return 200, _pdf_text(r.content)

    try:
        soup = BeautifulSoup(r.text, "lxml")
    except Exception:
        return "ParseError", ""
    for t in soup(["script", "style", "nav", "header", "footer",
                   "aside", "form", "noscript"]):
        t.decompose()
    parts = [el.get_text(" ", strip=True)
             for el in soup.find_all(["p", "li"])
             if len(el.get_text(strip=True)) > 60]
    strict = re.sub(r"\s+", " ", " ".join(parts)).strip()
    if len(strict) >= MIN_BODY:
        return 200, strict
    node = (soup.find("article") or soup.find("main")
            or soup.find(attrs={"role": "main"}) or soup.body)
    loose = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""
    return 200, (loose if len(loose) > len(strict) else strict)


# ── 闸 3：LLM 抽取 ───────────────────────────────────────────
SYS = """你是战争与国防情报分析师。给定一篇文章正文和一位 KOL 的名字，抽取【该 KOL 本人】在文中的判断性内容。

严格输出 JSON，字段：
 topic     — 主题，12-20字中文名词短语（针对哪个地区/哪场冲突/哪类装备）
 claim     — 核心论点，一句中文，必须是可证伪的方向性判断（会不会升级/降级/僵持、谁占优、何时发生、多少产能）
 reasoning — 论证逻辑，60-120字中文，说清他凭什么这么判断
 evidence  — 论据数组，3-6条中文短句，每条必须是文中出现的【具体事实】（事件、部署、协议、组织行为）
 data      — 数据数组，0-6条，每条 {"metric":"指标名","value":"数值+单位","context":"时间/来源限定"}，
             只收文中出现的确切数字，没有就给空数组，绝不估算
 direction — 只能是 升级 / 降级 / 僵持 / 未表态 之一
 horizon   — 时间视野，如 「3个月内」「2026年内」「未指明」
 confidence— high / medium / low，指该 KOL 表述的确定程度

硬性规则：
1. 如果正文里【找不到该 KOL 本人的方向性判断】——例如这是人物简介页、机构名录页、
   纯新闻报道、他只是被顺带提及、或正文只有背景叙述没有他的观点——
   必须输出 {"skip": true, "skip_reason": "简短中文理由"}，绝不脑补。
2. evidence 与 data 必须来自正文，禁止用你自己的知识补充。
3. 句子主体必须是简体中文；武器型号、机构缩写（CSIS、HIMARS、JASSM-ER）保留原文。
4. JSON 字符串值内部禁止出现直双引号，需要引号时一律用中文引号「」。"""


def call_llm(kol, title, theater, body, retries=3):
    """调 LLM 抽取。

    ★ 2026-09-03 踩坑：只写 urlopen(timeout=180) 不够。socket 已 ESTABLISHED
      但服务端半死不回时，Python 的 timeout 只覆盖「建立连接」和「单次 recv」，
      遇到「连上了但永远不返回数据」会**无限挂起**——实测卡了 35 分钟，
      /proc/<pid>/io 计数器纹丝不动，线程池早结束，只剩主线程 poll 一个 socket。
      正解：socket.setdefaulttimeout 兜底 + 每次请求后显式 close。
    """
    user = (f"KOL: {kol}\n战区: {theater}\n标题: {title}\n"
            f"正文:\n{body[:BODY_CAP]}")
    payload = json.dumps({
        "model": MODEL, "max_tokens": 1600, "temperature": 0.1,
        "messages": [{"role": "system", "content": SYS},
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
            raw = resp.read().decode("utf-8")
            d = json.loads(raw)
            return d["choices"][0]["message"]["content"], None
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


def parse_json(txt):
    """模型偶尔 ```json 包裹或中文里写直双引号，容错抽取。"""
    if not txt:
        return None
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        # 退路：把中文引号外的裸直引号转义后再试
        blob = m.group(0)
        try:
            return json.loads(re.sub(r'(?<=[\u4e00-\u9fff])"(?=[\u4e00-\u9fff])',
                                     "「", blob))
        except Exception:
            return None


REQUIRED = ("topic", "claim", "reasoning", "evidence", "direction")


def validate(j):
    """硬门禁：五要素缺一不可。写进函数而不是写进文档——
    自己定的标准靠『记得检查』执行，迟早会在自己身上破例。"""
    if not isinstance(j, dict):
        return "非 JSON 对象"
    for k in REQUIRED:
        v = j.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            return f"缺字段 {k}"
    if not isinstance(j.get("evidence"), list) or len(j["evidence"]) < MIN_EVIDENCE:
        return f"论据少于 {MIN_EVIDENCE} 条"
    if j.get("direction") not in ("升级", "降级", "僵持", "未表态"):
        return f"direction 非法：{j.get('direction')}"
    if len(j.get("reasoning", "")) < 40:
        return "论证过短（<40字）"
    if not isinstance(j.get("data"), list):
        j["data"] = []
    return None


def load_candidates(theater=None, files=None):
    recs, seen = [], set()
    src = files or sorted(f for f in os.listdir(STORE) if f.endswith(".json"))
    for fn in src:
        path = os.path.join(STORE, fn)
        try:
            rows = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        for s in rows:
            if s.get("status") != "ok" or not s.get("source_url"):
                continue
            if theater and s.get("theater") != theater:
                continue
            key = (s.get("kol"), s["source_url"])
            if key in seen:
                continue
            seen.add(key)
            recs.append(s)
    return recs


def dump(path, rows):
    if rows:
        json.dump(rows, open(path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--theater", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--workers", type=int, default=8, help="正文抓取并发（LLM 恒串行）")
    args = ap.parse_args()

    today = date.today().isoformat()
    cands = load_candidates(args.theater)
    if args.limit:
        cands = cands[:args.limit]
    tag = args.theater or "all"
    out_path = args.out or os.path.join(THESIS_DIR, f"thesis_{tag}_{today}.json")
    print(f"候选 {len(cands)} 条（theater={tag}）")

    # 断点续跑：已抽过的不重复烧配额
    done_keys, results = set(), []
    if os.path.exists(out_path):
        try:
            results = json.load(open(out_path, encoding="utf-8"))
            done_keys = {(r["kol"], r["source_url"]) for r in results}
            print(f"  已有产物 {len(results)} 条，跳过重跑")
        except Exception:
            results = []

    # ── 闸 1 ──
    rm_dir, stage2 = [], []
    for s in cands:
        bad, why = is_directory_page(s)
        if bad:
            rm_dir.append({**s, "removed_reason": why, "removed_stage": "directory"})
        else:
            stage2.append(s)
    print(f"闸1 名录/简介页剔除 {len(rm_dir)} → 剩 {len(stage2)}")

    stage2 = [s for s in stage2 if (s["kol"], s["source_url"]) not in done_keys]

    # ── 闸 2（并发抓正文）──
    # ★ 正文落盘缓存：闸2 抓 1147 页要十几分钟，进程一挂就全丢、重跑得重抓。
    #   2026-09-03 因 LLM 半死连接卡死重启，白白重抓了一轮，加了这个缓存。
    cache_path = os.path.join(THESIS_DIR, f"_body_cache_{tag}.json")
    body_cache = {}
    if os.path.exists(cache_path):
        try:
            body_cache = json.load(open(cache_path, encoding="utf-8"))
            print(f"  正文缓存命中 {len(body_cache)} 条")
        except Exception:
            body_cache = {}

    need = [s for s in stage2 if s["source_url"] not in body_cache]
    t0 = time.time()
    if need:
        fetched = list(ThreadPoolExecutor(args.workers).map(
            lambda s: (s["source_url"], *fetch_body(s["source_url"])), need))
        for url, st, body in fetched:
            body_cache[url] = {"st": str(st), "body": body}
        json.dump(body_cache, open(cache_path, "w", encoding="utf-8"),
                  ensure_ascii=False)
    rm_body, stage3 = [], []
    for s in stage2:
        c = body_cache.get(s["source_url"]) or {"st": "miss", "body": ""}
        st, body = c["st"], c["body"]
        if st == "200" and len(body) >= MIN_BODY:
            stage3.append((s, body))
        else:
            rm_body.append({**s, "removed_reason": f"正文不可得 http={st} chars={len(body)}",
                            "removed_stage": "nobody"})
    print(f"闸2 正文抓取 {time.time()-t0:.0f}s（新抓 {len(need)}），"
          f"取不到剔除 {len(rm_body)} → 剩 {len(stage3)}")

    # ── 闸 3（串行 LLM）──
    rm_nothesis, errs = [], 0
    t0 = time.time()
    for i, (s, body) in enumerate(stage3, 1):
        txt, err = call_llm(s["kol"], s.get("title", ""),
                            s.get("theater", ""), body)
        if err:
            errs += 1
            print(f"  [{i}/{len(stage3)}] {s['kol']} — LLM 失败 {err[:60]}")
            time.sleep(GAP)
            continue
        j = parse_json(txt)
        if not j:
            rm_nothesis.append({**s, "removed_reason": "LLM 输出无法解析",
                                "removed_stage": "no_thesis"})
        elif j.get("skip"):
            rm_nothesis.append({**s, "removed_reason": f"无本人判断：{j.get('skip_reason','')}"[:200],
                                "removed_stage": "no_thesis"})
        else:
            bad = validate(j)
            if bad:
                rm_nothesis.append({**s, "removed_reason": f"五要素不合格：{bad}",
                                    "removed_stage": "no_thesis"})
            else:
                results.append({
                    "kol": s["kol"], "theater": s.get("theater"),
                    "source_url": s["source_url"],
                    "source_title": s.get("title", ""),
                    "published_on": s.get("published_on"),
                    "date_status": s.get("date_status"),
                    "attribution": s.get("attribution"),
                    "attribution_reason": s.get("attribution_reason"),
                    "topic": j["topic"], "claim": j["claim"],
                    "reasoning": j["reasoning"], "evidence": j["evidence"],
                    "data": j.get("data", []),
                    "direction": j["direction"],
                    "horizon": j.get("horizon", "未指明"),
                    "confidence": j.get("confidence", "medium"),
                    "extracted_on": today,
                })
                print(f"  [{i}/{len(stage3)}] {s['kol']} ✓ {j['direction']} | "
                      f"{j['topic'][:24]} | 论据{len(j['evidence'])} 数据{len(j.get('data',[]))}")
        if i % SAVE_EVERY == 0:
            dump(out_path, results)
        if i % 20 == 0:
            el = time.time() - t0
            eta = (len(stage3) - i) * el / i / 60
            print(f"  ── 进度 {i}/{len(stage3)}｜合格 {len(results)}｜"
                  f"已用 {el/60:.0f}min｜ETA {eta:.0f}min", flush=True)
        time.sleep(GAP)

    dump(out_path, results)
    dump(os.path.join(DATA, f"removed_directory_{today}.json"), rm_dir)
    dump(os.path.join(DATA, f"removed_nobody_{today}.json"), rm_body)
    dump(os.path.join(DATA, f"removed_no_thesis_{today}.json"), rm_nothesis)

    el = time.time() - t0
    print(f"\nLLM 阶段 {el/60:.1f} 分钟（{el/max(1,len(stage3)):.1f}s/条），失败 {errs}")
    print(f"合格言论 {len(results)} 条 → {out_path}")
    print(f"剔除留痕：名录 {len(rm_dir)} / 无正文 {len(rm_body)} / 无判断 {len(rm_nothesis)}")
    if cands:
        print(f"合格率 {len(results)}/{len(cands)} = {100*len(results)/len(cands):.0f}%")


if __name__ == "__main__":
    main()
