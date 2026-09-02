# War-KOL 上下文日志

## 2026-09-02（项目从零建成并上线）

### 决策（均为 Chao 拍板）
- 建 War KOL 项目，参照三个既有项目：Eco KOL 板块构成 + Forecast 雷达图 + Forecast 时间线
- 名册「控制在 60 以内」「真正重要的需要评分星级」「要真的做的很专业，准确，有翔实数据的 KOL」
- 日报时间定 **09:00 JST**（开工前先看）
- 视频里的 YouTube 博主（听风的蚕）与他提到的伊朗人（Babak Taghvaee）**都加入**
- 南亚只有 2 人达 3★ → **放宽到 2★ 补至 5 人**，卡片标「区域代表·评分较低」
- backfill **一年**
- 「一直到所有完成，发布给我看看」→ 授权建 repo 并发布

### 改动（实际落地）
- `~/Projects/War-KOL/` 全套：AGENTS.md / README.md / data/README.md / 12 个脚本
- Notion 4 DB（War KOL List / By Day / By Week / By Month），父页 War KOL
- 名册 65 行（Active 62 + 备选 3），言论 411 条已写入 By Day
- 公网 repo `Curarpikt0000/War-KOL` + GitHub Pages 上线
- 内网 ChaoProjects/War-KOL/ 子目录同步
- 5 个 cron：daily 09:00 / weekly 周六 09:00 / monthly 月初 09:00 /
  selfheal 每小时:35 / context-distill 05:15
- `~/.hermes/project_topic_map.json` 补 `-1003988268482:56995 → War-KOL`

### 踩坑与教训（最有价值的部分）

**1. 子 agent 靠 summary 回传结果 = 数据必丢**
第一轮 5 个子 agent 全部 900s 超时。真因不是网络慢，而是它们**自作主张又向下派了孙 agent**，
孙 agent 全部 `status=completed` 正常交货，但产物只存在于 summary 字符串里，
被截断（transcript 里只剩 `+57422 chars` 的标记），state.db 和磁盘上一条都没有。
→ **正解：强制子 agent 每完成 3-4 项就 write_file 落盘**，并禁止再向下嵌套。
第二轮改完，5 个全部 completed，134 条记录一条不丢。

**2. 归属校验是刚需，不是锦上添花**
检索引擎对中文名/音译名（如「听风的蚕 / Zhu Weiyi」）会让引号短语失效，
退化成主题词搜索 → 抓回 CSIS/FPRI 的英文智库文章、同名者的 LinkedIn。
加校验前该 KOL 抓到 13 条**全是假归属**，加校验后 0 条（如实标 not_found）。
→ **不校验就入库 = 往库里灌垃圾，比没有数据更有害。**

**3. f-string 循环里的变量残留**
`source_url` 误用了循环外残留的 `url` 变量，导致一个人所有条目的 URL
全指向同一个错误链接（标题写 Key.Aero，URL 却是 ynetnews）。
→ 抽查时要**交叉核对标题域名与 URL 域名是否一致**，只看条数发现不了。

**4. 星级不能在入选后的子集里重算**
先在 123 人池定星、再选 62 人是对的；反过来在 62 人里切百分位，
会把 7.9 分（全池前 30%）的人标成 1★，自相矛盾且违背「只收 3★ 以上」。

**5. 日期核实率靠摘要抽取只有 14%**
补两级抽取后到 **49%**：① URL 路径（`/2026/09/02/` 是新闻站通用惯例，免费瞬时）
② 页面 `<time datetime>` / `datePublished` meta（慢但准）。
仍抽不到的**留空标 unverified，绝不用 collected_on 顶替**。

**6. 红线扫描真的会拦住东西**
publish.sh 第一次跑就命中：AGENTS.md 含内网 monorepo 路径。
→ AGENTS.md 加进 .gitignore，只随 rsync 进内部端，公网侧用 README.md 说明项目。

**7. build_notion_dbs.py 遇同名 DB 是复用不改 schema**
后加字段（Watchlist / Quality Flag）必须用单独的 patch_notion_schema.py。

### 待办
- [x] ~~方向分类 78%「未表态」~~ → 仍存在（782 条里 628 条＝80%），未改口径，如实呈现
- [ ] 3 位 3★ 够格者（Oryx、Tal Inbar、Charles Lister）因南亚保底占额被标
      Active=false 备选，Chao 可在 Notion 勾 Active 启用（实测三人当前仍 0 条言论）
