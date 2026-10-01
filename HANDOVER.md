# War-KOL 交接文档（HANDOVER）

> 写于 2026-10-01（JST）。接手的 agent **先读本文，再读 AGENTS.md**。
> 本文讲「现在是什么状态、怎么跑、哪里有坑、哪些事不能做」；AGENTS.md 讲「规矩」。
> 本文是公网安全版，不含内网地址与凭证；内网端另有 `HANDOVER_INTERNAL.md`（只在内网 repo）。
> 旧版 `docs/HANDOVER.md`（2026-09-02，当时 62 人/623 条）已过时，以本文为准。

---

## 0. 三十秒读懂

- **做什么**：汇总全球战争分析者（军事分析师 / 智库研究员 / OSINT / 国防产业）的公开言论，按战区判断走势，产出**单文件自包含 HTML 看板**。
- **规模（2026-10-01 实测）**：名册 67 人 / 合格言论 1056 条（按 KOL+出处去重）/ 7 战区 / 看板 19MB。
- **公网入口**：https://war-kol.pages.dev/ （Cloudflare Pages）。旧的 GitHub Pages 地址已死（账号被封，返回 404），**不要再贴**。
- **负责人**：Chao（Uber Sr Ops Manager）。名册增删、星级线、"定稿"页都由他拍板。
- **你接手后每天什么都不用做**：cron 全自动；你只需要在它报警时看懂报警。

---

## 1. 绝对不能做的事（红线，违反会出事故）

1. **绝不自行增删 KOL。** 名册 SSOT = Notion「War KOL List」库。本地 `data/kol_registry.json` **只能**由 `scripts/sync_kol_from_notion.py` 从 Notion 拉，**禁止手改**。
2. **绝不降低五要素门槛去凑数。** 每条言论必须有：主题、论点、论证、论据（≥3 条，`MIN_EVIDENCE=3`）、数据。缺一不入库。合格率通常只有 20–30%，这是**正常的**。
3. **归属规则无例外。** 第三方转述 / 逐字稿不入库；**主持人的提问不是主持人的判断**（FP Live 主持人 Agrawal 就是因此不收）。只收 KOL **本人署名**的判断。
4. **发表日查不到就留空标 `date_status=unverified`，绝不用抓取日（`collected_on`）顶替。**
5. **公网 repo 绝不含内网地址 / 内部标识 / 凭证。** `publish.sh` 有红线扫描；加新文件必须**同时**加进 `SCAN_FILES` 和 `git add` 两个清单。红线关键词只能加词边界 `\b`，**不能放宽**。
6. **凭证只放 `~/.hermes/.env`**，通过环境变量传入，不上命令行、不硬编码、不进 git、不在聊天里回显。
7. **不要跳过 pre-commit hook**（遇到 `no ssh cert is found` 是证书过期，等证书/让 Chao 续，不是绕过）。
8. **删数据前**：先 dry-run → 落盘留痕 → 问 Chao。所有清理脚本默认 dry-run。被剔除的数据一律写到 `data/removed_*` 留痕，历史抓取文件一律保留不删。
9. **`AGENTS.md` 是受保护文件**：写入会弹审批，静默超时 = 拒绝，**不要用 terminal 绕写**。待写入的改动记在 `docs/PENDING_AGENTS_MD_UPDATE.md`（目前 A–E 五块等 Chao 手动贴进去）。
10. **"定稿"的页面只改点名字段**，其余一字不碰；改前必备份。

---

## 2. 系统全景

```
Notion「War KOL List」(SSOT)
  │  sync_kol_from_notion.py --apply          ← 步骤 0，单向镜像
  ▼
data/kol_registry.json (67)
  │  fetch_statements.py --mode daily --days 3   ← 搜索抓取 + 两道归属闸
  ▼
data/statements/daily_<date>.json
  │  enrich_dates.py --fetch-pages              ← 回补发表日（必须在抽取之前）
  │  extract_thesis.py --all --workers 4        ← ★五要素门禁（3 道闸，LLM 串行）
  ▼
data/thesis/thesis_all_<date>.json  + data/removed_{directory,nobody,no_thesis}_<date>.json
  │  build_layers.py                            ← 四层：一句话 / 总结 / 译文 / 出处
  │  write_statements_to_notion.py              ← 幂等 upsert → Notion By Day
  │  build_dashboard.py → publish.sh            ← 红线扫描 → 双端 push → 镜像 → Cloudflare
  ▼
https://war-kol.pages.dev/  +  内网镜像
```

