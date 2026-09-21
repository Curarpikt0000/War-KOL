# War-KOL 交接文档

> 最后更新：2026-09-02（JST）
> 线上：https://curarpikt0000.github.io/War-KOL/
> Telegram topic：Uber 工作组 / thread 56995

给接手的人（或未来的我）：**先读这份，再读 AGENTS.md**。
这份讲「现在长什么样、怎么跑、哪里有坑」；AGENTS.md 讲「规矩」。

---

## 1. 这个项目在做什么

汇总全球战争分析 KOL（军事分析师 / 智库研究员 / OSINT 判读者 / 国防产业分析）
的每日公开言论，判断各战区走势。产出一个**单文件自包含 HTML 看板**，
双端发布（公网 GitHub Pages + Uber 内网 monorepo）。

当前规模：**62 位 KOL / 623 条言论 / 7 个战区**。

---

## 2. 一次完整的日更是怎么跑的

```
scripts/sync_kol_from_notion.py   # 步骤0：名册单向镜像（Notion = SSOT）
  ↓
scripts/fetch_statements.py       # 抓取 + 两道归属校验
  ↓
scripts/enrich_dates.py           # 发表日两级抽取（URL 路径 → 页面 meta）
  ↓
scripts/translate.py              # 增量中译（只翻新增，不重复烧配额）
  ↓
scripts/stance_tracker.py         # 落方向快照 + 与 7 天前比对出转向
  ↓
scripts/build_dashboard.py        # 建 HTML
  ↓
scripts/publish.sh                # 红线扫描 → 双端 push
```

手动全跑一遍：

```bash
cd ~/Projects/War-KOL
python3 scripts/translate.py          # 约 25 分钟（647 条全量）；增量通常几十秒
python3 scripts/stance_tracker.py
python3 scripts/build_dashboard.py
bash scripts/publish.sh
```

---

## 3. 看板有什么（8 个 section）

| Section | 说明 | 实现 |
|---|---|---|
| 总览 | 6 个 KPI（含**中文译写覆盖率**） | `main()` |
| 地域走向 | 世界地图，**气泡可点** → 弹出该战区言论列表 | `world_map.py` |
| 升级温度计 | 各战区加权净升级倾向 -100~+100 | `theater_gauge()` |
| 立场转向 | 谁改了判断（与历史快照比对） | `changes_html()` |
| 战区雷达 | 密度分布 + 方向构成 | `radar_svg()` |
| 言论卡片 | 日/周/月三档，三级钻取 | `statements_pane()` |
| 事件时间线 | 按发表日横向排布 | `timeline_html()` |
| 观点全景 | 62 张 KOL 卡片 → 弹层看档案 + 全部言论 | `kol_cards()` |

### 三级钻取（Chao 拍板，全站统一）
1. **L1** 中文标题
2. **L2** 中文言论总结
3. **L3** 英文原文摘要 + 原始出处

`l3Row()` 是**唯一渲染器**，三处弹层共用。要改就改它一个地方。

### 地图交互
点气泡或下方战区表格行 → 弹出该战区言论列表 → 表头可排序 / 搜索（中英都能搜）
/ 日周月切档 → **双击行**展开详情 → 可一键跳到该 KOL 档案。

---

## 4. 数据文件

| 文件 | 是什么 | 能不能删 |
|---|---|---|
| `data/kol_registry.json` | 名册镜像（SSOT 在 Notion） | 不能，跑镜像脚本重建 |
| `data/statements/*.json` | 抓取到的言论 | 不能 |
| `data/translations.json` | 中译缓存（按 URL 做键 + src_hash） | 可删但会重烧 25 分钟配额 |
| `data/stance/YYYY-MM-DD.json` | 每日方向快照 | 不能，删了就没法算转向 |
| `data/stance_changes.json` | 转向清单（派生） | 可删，重跑即生成 |
| `data/removed_homonym_*.json` | 同名者清理留痕 | 保留备查 |
| `data/notion_ids.json` | DB id（**gitignored**） | 不能进 git |

---

## 5. 血泪坑（按踩到的顺序）

### 5.1 子 agent 靠 summary 回传 = 数据必丢
第一轮 5 个子 agent 全部 900s 超时。真因不是网络慢，是它们**自作主张又向下派了
孙 agent**，孙 agent 全部 completed 正常交货，但产物只存在 summary 字符串里被
截断，磁盘上一条都没有。
→ **强制子 agent 每完成 3-4 项就 write_file 落盘 + 禁止再向下嵌套。**
（2026-09-02 又犯了一次：派去做 dashboard 对比的子 agent 再次自派孙 agent 并超时。
最后是我自己读两个项目源码拿到结论。**这个坑复发率 100%，别再派了，自己读。**）

