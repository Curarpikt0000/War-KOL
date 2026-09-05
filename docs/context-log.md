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

---

## 2026-09-03（每日 cron 首个完整自动轮次）

### 执行结果
步骤 0 名册镜像 → 抓取 → 补日期 → 归属复检 → 写 Notion → 中译 → 立场快照 → 双端 push，全链路跑通。
- 名册：Notion 65 行 / active 62，本地 registry 62（无增删）
- 抓取：319 条，有效 311 / not_found 8；归属复检后当日文件 313 条（ok 305）
- 发表日核实：0 → 132/305（43%）；其余留空标 unverified
- Notion By Day：新建 82 / 更新 617，读回 729 行
- 中译增量 85 条，0 失败；缓存 702 条
- 立场快照落盘，基线 2026-09-02，有明确立场者仅 4 位，转向 0 条
- 线上 md5 与本地一致（8ce9f625…）

### 发现并修掉的真 bug：通用平台域名让归属校验形同虚设
`_own_domains()` 从 `primary_url = https://www.youtube.com/@zhuweiyi` 抽出**裸域
youtube.com**，于是**整个 YouTube 的任何页面**都被判为「自有平台域名 → 强归属」。
实测抓回电子音乐人 ZHU 的频道页（标题「ZHU - YouTube」）当成听风的蚕的言论。
同理 `en.wikipedia.org` 一旦进了某人的 sources，就以更高优先级**绕过了
DENY_DOMAINS**，把「At sign - Wikipedia」这类词条当本人发言。

修法（`scripts/attribution.py`）：
1. 新增 `GENERIC_PLATFORM_HOSTS`（YouTube/X/Wikipedia/Medium/Substack…）
2. 命中通用平台时**不再只看域名**，必须在 URL 里找到 `_account_tokens()` 抽出的
   账号标识（handle / 频道 id）；找不到就退回姓名判据，不直接放行

★ 教训：**「自有域名」这条捷径只对机构自有站点成立**（csis.org、acleddata.com），
对通用 UGC 平台必须精确到账号。这是归属校验的**第三道闸门**，前两道都放行了它。

### 新增 scripts/revalidate_attribution.py
判据升级后历史文件不会自动失效 —— 旧数据会继续在 dashboard 上展示。
新脚本用当前判据重跑全量已入库条目，默认 dry-run，`--apply` 才落地并累加留痕到
`data/removed_attribution_<date>.json`。首轮剔除 15 条（3 个文件，全部是
Wikipedia 词条页 + 1 条同名 YouTube 频道）。
`publish.sh` 的 SCAN_FILES / git add 两个清单已同步补入新脚本与留痕文件。

### 待办
- [ ] 归属校验建议再补一道：`enrich_dates.py` 的 `--file` 参数只接受**文件名**不接受
      路径（传路径会拼成 data/statements/data/statements/…），易踩，可加个 basename 兜底
- [ ] 立场转向仍 0 条：有明确立场的 KOL 只有 4 位，样本太小。根因还是「未表态」占 80%
- [ ] 本轮 9 位 KOL 零产出（含听风的蚕，其 YouTube 通道仍缺）


---

## 2026-09-03 晚（Chao 质疑内容质量 → 五要素抽取管道上线）

### Chao 的两条指令
1. 「你怎么会出现很多什么圣战主义研究网站的这些言论？请把什么圣战主义研究学院、
   学者简介这些内容全部删掉」
2. 「每一条言论你都必须提供明确的主题、论点、论证、论据以及相关数据……
   否则这个消息没有任何意义」「言论具体的内容需要见解放入第2层点开的内容里，
   你很多点开之后没有内容」

### 根因（体检 1086 条得出）
旧管道 `fetch_statements.py` 把【搜索引擎结果】直接当言论入库：
- 只做归属校验（这条是谁说的），**从不校验「这一条是不是一个判断」**
- `quote` 字段全库 1086/1086 全空 —— **从来没抓过一次正文**
- 所谓 summary = 搜索引擎 description，平均 226 字符的背景描述
- 名录/简介/索引页 274 条（25%）；Aaron Y. Zelin 11 条里 10 条是简介
  （jihadology.net 那句「圣战原始素材资料库」是网站 slogan，不是他的发言）