**三道闸（`extract_thesis.py`）**：闸1 剔除人物简介 / 机构名录 / 作者归档页；闸2 抓正文，抓不到（付费墙 / 403 / 过短）直接剔除；闸3 LLM 抽五要素，找不到 KOL 本人判断就剔除。三道的剔除物全部落盘，不静默丢弃。

**为什么 LLM 必须串行**：本机 genai 代理（`localhost:8800`）并发必 429；脚本已内置 1.5s 间隔，**不要改并发**。客户端报 `RemoteDisconnected` 多是上游 429 被代理 log bug 掩盖，服务端日志才是一手证据。

---

## 3. 评分与星级（Chao 2026-09-30 拍板「甲」：固定分数线）

**四维加权（每维 0–10）**：A 机构与专业根基 30% / B 一手性 25% / C 历史命中率 30% / D 方法透明度 15%。

- **C 只算"已到期"的预测**（hit / miss / unclear 三档，表述模糊一律 unclear 不强判）。没有到期预测 → C 留空，加权分改为 `(A·.30+B·.25+D·.15)/.70`。
- **星级 = 固定分数线**（`scripts/rescore_kols.py::fixed_star`）：≥9.7 = 5★ / ≥9.3 = 4★ / **≥7.9 = 3★** / ≥6.5 = 2★ / 其余 1★。**3★=7.9 是 Chao 定的入库线**，其余线是按分布设的、可调。
- **为什么不用百分位**：百分位制下名册整体分数一上移，3★ 门槛会从 7.9 漂到 ~8.8，同一个人今天 3★ 明天 1★，入库判断不稳定（Withington 8.0 就栽过）。
- **尚未改的一处**：`tier=rated`（命中率已核验）那 2 人（Massicot 5★、Bronk 3★）仍按组内排名给星——他们的 C 走 Wilson 下界、小样本重罚，直接套固定线 Massicot 会掉到 2★。**待 Chao 定**。
- **AGENTS.md 里还写着旧的"群体内百分位"规则**，与代码不一致，等 Chao 把 `docs/PENDING_AGENTS_MD_UPDATE.md` 的 E 节贴进去。**以代码为准。**
- **入库门槛 3★**，规模目标 ≤60 人（现 67，超 7，不硬砍，等 Chao 定）。低于 3★ 的候选写 `data/candidates_rejected.json` 留痕。
- **两类例外（Chao 明确要求"要加"）**：Alex Karp（Palantir CEO，利益冲突）、Emil Michael（现任五角大楼 CTO，官方立场）。他们 1★ 但已入名册，卡片带 `quality_flag`（"产业信源 / 官方信源"），在看板单独成组"官方与产业信源"，**星级照实显示，不改分迎合**。
- **有 6 位现有 KOL 低于 3★**（Babak 1★，另 5 位 2★）。**不自动移出**，名册增删归 Chao。

**打分时的判例（供你判断新候选）**：
- 主持人 ≠ 嘉宾（Agrawal 6.14 不收）；
- 判断与自家生意挂钩 → D=3（Saronic 两位创办人 4.64/4.21 不收）；
- 失败预测对照现实核实后给 C（Aguilar C=2，1★）；
- 现任官员的公开发言是政策口径不是独立分析（Emil Michael 5.64）。

---

## 4. 看板结构（9 个顶级 section，`scripts/build_dashboard.py`）

KOL 最新观点 → 总览 → 地域走向 → 升级温度计 → 战区雷达 → 立场转向 → 言论卡片 → 事件时间线 → 观点全景。