### 5.2 归属校验要两道闸门，不是一道
只验「正文含姓名」，**同名的另一个人当然也有名字** → 直接穿透，灌进 25 条垃圾。
详见 AGENTS.md「归属校验必须两道闸门」。走过的两条弯路（主题词白名单 / 姓名扩展
判据）都记在那里，**别再试第二遍**。

### 5.3 f-string 循环里的变量残留
`source_url` 误用了循环外残留的 `url`，一个人所有条目 URL 全指向同一个错误链接。
→ 抽查要**交叉核对标题域名与 URL 域名是否一致**，只看条数发现不了。

### 5.4 星级不能在入选后的子集里重算
先在 123 人池定星、再选 62 人是对的；反过来在 62 人里切百分位，会把全池前 30%
的人标成 1★，自相矛盾。

### 5.5 发表日核实率靠摘要抽取只有 14%
补两级抽取后到 49%：① URL 路径（`/2026/09/02/`，免费瞬时）② 页面
`<time datetime>` / `datePublished` meta（慢但准）。
仍抽不到的**留空标 unverified，绝不用 collected_on 顶替**。

### 5.6 publish.sh 的扫描清单必须与 git add 清单同步
`world_map.py` 曾只在 git add 里、不在红线扫描里 = 新文件绕过安全门。已修。

### 5.7 LLM 批处理的两个具体坑
- 模型在中文正文里写**直双引号**（如 宣称的"胜利"）会破坏 JSON →
  `parse_json_blob()` 有正则退路兜底。修好前失败率 17%，修好后 0%。
- 标题是「人名 | 站点名」这类**纯专名**时，模型稳定原样回吐英文，重跑无效 →
  第 3 轮起换强化提示要求改写成中文描述句。
- **串行 + 1.5s 间隔，不要改并发**（本机 genai 代理并发必 429）。

### 5.8 同日多次运行会覆盖留痕
`purge_homonyms.py` 首轮清 23 条、次轮清 2 条，固定文件名让第二次把第一次的
记录冲掉了。已改为累加。**任何按日期命名的产出文件都要想一下同日重跑会怎样。**

### 5.9 视觉复核会误报，必须用 DOM 数据验证
vision 模型报过「出处列表头错位 6-8px」「降级颜色两处不一致」「底部没有渐隐」——
实测 DOM 全部为假（右边界都是 1144px、都是同一个绿、mask 存在只是太窄）。
但它也抓到过真问题（卡片行间高度 134 vs 154、弹层底部被裁、按钮文案不随状态变）。
→ **视觉复核当线索，DOM 实测当判据。**

---

## 6. Cron（JST）

| Job | 时间 | 做什么 |
|---|---|---|
| `war-kol-daily` | 每日 09:00 | 全流程 + Telegram 日报 |
| `war-kol-weekly` | 周六 09:00 | 一周立场变化 |
| `war-kol-monthly` | 每月 1 号 09:00 | 月度走势 + 预测应验回顾 |
| `war-kol-context-distill` | 每日 05:15 | 上下文归档 |
| `war-kol-selfheal` | 每小时 :35 | watchdog（no_agent） |

★ cron prompt **绝不写死 KOL 数量**，一律「读名册取 active==true 的全部」。

---

## 7. 待办

- [ ] 方向分类 78% 是「未表态」——只扫标题+摘要，信息量本就不够。
      要提升需抓正文，成本高。当前如实呈现，未硬凑。
- [ ] 3 位 3★ 够格者（Oryx、Tal Inbar、Rob Lee）因南亚保底占额被标 Active=false，
      Chao 可在 Notion 勾 Active 启用。
- [ ] 听风的蚕本轮 0 条（归属校验全拒）。其内容在 YouTube，需专门的频道抓取通道。
- [ ] 立场转向首日无基线，次日起才有数据。跑满一周后复核判据是否合理。

---

## 8. 改之前必须知道的三件事

1. **名册只读**。增删 KOL 一律 Chao 在 Notion 侧操作，本 agent 只跑单向镜像。
2. **公网端绝不含任何内网信息**。`publish.sh` 有红线扫描，加新文件必须同时
   加进 `SCAN_FILES` 和 `git add` 两个清单。
3. **删数据前先 dry-run + 落盘留痕 + 问 Chao**。所有清理脚本默认 dry-run。