- 方向 82% 判「未表态」—— 分类器只能扫标题关键词，因为没有正文

### 新增 scripts/extract_thesis.py（三道闸）
- 闸1 名录页过滤：URL 路径段（/experts/ /people/ /author/ /tag/…）+ 站点首页
      + 标题特征（「人名 | 机构名」）。纯规则零成本，剔除 226
- 闸2 正文抓取（requests + BeautifulSoup，并发 8）。抓不到直接剔除，剔除 199
      —— Chao 明确选「直接剔除」，不做「仅存目」区
- 闸3 LLM 抽七要素（topic/claim/reasoning/evidence/data/direction/horizon/
      confidence），找不到本人判断输出 skip。剔除 136
- `validate()` 是**建立前的硬门禁函数**（缺字段/论据<2/论证<40字直接判不合格），
  不是靠「记得检查」——教训见 memory

### 实测结果
- 699 去重候选 → **138 条合格（20%）**，47 位 KOL，LLM 零失败，51 分钟（11.2s/条）
- 论据均 4.7 条/条，数据均 2.9 条/条，81% 条目带确切数字
- **方向分布翻转**：升级 48 / 僵持 47 / 降级 21 / 未表态 22
  —— 未表态从 82% 降到 **16%**（LLM 读了正文，不是扫标题）
- 手工剔 1 条同名污染：Todd Harrison 的 yahoo 财经股评（军工分析师同名者）

### 渲染层改造
- `build_dashboard.py` 加 `load_thesis()` + main() 里的硬门禁（无五要素不进 STMTS）
- STMTS 行从 11 字段扩到 17（+ claim/reasoning/evidence/data/horizon/confidence）
- **方向以抽取结果为准**，覆盖关键词分类器的判断
- 新增 `thesisHTML()` —— L2 的唯一渲染器。原先战区列表弹层自己另写了一份 L2，
  正是「改一处漏两处」的原型，已合并
- 新增 CSS `.th-*` 一组：论点做带左边框的高亮块，数据做 metric/value/context 三列

### 我犯的错
用 `nohup ... &` 起后台任务，Hermes 报 exited，我据此判断进程死了 → 重启一个，
结果**两个进程同时跑写同一产物文件**，日志出现 [25/273] 和 [25/274] 交错。
判据应该是 `pgrep`，工具报的 exited 只是包装 shell 退了。已 kill 旧进程，
脚本自带断点续跑没有重复烧配额。

### 待办
- [ ] 199 条「抓不到正文」里有付费墙（NYT/FT），值得试浏览器抓取或换 Exa key
- [ ] 立场转向仍需累积基线，样本从 4 位扩到 47 位后下轮应出真实数据
- [ ] AGENTS.md 仍未更新（PENDING_AGENTS_MD_UPDATE.md），本轮又多两条待写：
      五要素门槛 + thesisHTML 唯一渲染器

---

## 2026-09-04（补记 09-03 白天菜单/钻取整改 + 凌晨上线确认）

> 前一条 09-03 记录只覆盖了 cron 轮次与当晚的五要素管道，**白天这一轮
> 「菜单顺序 + 三级钻取全覆盖」漏记**，本条补上；末尾是 09-04 凌晨的上线核验。

### Chao 的指令（原话要点）
1. 「左边的 menu 顺序和右边的图是不一致的……所有的都要保持一致，不能有跳动感」
2. 「你再逐一确认一下，每一个表是不是都有三级点开这样的功能？**每一个表都要确认到**」
3. 凌晨追问「新版已经上线了么」——要的是线上实证，不是我说「已发布」

### 改动（scripts/build_dashboard.py）
- **菜单生成改为严格按 DOM 顺序**：旧实现按 `GROUPS` 定义顺序装桶，
  同组成员被聚到一起 → 与页面真实顺序错位（立场转向 / 战区雷达被调了个），
  往下滚高亮往回跳。现改为顺 DOM 单遍扫描、**相邻同组名才合并，不连续就如实拆两段**。
  代码注释已就地写明理由（`build_dashboard.py` 文件头 + `groupNameOf()` 处）。