- [ ] 听风的蚕本轮 0 条（归属校验全拒）。其内容在 YouTube，需专门的
      YouTube 频道抓取通道才能覆盖

---

## 2026-09-02（续：地图钻取 → 全站中文化 → 同名污染清理）

### 决策
- **Chao**：「地图上的点应该是可以打开的……出现一个 list，可以按列表排序，然后我可以双击点开」
  → 地图气泡与战区表格行都做成可点，弹出该战区言论列表（表头排序 / 搜索 / 日周月全档位 / 双击展开详情）
- **Chao**：「所有 KOL 整体卡片以及每日、每周、每月卡片全部翻译成中文；在弹出原文之前必须符合
  三级点开逻辑：① 中文 title ② 点进去看翻译后的言论总结 ③ 再点开才是真正的原文。
  现在做的还差很远，重新做一下」→ 全站中文优先 + 严格三级钻取
- **Chao**：发现 9 条同名者误抓后选 **A 方案** ——「删掉这 9 条 + 给 attribution.py 加同名排除规则」
  （agent 给的三选项：A 删+治本 / B 只删 / C 只标注）
- **Chao**：「i can approve now」→ agent 重试 AGENTS.md 写入，但弹窗仍两次未送达，按协议停止
- **agent 判断**：不硬编码 Rajput/Venable 个案，改用三条通用判据（见踩坑第 2 条）
- **agent 判断**：子 agent 对比任务超时后不再重派，自己读源码

### 改动
- `scripts/world_map.py` — 气泡加透明热区（`fill=transparent`，半径 `max(r,18px)`）、
  `role=button` + `tabindex=0`；战区表格行可点
- `scripts/build_dashboard.py` — 647 条言论明细从 62 张 KOL 卡片内嵌**抽成全局 `STMTS` 数组**、
  卡片改下标引用（文件 634KB→639KB，多了整套列表功能）；新增战区列表弹层；
  新增统一三级渲染器 `l3Row()`（KOL 弹层 / 战区列表 / 时间线共用）；
  新增「中文译写覆盖率」KPI、升级温度计 section、立场转向 section
- `scripts/translate.py`（新）— 批量中文化，按 `source_url + src_hash` 做键落
  `data/translations.json`，增量只翻新增；串行 + 1.5s 间隔
- `scripts/stance_tracker.py`（新）— 每日落方向快照 `data/stance/<date>.json`，与 7 天前比对出转向
- `scripts/purge_homonyms.py`（新）— dry-run → 逐条核对 → `--apply`，留痕
  `data/removed_homonym_<date>.json`（实测 25 条）
- `scripts/attribution.py` — 加第二道闸门 `homonym_check()`（第 151 行），挂在 `filter_hits` 里，
  所有抓取调用方自动生效
- `scripts/publish.sh` — 红线扫描 + git add 两个清单补入 `world_map.py` / `translate.py` /
  `stance_tracker.py` / `purge_homonyms.py` / `docs/HANDOVER.md` / `docs/PENDING_AGENTS_MD_UPDATE.md`；
  `data/stance/` 纳入 git，`.bak` 排除
- `docs/HANDOVER.md`（新）— 流程图 + 8 个 section 说明 + 数据文件清单 + 9 条坑
- `docs/PENDING_AGENTS_MD_UPDATE.md`（新）— AGENTS.md 待应用内容（审批未通过的替代载体）
- 数据：`data/translations.json` 言论 620 + KOL 62；清理后 `data/statements/` 782 条
- 沉淀：新建 skill `kol-attribution-homonym-guard`；
  `llm-batch-via-local-proxy` 加 reference `translation-batch-pitfalls.md`
- 双端已 push，线上 md5 与本地一致：https://curarpikt0000.github.io/War-KOL/

### 踩坑与教训

**1. 批量翻译 17% 失败率，真因是我的解析太脆，不是配额/网络**
模型在**中文正文里写直双引号**（`宣称的"胜利"`）破坏 JSON 字符串 → `json.loads` 抛错。
双管修：① prompt 写死「JSON 值内禁用直双引号，一律用中文引号」② 解析加正则退路。
修后 160/160 零失败。
另有一条稳定失败：标题形如 `<人名> | <站点名>`（`Nathaniel Raymond | Just Security`），
模型判定「全是专名无需翻译」原样回吐英文，被我的中文校验正确拒绝。
温和提示两轮无效，**第 3 轮换强化提示**（明示「即使全是专名也必须给中文表达」）才收敛 → 644/644。