- **唯一渲染器 `layerBody()`**，所有弹层 / 卡片共用，**要改就改它一个**。
- **四层展开**：L1 一句话 → L2 总结 → L3 中文译文（原文有多长就翻多长）→ L4 出处。"所有的列表都应该是这样"。
- **"KOL 最新观点"按收录日（`extracted_on`）切日/周/月**，标签写"新收录"；卡片仍显示真实发表日或"发表日未核实"。原因：64% 的言论查不到发表日，按发表日切会近乎空（0/1/22）。
- 页面风格：禁 emoji 标题、标题 ≤8 字、每 section 一行说明、忌自夸词。
- 视觉复核只当线索，**DOM 实测才是判据**。

---

## 5. Cron / 自动化清单（完整快照见 `ops/cron-jobs.json`）

**Hermes cron（JST）**

| Job | 时间 | 类型 | 做什么 |
|---|---|---|---|
| `war-kol-daily` | 每日 09:00 | agent（约 2.9 小时，12:00 出结果） | 全流程 + Telegram 日报 |
| `war-kol-weekly` | 周六 09:00 | agent | 一周立场变化 |
| `war-kol-monthly` | 每月 1 号 09:00 | agent | 月度走势 + 预测应验回顾 |
| `war-kol-context-distill` | 每日 05:20 | agent | 上下文归档（只存本地） |
| `war-kol-selfheal` | 每小时 :35 | no_agent 脚本 | 自愈 watchdog |

**系统 crontab（容灾，纯脚本，零模型费用）**
- `*/5` `scripts/daily_chain.sh` — 链式驱动。本机实测：数小时级后台任务会被外部整组收割（日志戛然而止、无报错），对策 = 每 5 分钟拉起 + `flock` 单实例 + 每步可重入。
- `*/5` `scripts/layers_watchdog.sh` — 四层有缺口就补。
- `*/10` `scripts/finalize_watchdog.sh` — 缺口补完后重建 + 双端发布。
- `30 10-22 * * *` `scripts/delivery_fallback.sh` — Telegram 兜底（gateway 投递不稳）。

**cron 约定**：
- prompt **绝不写死 KOL 数量**，一律「读名册取 active==true 的全部」。
- **两段式不能合并**：抓取（no_agent 脚本）与分析写入（agent）必须分开；agent 循环抓取 N 个人会撞 agent 空闲 600s 上限，整个 job 报错。
- Hermes cron：带 `workdir` 的 job 独占目录锁，别的 job 等满 660s 即 TimeoutError。排班避开长任务窗口；这类报错≠job 有毛病。
- `continuity=true` 会套娃膨胀，判据是客观数字的监控 job 别开。

**⚠ 模型配置（2026-10-01 刚改，务必验证）**：`config.yaml` 默认已改为 `claude-sonnet-5-5`，5 个 job 也写死 sonnet-5-5。但改之前的 cron 实际全跑在 opus 上（state.db 近 3 天 951 个 cron session 无一个 Sonnet）。**改完后还没有任何 cron 启动过，生效与否尚未验证**——下一次 cron 启动后，查 `~/.hermes/state.db` 里该 session 的 `model` 字段确认。注意日志时间戳是 JST、数据库是 UTC，比对时要换算，否则会误判（我就误判过一次）。

---

## 6. 成本（2026-10-01 实测估算，按 token 计）

- cron agent 实测（按 Opus 价）：daily ≈ $4.4/天（每次输入 818K、输出 11K、约 26 次调用）、context-distill ≈ $0.7/天、weekly+monthly 摊 ≈ $0.8/天；按 Sonnet 价约为其 60%。
- 脚本直调模型（走代理，**不进 state.db**，是估算）：每条新言论 ≈ $0.25（翻译约 $0.17 是大头）；每天新增 5–122 条（常见 10–20）→ $2.5–5/天，大日子可到 $10–30。
- **War-KOL 约占全部 cron 费用的 10%**。
- 省钱试验结论：**筛选环节（五要素）不能换 Haiku**——20 条真实材料对照，Haiku 4.5 把 Sonnet 能抽出的 8 条里误杀 4 条（50%），且误杀不可补救。翻译 / 总结可能可换，**还没测**。实验脚本 `scratch/haiku_compare.py`（scratch 不进 git）。

