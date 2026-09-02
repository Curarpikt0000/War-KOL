# PENDING：AGENTS.md 待追加内容（审批弹窗两次未送达）

> 状态：**待应用**
> 生成：2026-09-02 JST
> 原因：`AGENTS.md` 是 protected 文件，两次审批弹窗均超时未送达 Chao，
>       按协议不绕路走 terminal 写入。请 Chao 手动贴入或在弹窗送达时授权。

## 怎么用

打开 `~/Projects/War-KOL/AGENTS.md`：

1. **替换**现有的整节 `## 数据纪律`（原文见下方「原文」块），
   换成「新内容 A」。
2. 在其后**依次追加**「新内容 B / C / D」三节。

---

## 原文（要被替换掉的整节）

```markdown
## 数据纪律
- **绝不编造**：抓不到标 status，不臆造言论/日期/出处。
- 每条言论锚 `source_url`，可追溯。
- 「最新言论」按 KOL **实际发表日** 分档，不是抓取日；发表日查不到的留空标
  `date_status=unverified`，**绝不用 collected_on 顶替**（Forecast-Checker 教训）。
- ★**幂等 upsert 必须 skip_none**：抓不到时不能把 Notion 已有真值 PATCH 成空
  （Eco 的 BofA 类回归根因）。
```

---

## 新内容 A —— 替换上面那节

```markdown
## 数据纪律
- **绝不编造**：抓不到标 status，不臆造言论/日期/出处。
- 每条言论锚 `source_url`，可追溯。

### ★ 归属校验必须两道闸门（Chao 2026-09-02 批准，实测教训）
`attribution.filter_hits()` 里顺序固定、缺一不可：
1. `check()` —— 这条是不是这个**名字**的？（自有域名 / 正文含姓名 / 名录站拒绝）
2. `homonym_check()` —— 这个名字是不是**同一个人**？

只有第 1 道时，**同名者直接穿透**。实测灌进 25 条垃圾：印度军事分析师
`Sushant Singh` ← 同名宝莱坞演员 Sushant Singh **Rajput** 的娱乐报道 8 条；
SIPRI 军费学者 `Nan Tian` ← 南天寺庙 / 民宿 / 古筝曲 5 条；国防分析师
`Todd Harrison` ← 同名食药律师 Todd Harrison **J.D.**（Venable 律所 FDA 组）2 条。

`homonym_check` 的三条判据（**都是通用规则，不是硬编码个案**）：
- 命中外行业身份标记（bollywood/actor/FDA/homestay…）**且**全文无本领域锚词
- 域名按业务性质不可能承载军事言论（agoda/tripadvisor/transfermarkt/flashscore…）
  —— 这条不依赖语言，专治别国语言页面（曾漏网一条泰语版民宿页）
- 综合娱乐聚合站的人物专题页（news18/vogue/indiatimes 的 `/topics|/tags|/author`）

**两条走过弯路、别再试**：
- ✗「战争主题词白名单」（不含 war/missile 就拒）→ 实测**误杀 96 条合法条目**
  （委内瑞拉人权案、SIPRI 军费研究、ACLED 冲突统计本就不含这些词）。
- ✗「姓名被扩展成更长全名就判同名者」→ 正则把姓名后任意一个词当姓氏，
  「Bellingcat 创始人 Eliot Higgins 访谈」「Alex de Waal 谈加沙饥荒」全被判死。
- **宁可漏判也不误杀真数据**。清理走 `scripts/purge_homonyms.py`
  （默认 dry-run，`--apply` 才写；移出者落盘 `data/removed_homonym_<date>.json`
  **同日多次运行累加不覆盖**——固定文件名曾让第二轮把第一轮记录冲掉）。

- 「最新言论」按 KOL **实际发表日** 分档，不是抓取日；发表日查不到的留空标
  `date_status=unverified`，**绝不用 collected_on 顶替**（Forecast-Checker 教训）。
- ★**幂等 upsert 必须 skip_none**：抓不到时不能把 Notion 已有真值 PATCH 成空
  （Eco 的 BofA 类回归根因）。
```

---

## 新内容 B —— 追加

```markdown
## ★ 三级钻取（Chao 2026-09-02 拍板，全站统一，不得例外）
所有言论条目与 KOL 卡片一律：
1. **L1** 中文标题（未翻译的显示英文原标题 + 「待翻译」标，不用机翻冒充）
2. **L2** 中文言论总结（LLM 译写要点）
3. **L3** 英文原文摘要 + 原始出处链接

落地位置：`build_dashboard.py::l3Row()` 是**唯一渲染器**，KOL 弹层 / 战区列表 /
言论卡片三处共用——各写一遍必然改一处漏两处（Eco 踩过）。

翻译走 `scripts/translate.py` → `data/translations.json`（按 source_url / KOL 名
做键 + 存 `src_hash`，**增量翻译**，每日 cron 只翻新增，不重复烧配额；
全量 647 条约 25 分钟，增量通常几十秒）。
- **串行 + 1.5s 间隔，不要改并发**（本机 genai 代理并发必 429，
  见 skill `llm-batch-via-local-proxy`）。
- 校验必须**扫全量**（非中文条数 == 0），不是抽查几条看着像中文就过。
- ★两个实测坑：① 模型在中文正文里写直双引号（如 宣称的"胜利"）会破坏 JSON →
  `parse_json_blob()` 有正则退路兜底，修好前失败率 17%、修好后 0%；
  ② 标题是「人名 | 站点名」这类纯专名时模型会原样回吐英文、重跑无效 →
  第 3 轮起换强化提示要求改写成中文描述句。
```

---

## 新内容 C —— 追加

```markdown
## 立场转向与升级温度计（2026-09-02 加）
- `scripts/stance_tracker.py` 每日落一份方向快照 `data/stance/YYYY-MM-DD.json`，
  与 7 天前比对出「谁改了判断」→ `data/stance_changes.json`。
  **快照目录必须进 git**（publish.sh 已加 `git add -A data/stance/`），
  删了就没法算转向。快照不足 2 份时返回空并标 reason，**绝不编造转向**。
- 主导方向口径：该 KOL 该战区近 30 天言论的方向众数，**排除「未表态」**
  （那是没判断，不是判断中立），众数并列时取最近一条。
- `build_dashboard.py::theater_gauge()` 升级温度计：方向值 × 时效衰减
  （半衰期 30 天）× KOL 星级权重，归一到 -100~+100。同样排除「未表态」。
- 两者都是**确定性脚本**，不交给 LLM 每天现判——否则结果随模型状态漂移。
```

---

## 新内容 D —— 追加

```markdown
## ★ 子 agent 派发禁令（2026-09-02 复发后立）
「读代码做对比分析」这类任务**不要派子 agent**，自己读。
实测复发率 100%：即便 prompt 明写「禁止再向下嵌套 delegate_task」，
子 agent 仍会自派孙 agent 然后卡在等它，900s 超时、零产出。
两次都是最后由主 agent 自己读源码解决的，派出去反而更慢。
```

---

## 应用后

把本文件顶部状态改成 `已应用（<日期>）`，**保留文件不删**（墓碑，供追溯）。