- **DOM 顺序重排**：地域类三块（地域走向 / 升级温度计 / 战区雷达）改为相邻，
  「立场转向」下移进言论组。当前 DOM 实序 = 总览 → 地域走向 → 升级温度计 →
  战区雷达 → 立场转向 → 言论卡片 → 事件时间线 → 观点全景（已实测与菜单逐项一致）。
- **补齐 3 个缺三级钻取的 section**（审计后发现）：
  - 升级温度计 `.gg-row` → 点行开该战区言论弹层（复用地图那套）
  - 战区雷达轴标签 `.rd-ax` + 方向分布条 `.dline` → 分别按战区 / 按方向筛选
  - 事件时间线卡片 `.tl-card` → 单条直达
- **弹层支持三种模式**：按战区 / 按方向（`tvOpenDir`）/ 单条直达（`tvOpenOne`），
  副标题统计口径随模式切换；全部加 `role=button` + `tabindex` + `:focus-visible`，键盘可达。

### 踩坑与教训
- **`assert flat == sorted(flat)` 验不出装桶型乱序** —— 合并后下标序列仍单调。
  真判据只能是逐项比对「菜单第 i 项 ↔ DOM 第 i 个 section」。
- **「言论数 623 → 699」不是 bug 是真实新数据** —— 当时怀疑 `.bak` 被当数据读，
  查证后是 09:00 的 cron 已跑完 `daily_2026-09-03.json`（彼时已过午夜）。
  顺带确认 `.json.bak` 不以 `.json` 结尾，不会被 glob 读到。数字异常先分辨
  「口径错」还是「真的新增了数据」。
- ★**程序化验收也会被 CDN 缓存骗** —— headless 浏览器验收报
  `tvOpenDir is not defined`，看着像「新绑定没上线」，实际拿的是 CDN 旧 JS。
  加 cache-buster 查询串（`?t=<ts>`）复测即通过。此前只把 CDN 缓存当作
  「md5 首次 curl 会撞」，这次是它伪装成**功能缺失**。
- 09-04 凌晨的上线核验用了**三重判据**：线上 md5 == 本地 `index.html` /
  `dashboard/index.html`、页面页脚生成时间对得上最后一次 commit、
  个人端 remote HEAD == 本地 HEAD。三条都过才回「已上线」。

### 待办
- [ ] `AGENTS.md` 仍未更新（`docs/PENDING_AGENTS_MD_UPDATE.md`，状态仍为「待应用」）。
      审批弹窗已两次静默超时，按协议未绕 terminal；待 Chao 在屏幕前时同轮触发。
      待写内容已累积 4 块：归属校验闸门、三级钻取规范、五要素门槛、thesisHTML 唯一渲染器。
- [ ] 199 条「抓不到正文」中的付费墙（NYT / FT）救回方案：浏览器抓取或换 Exa key
- [ ] `enrich_dates.py --file` 仍只接受文件名不接受路径（已确认脚本内无 basename 兜底）
- [ ] 立场转向：有明确立场者已从 4 位扩到 47 位，需下一轮 cron 累积基线后验证是否出真实转向


---

## 2026-09-04 深夜～09-05 凌晨（扩量：138 → 402 条）

### Chao 的指令
「目前言论太少了你觉得能否放宽一点空间，给更多的人物言论放入我们tracker的空间」

### 诊断：瓶颈不在门槛，在上游（假设被实测推翻）
我原以为「门槛太严」，数字不支持：
- **上游候选池只有 815 条、人均 13.4** —— fetch_statements 每人只发 2-3 个 query
- 三人对照实测：加 7 组 query 后唯一 URL 从 18 → 40-72（**2.2-4 倍**）
- 闸3 剔的 134 条逐条归类 LLM 理由：真正该剔的约 48 条（纯新闻 22 + 简介书单 19 +
  同名 4 + 预告 3）判断**是对的**；误杀主要是 **PDF 解析失败 23 条**
  （LLM 说「正文乱码」= 我把 PDF 字节喂给了 HTML 解析器）