---

## 7. 已知待办 / 阻塞（按优先级）

1. **Karp / Michael 的上线状态**：两人已入 Notion 与本地名册（各 1★，组「官方与产业信源」）；近一年抓取完成（88 条原料，发表日核实 10 条），五要素筛选后合格 **Karp 14 条、Michael 7 条**；**四层内容（`build_layers.py --all`）写本文时仍在后台生成，发布尚未执行**。接手后先看 `pgrep -af build_layers`，跑完由 `finalize_watchdog.sh` 自动重建发布，再用 `curl -A "Mozilla/5.0" https://war-kol.pages.dev/` 读回确认两人出现。Kavanagh（11 条）与 Grieco（3 条）已于 10-01 上线。
2. **AGENTS.md 四块（A–D）+ E 块**待 Chao 手动贴入（`docs/PENDING_AGENTS_MD_UPDATE.md`）。审批弹窗两次超时。
3. **名册超 60 人上限**（67）；6 位低于 3★ 者待 Chao 定去留；`tier=rated` 两人是否改固定线待定。
4. **闸2「无正文」约 1314 条**：YouTube 177、IISS / FPRI / NYT / Crisis Group 付费墙、学术站。没字幕的 YouTube 暂不跑（太费时间），优先走文字渠道。
5. **发表日核实覆盖率仅约 20%**（64% 言论无可核实发表日）。
6. **两个 watchdog 的 mtime 互相干扰未修**：曾引发"总结 0 字"的虚惊（其实是 `no_body` 诚实标注，仅占约 6%，集中在 moneycontrol / newsweek / cepa / carnegie）。**看到 `总结0字` 先查 `no_body` 字段，别当故障。**
7. **Hermes gateway 投递不稳**，只加了 fallback 通道；一个 `gateway restart` 进程曾卡 22 分钟没结束，原因未查。
8. 页面存在两套日/周/月按钮（"KOL 最新观点"按收录日，"言论卡片"按发表日），口径不同，**合并还是删旧的待 Chao 定**。
9. 听风的蚕（`tier=monitor`，rating=None）无正文；O'Rourke 监测中（101 条原料，0 通过）。
10. ChaoWiki 归档提示（"收工"）多次无回复。

---

## 8. 踩过的坑（接手前必读）

**数据与口径**
- **子 agent 靠 summary 回传 = 数据必丢**；且会自派孙 agent 超时（复发率 100%，自己读源码）。必须每 3–4 项 `write_file` 落盘 + 禁嵌套。`child_timeout_seconds=900`，约 12 轮/人 → 安全容量约 3 人/批；timeout 标签下常已落盘，先查文件。
- **归属校验要两道闸**：只验"正文含姓名"，同名另一个人照样穿透。走过的两条弯路（主题词白名单 / 姓名扩展判据）别再试。
- **星级不能在入选后的子集里重算**（会把全池前 30% 标成 1★）。
- **幂等 upsert 必须 skip_none**：抓不到时不能把 Notion 已有真值 PATCH 成空。
- **同日多次运行会覆盖留痕**：任何按日期命名的产出文件，想一下同日重跑会怎样（`purge_homonyms.py` 曾把第一轮记录冲掉）。
- **"查不到 X"的结论，先拿必然存在的对照组走同一查询**（搜索后端抽风时 fetch 得分会是 0，不代表没有）。
- **上游"内容安全拒答"**：`choices=null 且 completion_tokens==0` 是永久拒答，重试无效，已落盘跳过（曾 4 条连续 7 天占满新料名额）。
- **`fetch_body()` 返回 `(status, body)` 元组**，不是纯正文（我写对照脚本时用错，白跑一轮）。
- **后台"正常结束"通知必须看 `EXIT=` 码**；管道里 `tee` 会吞掉真实退出码；排查中禁止 `>/dev/null 2>&1` 吞 stderr。
- **前台命令别放超过 ~400s 的活**，会被工具超时打断（`extract_thesis` / `build_layers` 一律后台 + notify）。内联 heredoc 或超长一行命令会被 hardline 拦截，写成脚本文件再跑。

