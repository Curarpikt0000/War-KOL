---
name: kol-attribution-homonym-guard
description: Use when scraped hits must prove they are that person.
version: 1.0.0
author: Hermes (Chao's agent)
license: internal
metadata:
  hermes:
    tags: [scraping, attribution, data-quality, kol, dedup]
    related_skills: [llm-batch-via-local-proxy, monitoring-pipeline]
---

# 归属校验：拦住「同名的另一个人」

面向「把公开检索结果归到具体人头上」的采集管道（KOL 言论追踪、
分析师观点库、作者监控）。

## When to Use
- 抓取结果要写进「某人说了什么」的库
- 库里出现与主题无关的条目，但标题里确实有那个人名
- 设计新的 KOL / 作者抓取管道

---

## 核心：一道闸不够，必须两道

大多数人只写第一道：

```python
if kol_name.lower() in (title + summary).lower():
    accept()          # ← 同名者直接穿透
```

**同名的另一个人当然也有这个名字。**
实测（War-KOL 2026-09-02，647 条中灌进 25 条垃圾）：

| 名册里的人 | 混进来的同名者 | 条数 |
|---|---|---|
| `Sushant Singh`（印度军事分析师） | Sushant Singh **Rajput**（已故宝莱坞演员） | 8 |
| `Nan Tian`（SIPRI 军费学者） | 南天寺庙 / 民宿 / 古筝曲 | 5 |
| `Todd Harrison`（国防分析师） | Todd Harrison **J.D.**（食药律师） | 2 |

正确结构：

```python
def filter_hits(kol, hits):
    for h in hits:
        good, reason = check(kol, h)           # 道 1：是不是这个「名字」的？
        if good:
            is_h, why = homonym_check(kol, h)  # 道 2：是不是「同一个人」？
            if is_h:
                good, reason = False, why
```

顺序不能反。接在 `filter_hits` 里而不是各个抓取脚本里——调用方自动生效。

---

## 第二道闸的三条判据（通用规则，非硬编码个案）

### A. 外行业身份标记 + 无本领域锚词

两个条件**缺一不可**——只有「既像别的行业、又完全不像本领域」才判。

```python
HOMONYM_MARKERS = ["bollywood", "actor ", "cricketer", "transfermarkt",
                   "fda ", "dietary supplement", "homestay", "temple"]
DOMAIN_ANCHORS  = ["defense", "military", "missile", "conflict", "osint"]

blob = (title + " " + summary).lower()
if any(a in blob for a in DOMAIN_ANCHORS):
    return False, ""                       # 就是本领域，放行
marks = [m for m in HOMONYM_MARKERS if m in blob]
if marks:
    return True, f"同名者：命中外行业标记「{marks[0]}」且全文无本领域用语"
```

### B. 业务性质上不可能承载该领域内容的域名

```python
NEVER_HOSTS = ("agoda.", "booking.com", "tripadvisor.", "airbnb.",
               "transfermarkt", "flashscore", "imdb.com")
```

★ 这条**不依赖语言**。实测漏网过一条**泰语版民宿页**——
英文关键词全落空，域名判据一发即中。

### C. 综合娱乐聚合站的人物专题页

```python
AGG_HOSTS = ("news18.com", "indiatimes.com", "vogue.", "wionews.com")
if any(h in url for h in AGG_HOSTS) and re.search(r"/(topics?|tags?|authors?)/", url):
    return True, "同名者：综合聚合站人物专题页"
```

★ **只限综合/娱乐聚合站**。曾对所有 `/topics|/author` 路径生效，
把 RAND 出版物页、Foreign Policy 作者页这类**合法信源**也误杀了。

---

## ★★ 两条看着对、实测错的路——别再试

### ✗ 主题词白名单（不含 war/missile 就拒）

直觉上最自然，实测 **误杀 96 条合法条目**（647 中的 15%）：
委内瑞拉人权案、SIPRI 军费研究、ACLED 冲突数据统计——
这些**本就不含**那些词，却是真正的领域内容。
**根因**：领域内容的词汇分布比你以为的宽得多。

### ✗ 「姓名被扩展成更长全名就判同名者」

看上去很本质（Sushant Singh → Sushant Singh **Rajput**），
实现时正则会把姓名后**任意一个词**当成姓氏：

- 「Bellingcat 创始人 **Eliot Higgins interview**」→ 判死
- 「**Alex de Waal described** 加沙饥荒」→ 判死

停用词白名单补不完（interview/explains/described/publication…）。已撤除。

---

## 为什么宁漏判不误杀

- 漏判：库里多几条脏数据，前端可标注、事后可清
- 误杀：**真数据永久丢失**，而且你不知道丢了什么

每加一条规则，先**干跑全库**逐条看命中名单：

```python
for r in all_records:
    is_h, why = homonym_check(roster.get(r['kol']), r)
    if is_h:
        print(r['kol'][:20], '|', r['title'][:56], '|', why)
```

我实测时靠这个循环才发现两版规则误杀——**没干跑就上线就晚了**。

---

## 清理已入库的污染

三条纪律：
1. **默认 dry-run**，`--apply` 才真改
2. **移出不是删除**：落盘 `removed_<date>.json` 留痕，改前 `.bak`
3. **删数据前问人**，列出条数与样例让对方拍板

★ 同日多次运行的留痕文件必须**累加不覆盖**。
实测踩过：首轮清 23 条、次轮清 2 条，固定文件名让第二次把第一次冲掉，
最后靠 `git show HEAD:<file>` 差集重建。
**任何按日期命名的产出文件，都要想一下同日重跑会怎样。**

---

## 发现污染的入口

污染难主动发现，因为每条看起来都「有名字、有链接」。三个有效入口：

1. **渲染后看一眼**——实测就是看 dashboard 截图时发现一条
   「Venable 律所 FDA 组联席主席简介」挂在国防分析师名下，顺藤摸瓜查出 25 条
2. **按人分组看标题列表**，同一人下面风格突变的一眼能看出
3. **域名分布**：出现 vogue/agoda/transfermarkt 这类域名就该警觉

---

## 落地清单

- [ ] `filter_hits` 里两道闸都在，顺序正确
- [ ] 外行业标记与领域锚词**双条件**，不是单条件
- [ ] 域名黑名单覆盖订房/点评/体育类（不依赖语言）
- [ ] 聚合站判据只限娱乐/综合站，不误伤智库作者页
- [ ] 新规则上线前干跑全库，逐条看命中名单
- [ ] 清理脚本默认 dry-run + 留痕累加 + 改前 `.bak`