- 闸2 的 199 条同样多是技术问题：200但正文<800 有 111 条、PDF 25、YT 30、X 30、真付费墙 65

### 方案 A+B（Chao 选「直接跑完全部」+「论据下限 2→3」，未选 C 放宽判断类型）
**A 修技术漏**
- PDF 走 pymupdf（抽样 12 条可读 58%）
- 正文三层提取：PDF → 严格法(p/li>60) → article/main 宽松兜底（抽样回收 40%）
- 闸1 补 bookshelf/CV/events/webinar/podcast-preview 规则
- MIN_EVIDENCE 2→3（对现有 138 条零损失，最少的正好是 3）

**B 扩大上游**
query 3 组 → 11 组，五族：基础/访谈(interview,testimony)/音频(podcast transcript)/
句式("I think","I expect")/站点定向(warontherocks,foreignaffairs)。节流 0.4s→1.2s 防 429。

### 结果
- 抓取 1332 条 → 全库去重候选 **699 → 1625（2.3 倍）**
- 闸1 剔 478 / 闸2 剔 361 / 闸3 剔 386 → **合格 402 条（25%）**，LLM 零失败
- 论据均 **5.3**/条，数据均 **3.1**/条，**80%** 带确切数字
- 方向：升级 168 / 僵持 120 / 降级 60 / 未表态 54（未表态仅 13%）
- KOL 覆盖 58/62；战区：俄乌 116 / 军工 75 / 中东 72 / 非洲 45 / 印太 37 / 南亚 35 / 拉美 22

### 三个真 bug（都在这轮暴露）
**1. LLM 半死连接导致无限挂起（最严重）**
`urlopen(timeout=180)` 挡不住「socket 已 ESTABLISHED 但服务端永不返回数据」。
实测卡 35 分钟，判据是 **/proc/<pid>/io 计数器纹丝不动**（不是 CPU、不是线程数）。
修法：`socket.setdefaulttimeout(LLM_TIMEOUT)` + finally 显式 close。
★ 教训：我曾从「1 线程 1 socket」推断线程池已结束→在正常跑，**推错了**——
  ThreadPoolExecutor.map 惰性，主线程等第一批结果时本来就只有 1 个活动线程。
  唯一可靠判据是 io 计数器。

**2. 卡死重启白重抓一轮** → 加 `_body_cache_<tag>.json` 正文落盘缓存，
闸2 从 409s 降到 **74s**。缓存 17MB 已加进 .gitignore。

**3. 红线扫描误杀整次 push**：`presto` 撞上播客主持人姓氏 **Preston**
（iheart.com/podcast/...preston-s-287975507）。修法 = 加词边界 `\bpresto\b`，
**不是放宽关键词**。已用 7 行样本验证：真泄漏全拦、Preston/prestomanifest 正确放行。

### 另两处修正
- `load_thesis()` 误读 `_body_cache_*.json` → AttributeError。改成只认 `thesis_*.json` + 类型守卫
- 同名污染：新 query 里的 interview/podcast/commentary 把同名音乐人、小说家捞进来
  （Jeffrey Lewis 音乐人/小说家、Todd Harrison 股评人）。闸3 挡住了但白烧配额；
  手工剔 Todd Harrison 2 条财经稿（yahoo/newsday），defensenews 那条是真国防分析保留

### 我犯的错（记录以免重复）
上一轮我报「零产出、卡在 138 条」是**错的**——实际已跑出 208 条，
是产物文件按 SAVE_EVERY=5 落盘导致读数滞后。已加每 20 条打印进度+ETA 的日志。

### 待办
- [ ] 同名污染前置：扩量 query 让它变多了，考虑在闸1 加「KOL 领域词 vs 标题主题词」预筛
- [ ] 真付费墙 65 条（NYT/FT）仍未攻，需浏览器抓取或 Exa key
- [ ] 带日期只有 160/402（40%），发表日核实率仍是短板