**发布**
- **push 成功 ≠ 公网看得到**。GitHub Pages 已死，真公网入口是 Cloudflare；`publish.sh` 末尾幂等发布（线上 md5 相同就跳过）。
- **Cloudflare 会拦 Python 默认 UA（403）**，核对线上要用 `curl -A "Mozilla/5.0"`。
- `publish.sh` 第 4 步 `cd` 进内网 monorepo 后**必须切回**，后续脚本一律用 `$ROOT` 绝对路径（曾因此内网镜像整天没同步）。
- 发布由内容指纹去重，不是"今天跑过没"。

**LLM 批处理**
- 模型在中文里写直双引号会破坏 JSON → `parse_json()` 有正则退路。
- 标题是纯专名时模型原样回吐英文，重跑无效 → 换强化提示改写成中文描述句。
- 同配额下测限流前，先停其他同配额进程。

---

## 9. 接手后的头 30 分钟（按序执行）

> 在哪台机器：**任何装了 Hermes 的 VM**。以下命令都在项目根目录。

1. `git pull` 本仓库；读本文 + `AGENTS.md`。
2. 按 `SETUP.md` 配置 `.env`、复制 `self-skill/` 到 `~/.hermes/skills/`、重建全部 cron（对照 `ops/cron-jobs.json`）。
3. `python3 scripts/sync_kol_from_notion.py`（**不带 `--apply`**，先看 diff）→ 确认名册数与 Notion 一致。
4. 读 `data/thesis/thesis_all_<最新>.json` 计数、看线上页面，确认 Karp / Michael 是否已有言论（§7.1）。
5. 验证 §5 的模型配置是否真的生效。
6. 看 `logs/chain_<今天>.status` 与 `scratch/layers.log`，确认链条在走。
7. 有疑问**先问 Chao，别自治**——尤其是名册、星级线、任何删除、`git push`、改 cron。

---

## 10. 关键文件速查

| 路径 | 作用 | 能不能删 |
|---|---|---|
| `data/kol_registry.json` | 名册镜像 | 不能（脚本可重建） |
| `data/statements/*.json` | 抓取原料 | 不能 |
| `data/thesis/` | 五要素产物 | 不能 |
| `data/layers/` | 四层内容 | 可重建但烧配额 |
| `data/removed_*_<date>.json` | 三道闸剔除留痕 | 保留备查 |
| `data/candidates_rejected.json` | 低于 3★ 候选留痕（含理由与复审条件） | 保留 |
| `data/roster_candidates.json` | 待定候选 | — |
| `data/notion_ids.json` | Notion 库 id（gitignored） | 不能进 git |
| `ops/cron-jobs.json` | 5 个 Hermes cron 的真实 prompt 快照 | — |
| `docs/PENDING_AGENTS_MD_UPDATE.md` | 等 Chao 贴进 AGENTS.md 的改动（A–E） | — |
| `docs/context-log.md` | 每日上下文归档 | — |
| `scratch/`、`logs/` | 临时与日志，gitignored | 可清 |

---

## 11. 近期历史（2026-09-20 → 10-01）

- 09-21：门禁修复后 108 条送 LLM、20 条合格。
- 09-25：公网切换到 Cloudflare Pages；Withington（RUSI）入库。
- 09-29：新增"KOL 最新观点"顶部 section。
- 09-30：评分口径改固定分数线；Kavanagh、Grieco 入库（8.43 分，克制派立场标注）；Larry Johnson（1★ 3.45 分，含 FARA 外国代理人登记 7487）不收。
- 10-01：Karp、Michael 按 Chao 要求入名册（官方与产业信源组）；Cron 模型由 opus 改 sonnet-5-5（未验证生效）；Haiku 对照实验（筛选不能换）。
- 已拒候选（留痕在 `candidates_rejected.json`）：Agrawal、Antrobus、Aguilar、Mavrookas、Altekar、Larry Johnson 等。
