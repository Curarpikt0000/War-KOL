# data/ 数据字典

每个文件的来源、口径、生成方式。**改动前先读这里。**

## 流水线顺序（不可调换）

```
raw/*.json  →  merge_raw.py  →  candidates_raw.json
                                      ↓
                            select_roster.py（定星+配额）
                                      ↓
                          roster_final.json + candidates_rejected.json
                                      ↓
                        write_roster_to_notion.py（写 Notion 名册）
                                      ↓
                    【此后 SSOT 转移到 Notion，本地只读】
                                      ↓
                   sync_kol_from_notion.py --apply（单向镜像）
                                      ↓
                              kol_registry.json
                                      ↓
                    fetch_statements.py（读 active 全量）
                                      ↓
                          statements/*.json
                                      ↓
              write_statements_to_notion.py + build_dashboard.py
```

**关键**：`roster_final.json` 是**一次性建库产物**。名册定稿写入 Notion 后，
SSOT 就是 Notion —— 日常只跑 `sync_kol_from_notion.py` 反向镜像到
`kol_registry.json`。**不要再跑 select_roster.py 覆盖名册**，那会抹掉
Chao 在 Notion 侧的人工增删。

---

## 文件清单

### `raw/*.json` — 调研原始产出
- 来源：5 个并行子 agent 联网调研（2026-09-02），按战区分文件
- `ukraine.json` 28 · `mideast.json` 25 · `indopacific.json` 24 ·
  `other_theaters.json` 28 · `defense_industry.json` 29 = **134 条**
- 字段：name_en / name_zh / affiliation / role / platforms / x_handle /
  youtube / language / theater / specialty / score_A~D / rating_reason /
  controversies / sources
- 每人至少 1 个可访问 URL；查不到的字段填 `unknown`，**未编造**

### `candidates_raw.json` — 去重合并后的候选池（123 人）
- 由 `merge_raw.py` 生成。134 → 123（合并 11 条跨战区重复）
- **合并口径**：同一人被多组收录时，`theater` 变成**列表**保留全部战区；
  四维分数取各组**最高分**（低分往往是「在我这个领域他不算核心」而非「他不行」）；
  rating_reason / controversies / sources 全部合并保留，信息只增不减
- 9 人跨战区，如 Jeffrey Lewis（中东/军工/印太 3 组）

### `roster_final.json` — 入选名册（62 人，一次性产物）
由 `select_roster.py` 生成。构成：
- **3★+ 核心 57 人**：达入库门槛
- **南亚放宽 3 人**（Chao 2026-09-02 拍板）：南亚达 3★ 者仅 2 人，
  结构性原因——区域战地型分析者在 A（机构根基）/ D（方法透明度）
  两维天然吃亏，即便该领域最权威者也卡在 2★。放宽至 2★ 补至 5 人，
  标 `regional_representative=true` + `quality_flag="区域代表·评分较低"`
- **watchlist 2 人**（Chao 点名纳入）：Babak Taghvaee 4.40（121/123）、
  听风的蚕 2.30（123/123 垫底）。**不占 3★ 名额**，标 `watchlist=true`，
  卡片必须显示低可信度警示

★ **星级在全量 123 人池内定**（百分位口径），绝不在入选后的 62 人里重算——
那 62 人全是头部，再切百分位会把 7.9 分的人标成 1★，自相矛盾。

### `candidates_rejected.json` — 未入选留痕（61 人）
两类：`星级 N★ < 门槛` 和 `够格但未入选（60 人上限）`。留痕备查，日后可提。

### `notion_ids.json` — **gitignored**
4 个 DB 的 id。**脚本禁止硬编码任何 page id**，一律从这里读。

### `kol_registry.json` — 本地名册镜像（62 人）
- 由 `sync_kol_from_notion.py --apply` 从 Notion 单向镜像生成
- **本地独有采集配置**（`search_terms` / `rss` / `last_fetched` / `fetch_notes`）
  在镜像时保留不被覆盖
- ★ **匹配坑**（Eco 项目实测）：Notion 名常带机构后缀。
  正解 = 先全量精确匹配 → 模糊只认「本地名 ⊂ Notion 名」单方向 →
  取最短候选 → 已配对者不再参与模糊。反过来做会让短名抢走长名的行。

### `kol_removed_<date>.json` — 移出留痕
Notion 侧取消 active 的人落这里。**其历史抓取文件一律保留不删**，
日后在 Notion 加回来历史立即可用。

### `statements/*.json` — 言论抓取产物
- `backfill_<date>.json`：一年回补（`--mode backfill --days 365`）
- `daily_<date>.json`：每日增量（`--mode daily --days 3`）
- 字段：kol / theater / title / summary / quote / source_url /
  published_on / date_status / direction / collected_on / status /
  attribution / attribution_reason

**三个必须理解的字段**：

| 字段 | 取值 | 含义 |
|---|---|---|
| `status` | ok / not_found | not_found = 本轮真的没抓到，**如实标注非编造** |
| `date_status` | verified / unverified | unverified 时 `published_on` **留空**，绝不用 `collected_on` 顶替 |
| `attribution` | verified / unverified | 归属校验结果，只有 verified 才入库 |

`direction` = **升级 / 僵持 / 降级 / 未表态**。
语义是「冲突会不会升级」，**不是金融多空**——套多空会失真。
脚本内是关键词粗分类，仅作初筛，真正判定由 cron 里的 agent 复核。

### `statements/rejected_attribution.jsonl` — 归属校验拒绝留痕
★ **为什么必须有这层**（2026-09-02 实测）：
对「听风的蚕 / Zhu Weiyi」这类中文名或音译名，引号短语检索会失效，
退化成主题词搜索 → 抓回 CSIS/FPRI 的英文智库文章、甚至同名者的 LinkedIn。
加校验前该 KOL 抓到 13 条**全是假归属**；加校验后 0 条（如实标 not_found）。
**不校验就入库 = 往库里灌垃圾，比没有数据更有害。**

---

## 已知踩坑（勿重蹈）

1. **ddgs 的 url 字段是 `href` 不是 `url`**；且在循环里必须取
   `hit.get("url")` 而非循环外残留的 `url` 变量——否则一个人所有条目
   `source_url` 全指向同一错误链接（实测：标题写 Key.Aero，URL 却是 ynetnews）。
2. **子 agent 靠 summary 回传结果会丢数据**：第一轮 5 个子 agent 全部 900s 超时，
   孙 agent 明明 completed，但产物只在 summary 里、被截断（`+57422 chars` 被砍），
   一条都没保住。正解 = **强制子 agent 每完成 3-4 项就写文件**。
3. **build_notion_dbs.py 遇同名 DB 是复用不改 schema**，后加字段要用
   `patch_notion_schema.py`。
4. **ddgs 长时间批量会零星 ConnectTimeout**，属正常退避，脚本有增量落盘不会丢；
   重跑时已完成的人会自动跳过。
