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
    """分流：(归属确认, 存疑)。

    ★ 两道闸门，顺序不能反：
      1) check()        —— 这条是不是这个「名字」的？
      2) homonym_check() —— 这个名字是不是「同一个人」？
    只过第 1 道会让同名者直接穿透（2026-09-02 实测灌进 23 条娱乐/法务/旅游
    垃圾），所以第 2 道是必需的，不是锦上添花。
    """
    ok, unsure = [], []
    for h in hits:
        good, reason = check(kol, h)
        if good:
            is_h, hy = homonym_check(kol, h)
            if is_h:
                good, reason = False, hy
        h["attribution"] = "verified" if good else "unverified"
        h["attribution_reason"] = reason
        (ok if good else unsure).append(h)
    return ok, unsure


# ── 同名者（homonym）识别 ──────────────────────────────────
# ★ 2026-09-02 实测发现的漏网场景：姓名匹配成功，但那是【同名的另一个人】。
#   实例：① 印度军事分析师 Sushant Singh ← 混入已故宝莱坞演员 Sushant Singh
#         Rajput 的娱乐报道 7 条；② 国防分析师 Todd Harrison ← 混入同名食药
#         律师 Todd Harrison J.D.（Venable 律所 FDA 组）2 条。
#   旧校验只问「正文里有没有这个名字」，同名者当然也有 → 直接穿透。
#
# 为什么不用「战争主题词白名单」：实测会误杀 96 条合法条目（委内瑞拉人权
#   案、SIPRI 军费研究、ACLED 冲突数据统计等本就不含 war/missile 等词）。
#   宁可漏判也不能误杀真数据。
#
# 改用「职业身份冲突」判据：本项目 KOL 全是安全/国防/地缘领域从业者，
#   若条目把这个名字明确标注成**另一个明显无关行业的身份**，即判同名者。
#   只列与本领域绝无重叠的行业，且要求出现在【姓名近旁】，避免误伤
#   （如一篇军事文章顺带提到 "actor" 一词不该被判死）。
HOMONYM_MARKERS = [
    # 娱乐 / 体育
    "bollywood", "hollywood", "tollywood", "filmfare", "box office",
    "actor ", "actress", "singer", "rapper", "celebrity", "movie star",
    "cricketer", "footballer", "transfermarkt", "injury history",
    "police forces probe", "death case", "cbi probe", "photos about",
    "latest news & videos", "manager profile",
    # 食药 / 消费法务（与国防法务不同）
    "fda ", "self-gras", "dietary supplement", "food safety",
    "food and dietary supplement", "labeling and advertising claims",
    # 生活服务 / 旅游 / 宗教场所
    "homestay", "hotel", "guzheng", "temple", "skincare",
]
# 出现这些词说明【就是本领域】，即便同段落有上面的词也不判同名者
DOMAIN_ANCHORS = [
    "defense", "defence", "military", "war", "security", "geopolit",
    "missile", "nuclear", "conflict", "osint", "intelligence", "army",
    "navy", "air force", "strateg", "sanction", "nato", "pentagon",
    "国防", "军事", "战争", "导弹", "安全", "地缘",
]


def homonym_check(kol, hit):
    """(is_homonym, reason)：这条是不是同名的另一个人？

    判据：命中明确的外行业身份标记，且全文找不到任何本领域锚词。
    两个条件缺一不可——只有「既像别的行业、又完全不像本领域」才判。

    ★ 曾试过第二条判据「姓名被扩展成更长全名就算同名者」，实测**误杀严重**：
      「Bellingcat 创始人 Eliot Higgins 访谈」「Alex de Waal 谈加沙饥荒」
      这类合法条目都被判死（正则把姓名后任意一个词都当成姓氏）。
      已撤除。宁可漏判也不误杀真数据——漏掉的少量脏数据由标注层兜底。
    """
    blob = (f"{hit.get('title','')} "
            f"{hit.get('description') or hit.get('summary','')}").lower()
    if any(a in blob for a in DOMAIN_ANCHORS):
        return False, ""
    marks = [m for m in HOMONYM_MARKERS if m in blob]
    if marks:
        return True, f"疑似同名者：命中外行业标记「{marks[0].strip()}」且全文无本领域用语"
    # 某些域名按业务性质就不可能承载军事言论（订房/点评/票务/电商），
    # 且这类页面常是别国语言（实测漏网一条泰语版民宿页，英文关键词全落空）
    # → 直接按域名拒，不依赖语言。
    NEVER_HOSTS = ("agoda.", "booking.com", "tripadvisor.", "airbnb.",
                   "expedia.", "trip.com", "hotels.com", "ctrip.",
                   "transfermarkt", "flashscore", "imdb.com")
    url = (hit.get("url") or hit.get("source_url") or "").lower()
    if any(h in url for h in NEVER_HOSTS):
        return True, "疑似同名者：订房/点评/体育票务类站点，业务性质上不承载军事言论"
    # 聚合站的「人物专题页」本身不是言论，且极易撞同名者。
    # ★ 只针对综合新闻/娱乐聚合站——曾一度对所有 /topics|/author 路径生效，
    #   把 RAND 出版物页、Foreign Policy 作者页这类合法信源也误杀了。
    AGG_HOSTS = ("news18.com", "indiatimes.com", "timesofindia", "vogue.",
                 "wionews.com", "financialexpress.com", "moneycontrol.com",
                 "outlookindia.com", "inkl.com", "etbrandequity",
                 "flashscore", "transfermarkt")
    if any(h in url for h in AGG_HOSTS) and re.search(
            r"/(topics?|tags?|authors?)/", url):
        return True, "疑似同名者：综合聚合站人物专题页且全文无本领域用语"
    return False, ""
