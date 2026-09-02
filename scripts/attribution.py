#!/usr/bin/env python3
"""归属校验：判断一条检索结果是否【真的出自该 KOL】。

为什么必须有这一层（2026-09-02 样板实测发现）：
  对「听风的蚕 / Zhu Weiyi」这类中文名或音译名，引号短语检索会失效，
  退化成主题词搜索 → 抓回 CSIS / FPRI 的英文智库文章、甚至同名者的
  LinkedIn 页。若不校验就入库，等于往库里灌与本人无关的内容，
  比没有数据更有害。

判据（保守，宁可漏不可错）：
  1) 命中 KOL 自有平台域名（youtube 频道 / x handle / primary_url 域名）→ 强归属
  2) 标题或摘要里出现 KOL 姓名（英文名、中文名、或姓氏+名的任一完整形式）→ 归属
  3) 命中已知的「聚合站/百科/职业社交」域名且无姓名 → 判否
  4) 其余一律判否，标 attribution=unverified，不入库主表（留在 raw 备查）
"""
import re
from urllib.parse import urlparse

# 这些站点即便标题含名字也多半不是本人发言（百科/名录/职业社交/内容农场）
DENY_DOMAINS = {
    "linkedin.com", "wikipedia.org", "wikiwand.com", "facebook.com",
    "instagram.com", "tiktok.com", "amazon.com", "goodreads.com",
    "researchgate.net", "academia.edu", "crunchbase.com", "zoominfo.com",
    "rocketreach.co", "everybodywiki.com", "baike.baidu.com",
}


def _domain(url):
    try:
        h = (urlparse(url).hostname or "").lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def _own_domains(kol):
    """KOL 自有平台域名集合。"""
    out = set()
    for key in ("primary_url", "youtube"):
        d = _domain(kol.get(key) or "")
        if d:
            out.add(d)
    plat = str(kol.get("platforms") or "") + " " + str(kol.get("sources") or "")
    for m in re.finditer(r"https?://([^\s/|,)]+)", plat):
        d = m.group(1).lower()
        out.add(d[4:] if d.startswith("www.") else d)
    return out


def _name_variants(kol):
    """生成用于匹配的姓名变体（去噪：剥掉括号注释与机构后缀）。"""
    vs = set()
    for key in ("name_en", "name_zh"):
        raw = (kol.get(key) or "").strip()
        if not raw:
            continue
        # 剥括号内容：Zhu Weiyi ("Ting Feng De Can") → Zhu Weiyi + Ting Feng De Can
        inner = re.findall(r"[（(\"']([^）)\"']{2,})[）)\"']", raw)
        base = re.sub(r"[（(\"'][^）)\"']*[）)\"']", " ", raw).strip()
        for cand in [base] + inner:
            cand = cand.strip(" ·,-—")
            if len(cand) >= 2:
                vs.add(cand.lower())
    h = str(kol.get("x_handle") or "").strip().lstrip("@")
    if h and h.lower() != "unknown":
        vs.add(h.lower())
    return {v for v in vs if len(v) >= 3}


def check(kol, hit):
    """返回 (attributed: bool, reason: str)。"""
    url = hit.get("url") or hit.get("source_url") or ""
    dom = _domain(url)
    blob = f"{hit.get('title','')} {hit.get('description') or hit.get('summary','')}".lower()

    own = _own_domains(kol)
    if dom and any(dom == d or dom.endswith("." + d) for d in own):
        return True, f"自有平台域名 {dom}"

    variants = _name_variants(kol)
    hit_names = [v for v in variants if v in blob]
    if hit_names:
        if any(dom == d or dom.endswith("." + d) for d in DENY_DOMAINS):
            return False, f"名字命中但域名属名录/百科类（{dom}），非本人发言"
        return True, f"正文含姓名「{hit_names[0]}」"

    if dom in DENY_DOMAINS:
        return False, f"名录/百科类域名 {dom} 且无姓名"
    return False, "标题与摘要均未出现该 KOL 姓名"


def filter_hits(kol, hits):
    """分流：(归属确认, 存疑)。"""
    ok, unsure = [], []
    for h in hits:
        good, reason = check(kol, h)
        h["attribution"] = "verified" if good else "unverified"
        h["attribution_reason"] = reason
        (ok if good else unsure).append(h)
    return ok, unsure