**2. 同名者污染是第三道归属门（前两道全放行）**
原归属校验只验「正文含姓名 / 命中自有域名」——**同名不同人会完美穿透**。
647 条里揪出 **25 条**（3.9%）：宝莱坞演员 Sushant Singh Rajput 混进印度军事分析师、
FDA 监管律师 Todd Harrison 混进国防分析师 Todd Harrison、SIPRI 军费学者 Nan Tian
撞上同名寺庙/民宿/古筝曲（含一条**泰语**订房页）、同名足球经理的 Transfermarkt 页。
**走过两条弯路，都实测撤掉了**：
- ❌ 主题词白名单（「必须命中战争/国防主题词」）→ 96 条命中里大部分是**合法条目**
  （委内瑞拉人权、SIPRI 军费、ACLED 冲突数据），误杀太狠
- ❌「姓名被扩展成更长全名 ⇒ 同名者」→ 正则把姓名后任意一个词当姓氏，
  把「Bellingcat 创始人某某访谈」「某某谈加沙饥荒」全判成同名者
✅ 最终三条判据：**外行业身份标记 + 无领域锚词（双条件）/ 订房点评类域名 / 娱乐聚合站专题页**。
泰语页漏网提醒：关键词判据是语言相关的，**域名业务性质判据才跨语言**。
URL 路径判据一开始写太宽（拒掉 RAND 出版物页、Foreign Policy 作者页），收紧到只拒娱乐聚合站。

**3. 留痕文件按日期命名，同日二次运行直接覆盖 —— 第一批 23 条记录当场丢了**
`.bak` 也是第二轮的。靠 `git` 里的 HEAD 版本才重建出完整 25 条。已修脚本改为追加合并。
→ **留痕文件的命名必须防同日覆盖**，否则「可恢复」是假的。

**4. 视觉模型的截图指控必须用 DOM 实测复核，误报率不低**
三轮视觉复核里**驳回了 4 条误报**：说「出处列表头错位 6-8px」（实测表头与内容右边界都是
1144px）、说「底部没有渐隐」（mask 存在，只是 18px 太窄）、说「降级两处颜色不一致」
（实测都是 `rgb(163,190,140)`）、说「英文原始字段区显示中文＝翻译坏了」
（registry 里 affiliation/role 建册时本来就是中文）。
但它也**抓对了真问题**：卡片行高不一致（134 vs 154）、弹层底部被视口裁切、
按钮文案不随状态切换、以及**最有价值的那条 —— 揪出 FDA 律师条目，顺藤摸瓜挖出全库 25 条污染**。
→ 视觉模型当**线索源**用，每条都去 DOM 取数核实；最后那条误报里的措辞问题（我把
「未经译写的原始字段」标成「英文原始字段」）其实是我自己的 bug。

**5. 子 agent 派发禁令复发率 100%**
任务书明确写了「禁止嵌套 delegate_task」，子 agent 仍自派孙 agent 并卡死 900s 超时，
产物只在被截断的 summary 里、磁盘零留存 —— 与前一轮**同一个坑**。
两次都是我自己读源码解决的（读 Eco 的 `kol_stance_changes`、AI-News 的 `compute_danger_gauge`）。
→ 「读代码做对比」这类活**不要派**，自己读更快更可靠。

**6. AGENTS.md 审批弹窗连拒 2 次（含 Chao 明说「i can approve now」之后）**
表现是我这侧静默超时，不是 Chao 点了否决。按协议**没有绕路走 terminal**。
改动落成 `docs/PENDING_AGENTS_MD_UPDATE.md`（可直接复制粘贴的四块 markdown + 操作说明）并已 push。

### 待办
- [ ] **AGENTS.md 未更新**：需 Chao 手动贴 `docs/PENDING_AGENTS_MD_UPDATE.md` 里的四块内容
      （归属校验两道闸门 / 三级钻取规范），贴完把 PENDING 顶部状态改「已应用」当墓碑
- [ ] 立场转向 section 首日 0 条（无基线），**2026-09-03 起应出真实数据** —— 次日需验证
- [ ] 方向分类「未表态」占 80%（628/782），未改；要降只能抓正文，成本高
- [ ] Chao 未答的开放问题：是否把「地图钻取列表」模式复制到战区雷达（点雷达轴出列表）
