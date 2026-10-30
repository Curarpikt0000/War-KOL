# War-KOL 交接文档（HANDOVER）

> 首版写于 2026-10-01，**2026-10-30（JST）整体重写**。接手的 agent **先读本文，再读 AGENTS.md**。
> 本文讲「现在是什么状态、怎么跑、哪里有坑、哪些事不能做」；AGENTS.md 讲「规矩」。
> 本文是公网安全版，不含内网地址与凭证；内网端另有 `HANDOVER_INTERNAL.md`（只在内网 repo）。
> 旧版 `docs/HANDOVER.md`（2026-09-02，当时 62 人/623 条）已过时，以本文为准。

---

## 0. 三十秒读懂

- **做什么**：汇总全球战争分析者（军事分析师 / 智库研究员 / OSINT / 国防产业）的公开言论，按战区判断走势，产出**单文件自包含 HTML 看板**。
- **规模（2026-10-30 实测）**：名册 68 人 / 合格言论 1233 条（按 KOL+出处去重）/ 7 战区 / 看板 22MB。星级：5★ 9 · 4★ 11 · 3★ 38 · 2★ 5 · 1★ 4 · 监测 1。
- **公网入口**：https://war-kol.pages.dev/ （Cloudflare Pages）。旧 GitHub Pages 地址已死（账号被封），**不要再贴**。
- **负责人**：Chao（Uber Sr Ops Manager）。名册增删、星级线、"定稿"页都由他拍板。
- **2026-10-30 起的状态**：Chao 要求**停掉整条每日流程**——agent 日报（`war-kol-daily`）已暂停；系统 crontab 的数据管线 3 条也已注释停用（有备份）。**看板停在 10-30 的数据，不再自动更新。**恢复方式见 §12.2。**接手第一件事 = 读 §12，再跑 `python3 ops/handover_check.py`**（只读，会告诉你现在到底哪些在跑）。
- **接手前必读两个陷阱**：§1 第 14 条（新克隆里跑 `build_layers --all` 会洗空译文）、§12.3（换机器要自建 `~/.hermes/war_kol_publish.env`，否则内网同步静默跳过）。

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
11. **`sources` 字段只放 KOL 真正的自有平台。** 归属脚本把 `sources` / `primary_url` / `youtube` 里出现的域名全部当作"自有平台"白名单：若把评估时引用的出处（维基、NYT、Newsweek 等）填进去，整个媒体网站都会绕过作者校验（2026-10-07：Johnson 57 条原料里 26 条因此未验署名即放行）。评估引文放 `data/candidates_rejected.json`，不放名册。
12. **自有域名 ≠ 免检。** KOL 自己博客的首页 / 分页 / 读者留言页，正文可能一次都不含他的名字；仍须过五要素门禁。
13. **五要素门禁只验"正文有没有方向性判断"，不验"是不是本人说的"。** 节目简介页、第三人称转述、嘉宾介绍页都能过闸；目前**没有"署名核验"硬门禁**（§7 待办）。收录第三方来源前要人工核署名。
14. **在没有 `data/thesis/_body_cache_all.json` 的目录里，绝不运行 `build_layers.py --all`。** 它会把现有译文和总结覆盖成空（隔离副本实测：1210 条里 1203 条被洗空，610 万字）。详见 §8「全新克隆陷阱」。

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
- **入库门槛 3★**，规模目标 ≤60 人（现 68，超 8，不硬砍，等 Chao 定）。低于 3★ 的候选写 `data/candidates_rejected.json` 留痕。
- **两类例外（Chao 明确要求"要加"）**：Alex Karp（Palantir CEO，利益冲突）、Emil Michael（现任五角大楼 CTO，官方立场）。他们 1★ 但已入名册，卡片带 `quality_flag`（"产业信源 / 官方信源"），在看板单独成组"官方与产业信源"，**星级照实显示，不改分迎合**。
- **名册里 <3★ 共 9 位**（2026-10-30 读名册实测）：1★ 四位 = Karp 4.64 / Michael 5.64 / Johnson 4.07 / Babak 5.0；2★ 五位（7.43–7.86）。前三位是 Chao 明确要求"要加"的例外；其余**不自动移出**，名册增删归 Chao。

**打分时的判例（供你判断新候选）**：
- 主持人 ≠ 嘉宾（Agrawal 6.14 不收）；
- 判断与自家生意挂钩 → D=3（Saronic 两位创办人 4.64/4.21 不收）；
- 失败预测对照现实核实后给 C（Aguilar C=2，1★）；
- 现任官员的公开发言是政策口径不是独立分析（Emil Michael 5.64）。

**Johnson 的特殊情况（2026-10-07）**：原评估 3.45（C=2）；`rescore_kols.py` 后 C 被清空（他没有已到期预测可核验），加权分变为 **4.07**。`rating_reason` 文字里仍写着 C=2——两者不一致，**以名册里的数字为准**。他的 7 条言论里 5 条来自第三方转述 / 节目页 / 搬运站，是 Chao 选"乙"后**明知违反归属规则**的一次性例外，只限他一人，留痕在 `data/attribution_exceptions_johnson.json`，规则本身未改。

---

## 4. 看板结构（9 个顶级 section，`scripts/build_dashboard.py`）

KOL 最新观点 → 总览 → 地域走向 → 升级温度计 → 战区雷达 → 立场转向 → 言论卡片 → 事件时间线 → 观点全景。

- **唯一渲染器 `layerBody()`**，所有弹层 / 卡片共用，**要改就改它一个**。
- **四层展开**：L1 一句话 → L2 总结 → L3 中文译文（原文有多长就翻多长）→ L4 出处。"所有的列表都应该是这样"。
- **"KOL 最新观点"按收录日（`extracted_on`）切日/周/月**，标签写"新收录"；卡片仍显示真实发表日或"发表日未核实"。原因：64% 的言论查不到发表日，按发表日切会近乎空（0/1/22）。
- 页面风格：禁 emoji 标题、标题 ≤8 字、每 section 一行说明、忌自夸词。
- 视觉复核只当线索，**DOM 实测才是判据**。

---

## 5. Cron / 自动化清单（完整快照见 `ops/cron-jobs.json`；一键自检 `python3 ops/handover_check.py`）

**Hermes cron（JST）——2026-10-30 19:07 起的真实状态**

| Job | 时间 | 类型 | 状态 | 做什么 |
|---|---|---|---|---|
| `war-kol-daily` | 每日 09:00 | agent（Sonnet 5.5） | **已暂停（Chao 2026-10-30）** | 全流程 + Telegram 日报 |
| `war-kol-weekly` | 周六 09:00 | agent | 在跑 | 一周立场变化（读已落盘数据，不抓取） |
| `war-kol-monthly` | 每月 1 号 09:00 | agent | 在跑 | 月度走势 + 预测应验回顾 |
| `war-kol-context-distill` | 每日 05:20 | agent | 在跑 | 上下文归档（只存本地） |
| `war-kol-selfheal` | 每小时 :35 | no_agent 脚本 | 在跑 | 自愈 watchdog |

**系统 crontab（纯脚本，零模型费用，不在 `jobs.json` 里）**——当前机器 `crontab -l` 里有 **3 条，2026-10-30 起均已被注释停用**（备份 `~/crontab.war-kol.bak_20261030`）：
- `*/5` `scripts/daily_chain.sh` — 数据链式驱动，**每天 00:00 自己拉起抓取**，并不依赖 agent 日报。（**已停**）
- `*/5` `scripts/layers_watchdog.sh` — 四层有缺口就补。
- `*/10` `scripts/finalize_watchdog.sh` — 缺口补完后重建 + 双端发布。
- ⚠ **`delivery_fallback.sh` 不在当前 crontab 里**（旧版交接文档把它列为在跑，那是错的；脚本在 `scripts/` 但没人调用）。日报停了以后它也没有意义。

**一个关键事实（读实物得出）**：只暂停 `war-kol-daily` **不会**停掉每天的抓取、筛选、写 Notion、发布——10-30 当天这四步全是 `daily_chain.sh` 在 00:00–08:54 完成的（FETCH 07:26 结束、THESIS 07:33、NOTION 08:54，PUBLISH 因线上已是当前数据而跳过），agent 日报 09:00 才起，只读结果、发 Telegram。所以 Chao 又批准把这 3 条系统 cron 一起停了。`war_kol_selfheal.py` 补抓取的条件要求"`war-kol-daily` 今天 fire 过"，日报暂停后它**不会**替日报补跑（只读到该脚本第 61–125 行，判断分支完整，未实测）。

**cron 约定**：
- prompt **绝不写死 KOL 数量**，一律「读名册取 active==true 的全部」。
- **两段式不能合并**：抓取（no_agent 脚本）与分析写入（agent）必须分开；agent 循环抓取 N 个人会撞 agent 空闲 600s 上限，整个 job 报错。
- Hermes cron 带 `workdir` 的 job 独占目录锁，别的 job 等满 660s 即 TimeoutError。排班避开长任务窗口。
- `continuity=true` 会套娃膨胀，判据是客观数字的监控 job 别开。

**模型配置（已验证）**：`config.yaml` 默认与 5 个 job 均为 `claude-sonnet-5-5`。10-30 的 `war-kol-daily`（09:00）与 `war-kol-context-distill`（05:20）在 `state.db` 里的 `sessions.model` 均为 `claude-sonnet-5-5`，**Sonnet 已真生效**（10-01 旧文档写"未验证"，现更正）。注意日志时间戳是 JST、库是 UTC，比对要换算。

---

## 6. 成本（2026-10-30 更新）

- cron agent（按 token 计）：按 Opus 价时 daily ≈ $4.4/天；改 Sonnet 后约 60%。**日报暂停后这一块归零**；weekly + monthly + context-distill 仍有少量费用。系统 cron 管线也停了，脚本直调模型费用同样归零。
- 脚本直调模型（走本机代理，**不进 `state.db`**，是估算）：每条新言论 ≈ $0.25（翻译约 $0.17 是大头）。**近 6 天每天新增合格言论只有 2–7 条**（`thesis_all_*` 实测）→ 约 $0.5–2/天；批量回补新人时可到几十美元。
- 省钱试验结论：**筛选环节（五要素）不能换 Haiku**——20 条真实材料对照，Haiku 4.5 把 Sonnet 能抽出的 8 条里误杀 4 条（50%），且误杀不可补救。翻译 / 总结**没测**。实验脚本 `scratch/haiku_compare.py`（scratch 不进 git，对照数据没有随库带走）。

---

## 7. 已知待办 / 阻塞（按优先级，2026-10-30 复核）

1. **【交接真风险】新克隆目录里的译文洗空陷阱**（详见 §8）。未修，**需 Chao 批准改 `build_layers.py`**（属构建逻辑）。修法建议：`body` 为空且已有译文时跳过重写。在修之前，换机器接手必须先把 `_body_cache_all.json`（约 77MB）从原机拷过去。
2. ~~公网 `publish.sh` 即将带出内网路径~~ **已处理（Chao 2026-10-30 批准）**：`publish.sh` 里不再有任何内网路径字面量。内网 monorepo 的本机路径改为从本机文件 `~/.hermes/war_kol_publish.env` 读取（该文件不进任何 git、不含凭证，只放 `WARKOL_MONO` 与 `WARKOL_CERT_ENV` 两个路径）。**换机器接手要自己建这个文件**（见 §12.3）；没建则 `publish.sh` 会**跳过内网同步且不报错**——所以内网副本悄悄停更而没人发现是这个改法的代价，`ops/handover_check.py` 第 5 项会检查它。
3. **署名核验硬门禁缺失**（§1 第 13 条）：节目页 / 转述页仍会过五要素。建议把"本人署名"写成 `extract_thesis.py` 的第 4 道闸并回扫全库；**需 Chao 批准**（属抽取逻辑）。
4. **名册超 60 人上限**（现 68）；9 位 <3★ 者去留待 Chao 定（§3）；`tier=rated` 两人是否改固定线待定。
5. **AGENTS.md 与代码不一致**：它仍写"群体内百分位"，代码已是固定分数线。受保护文件，改动记在 `docs/PENDING_AGENTS_MD_UPDATE.md`（A–E 五块，等 Chao 手动贴入；审批弹窗两次超时）。
6. **`data/` 下有大量未清理的 `.bak*` 备份**（`kol_registry.json.bak-rescore-*` 已进 git 追踪，随克隆下来）。
7. **闸2「无正文」约 1300 条**：YouTube、IISS / FPRI / NYT / Crisis Group 付费墙、学术站。没字幕的 YouTube 暂不跑，优先走文字渠道。
8. **发表日核实覆盖率 37%**（1233 条中 451 条）。
9. **两个 watchdog 的 mtime 互相干扰未修**：曾引发"总结 0 字"虚惊（其实是 `no_body` 诚实标注）。**看到 `总结0字` 先查 `no_body` 字段，别当故障。**
10. 页面存在两套日/周/月按钮（"KOL 最新观点"按收录日，"言论卡片"按发表日），口径不同，合并还是删旧的待 Chao 定。
11. 听风的蚕（`tier=monitor`）无正文；O'Rourke 监测中（0 通过）。
12. **Notion 写入全量版每天要 76–81 分钟**（`write_statements_to_notion.py`，近 6 天实测，都在 `daily_chain.sh` 后台跑完、exit=0）。agent 或前台会话里直接跑会被 ~400s 工具超时打断——那是前台限制，不是故障。建议改成只写增量；未做。
13. ChaoWiki 归档提示（"收工"）历史上多次无回复。

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

**构建与交接陷阱（2026-10-30 实测补充）**

- **全新克隆陷阱（最重要）**：`data/thesis/_body_cache_all.json`（约 77MB，原文缓存）被 `.gitignore` 排除，**克隆下来没有**。`build_layers.py` 判断"某条要不要重做"用的是 `hash(claim + 正文前2000字 + 正文长度)`，正文为空时 hash 全变 → `--all` 会把 **1210 条里的 1210 条**列为待办（其中 1203 条原本有完整译文），重写时正文长度 <200 就把总结和译文写成空，并由 `publish.sh` 推上线。隔离副本里实测（无任何 LLM 费用，只数待办）：待生成 1210 条，被洗空的总结 1203 条、译文 1203 条共 610 万字；生产目录同一计算是 7 条。
  - 触发路径：`layers_watchdog.sh` 只在"thesis 里有但 layers 里没有的 URL"出现时才拉起 `build_layers --all`，克隆当天缺口为 0 → 不触发；**接手后第一条新增言论入库，就会触发**。
  - 缓解：先从原机拷 `_body_cache_all.json` 到同一路径；或在批准修复前把 `layers_watchdog.sh` 那条 crontab 注释掉。`ops/handover_check.py` 会在缓存缺失时红字报警。
  - 缓存在内网 monorepo 的检出目录里有一份 60MB 的旧副本（09-21），但 git 没追踪它，**不会随 pull 到达别的机器**，且已陈旧。
- **`publish.sh` 在 10-30 被改过两次**（备份 `scripts/publish.sh.bak.20261030_*` 未进 git）：①公网推送改为每 14 天一次，闸在 `~/.hermes/scripts/public_push_gate.sh`（提交仍每天做，只拦 push；状态在 `~/.hermes/state/public_push/`）；②内网 monorepo 同步改为固定本机路径（细节见内网补充文件），原来依赖的环境变量没有设置处，**内网同步因此自 09-14 起停摆**，10-30 才修好。两处都没写进 `docs/context-log.md`，我是对比备份和 git 才发现的。
- **闸不在仓库里**：`public_push_gate.sh` 住在 `~/.hermes/scripts/`，不随克隆走。换机器后 `publish.sh` 调它会找不到——需把它也拷过去，或把调用改成缺失时直接推。
- **本地领先公网 1 个提交**（10-30 的 `publish.sh` 改动）：闸 14 天内不推，所以这是预期状态；但意味着**任何手动往公网 `main` 推的提交都会让下次闸推送变成非快进被拒**（rc=7），要先对齐。
- **跨天后 `daily_chain.sh` 的哨兵靠 `scratch/`**：`scratch/` 被 gitignore，新机器没有哨兵 → 当天会从头跑一遍抓取（有成本）。
- **后台"正常结束"通知要看 `EXIT=`**；本轮曾因没读日志首行，误判"Johnson 没进四层"，实际是读产物才发现早已生成。**判断"有没有生成"看产物文件，不看日志里列了谁。**

---

## 9. 接手后的头 30 分钟（按序执行）

> 在哪台机器：**任何装了 Hermes 的 VM**。以下命令都在项目根目录。

1. `git pull` 本仓库；读本文 + `AGENTS.md`（注意它仍写旧百分位规则，以代码为准）。
2. `python3 ops/handover_check.py` —— 只读自检，**先看它的输出再做任何事**。
3. 若是**换了一台机器**：先拷 `data/thesis/_body_cache_all.json`（§8 全新克隆陷阱），再把 `layers_watchdog.sh` 那行 crontab 留着注释，直到缓存到位。
4. 按 `SETUP.md` 配置 `.env`、复制 `self-skill/` 到 `~/.hermes/skills/`、重建 cron（对照 `ops/cron-jobs.json` 与 §5 的真实状态——**`war-kol-daily` 现在是暂停的，不要想当然地把它启用**）。
5. `python3 scripts/sync_kol_from_notion.py`（**不带 `--apply`**，先看 diff）→ 确认名册数与 Notion 一致（2026-10-30 为 68）。
6. 看 `logs/chain_<今天>.status`，确认链条在走（正常序列：FETCH → ENRICH → THESIS → PROPAGATE → NOTION → PUBLISH → CHAIN_COMPLETE）。
7. 有疑问**先问 Chao，别自治**——尤其是名册、星级线、任何删除、`git push`、启停 cron、改 `build_layers` / `publish.sh` / `extract_thesis`。

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
| `ops/cron-jobs.json` | 5 个 Hermes cron 的真实 prompt 快照（含 enabled 状态与系统 crontab 的 3 条） | — |
| `ops/handover_check.py` | 只读自检脚本（cron / 名册 / 缓存 / 线上 md5 / 内部标识） | — |
| `data/attribution_exceptions_johnson.json` | Chao 对 Johnson 一人的归属例外留痕 | 保留 |
| `data/thesis/_body_cache_all.json` | 原文缓存（77MB，gitignored，**不随克隆走**，缺它跑 build_layers 会洗空译文） | **不能删** |
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
- 10-07：Johnson 入册（Chao 再次点名；普通名册行 1★）；发现 `sources` 字段被当自有域名白名单的漏洞并修正；五要素筛选后 7 条合格，Chao 选"乙"全收（含 5 条第三方来源，一次性例外）。
- 10-10 ~ 10-29：日常运行；每日新增合格言论 2–7 条；`rescore` 把 Johnson 的 C 清空（3.45→4.07）。
- 10-30：公网 GitHub 推送改每 14 天一次；`publish.sh` 内网同步重写（原环境变量无设置处，内网自 09-14 起停摆，已修）；**Chao 要求停 agent 日报**，`war-kol-daily` 暂停；本次交接文档重写。
## 12. 现在谁在跑、怎么停、怎么恢复（2026-10-30 19:20 JST）

### 12.1 当前状态
| 项 | 状态 |
|---|---|
| `war-kol-daily`（agent 日报） | **暂停**（`paused_at` 2026-10-30 19:07:51） |
| `war-kol-weekly` / `monthly` | 仍在跑，但**只读 `data/`**；`data/` 自 10-30 起不再增长，所以它们汇总的是**不再更新的数据** |
| 系统 crontab 三条（chain / layers / finalize） | **已全部停（Chao 2026-10-30 批准）**：注释保留在 crontab 里，原文件备份 `~/crontab.war-kol.bak_20261030` |
| 看板 | **从此不再自动更新**（管线已停）；停在 10-30 数据，公网 md5 `f70fbf2c352d`，内网镜像 v118 |
| 公网 GitHub 推送 | 14 天一次，上次 2026-10-30 00:30，下次约 11-13；本地领先公网 1 个提交 |

### 12.2 停与恢复
- **恢复日报**：Hermes cron 管理里对 `war-kol-daily`（job_id `bebf9f3b45ba`）执行 resume；原 09:00 计划保留。
- **数据管线已停**（2026-10-30）。恢复：`crontab ~/crontab.war-kol.bak_20261030`（备份里是停之前的完整 crontab；**若这期间 crontab 有别的改动，别整份覆盖**，改为手工去掉那 3 行行首的 `# [停于2026-10-30 Chao批准] `）。**恢复前先看 §8「全新克隆陷阱」与 §12.3 的前置条件。**
- 停掉后 `war-kol-weekly` / `monthly` 仍会跑，但读的是 `data/`，而 `data/` 不再更新——周报月报会基于 10-30 之后**不再增长**的数据。

### 12.3 公网仓库的内部标识（2026-10-30 已处理）
公网 `scripts/publish.sh` 现在不含内网路径字面量。本机路径放 `~/.hermes/war_kol_publish.env`（不进 git，不含凭证），内容是两行：`WARKOL_MONO="<内网 monorepo 本地 clone 的路径>"` 与 `WARKOL_CERT_ENV="<证书环境文件路径>"`；具体取值见内网补充文件。**换新机器：先建这个文件，否则内网同步会静默跳过。** 公网推送闸（`public_push_gate.sh`）仍是 14 天一次，在 `~/.hermes/scripts/`，不随克隆走，也要另拷。

---

## 13. 构建方案（build）总览

### 13.1 阶段与产物
| 阶段 | 脚本 | 产物 | 并发 / 耗时 |
|---|---|---|---|
| 0 名册镜像 | `sync_kol_from_notion.py --apply` | `data/kol_registry.json` | 秒级 |
| 1 抓取 | `fetch_statements.py --mode daily --days 3` | `data/statements/daily_<日>.json` | 串行，数小时（10-30 约 7.4 小时） |
| 1.2 覆盖率闸 | `daily_chain.sh` 内 | 至少 90% 名册有产出，否则不落哨兵；6 小时逃生阀放行并标"降级" | — |
| 1.5 回补发表日 | `enrich_dates.py --fetch-pages --limit-fetch 400` | 填 `published_on` | 约 5 分钟，**必须在五要素前** |
| 2 五要素门禁 | `extract_thesis.py --all --workers 4` | `data/thesis/thesis_all_<日>.json`、`removed_{directory,nobody,no_thesis}_<日>.json`、`_body_cache_all.json` | LLM 串行 1.5s 间隔 |
| 2.1 回填发表日 | `propagate_dates_to_thesis.py` | 只填空 | 秒级 |
| 3 四层内容 | `build_layers.py --all`（`layers_watchdog.sh` 兜底） | `data/layers/layers_<日>.json`（一句话 / 总结 / 译文 / 出处） | 每条约 $0.25；**§8 陷阱** |
| 3.5 写 Notion | `write_statements_to_notion.py`、`write_weekly_to_notion.py` | Notion By Day / By Week | **76–81 分钟** |
| 4 重算星级 | `rescore_kols.py --apply` | 名册星级与分数（固定分数线） | 秒级 |
| 5 建看板 | `build_dashboard.py` | `dashboard/index.html`（22MB，单文件自包含） | 分钟级；**在全新克隆里实测可构建**（68 人 / 1233 条 / 退出码 0） |
| 6 发布 | `publish.sh`（红线扫描 → 公网闸 → 内网 monorepo → Cloudflare → 内网镜像） | 公网 / 内网 / 镜像 | 约 2–3 分钟 |

### 13.2 发布内部逻辑
`publish.sh` → `build_dashboard.py` → 复制到根 `index.html`（Pages 入口）→ **红线扫描**（`SCAN_FILES` 清单，必须与 `git add` 清单同步）→ `git add` + 提交（每天都做）→ `public_push_gate.sh push war-kol`（14 天一次）→ rsync 到内网 monorepo 子目录并按**当前分支**推送 → `publish_cloudflare.sh`（靠线上 md5 判等）→ `publish_vibe_mirror.sh`（靠 sha256 台账幂等，失败恒 exit 0）。发布去重靠 `publish_fingerprint.sh` 的**内容指纹**，不是"今天发过没"。

### 13.3 git 三态（哪些文件克隆后有 / 没有）
| 文件 | git 追踪 | 克隆后有 | 说明 |
|---|---|---|---|
| `data/kol_registry.json`、`data/statements/`、`data/thesis/thesis_*.json`、`data/layers/` | 是 | 有 | 数据本体 |
| `data/thesis/_body_cache_all.json` | **忽略** | **没有** | §8 陷阱的根 |
| `data/notion_ids.json` | **忽略** | **没有** | 向 Chao 要，或 `build_notion_dbs.py` 重建；内网端 `git add -f` 才带 |
| `.env`、`scratch/`、`logs/` | 忽略 | 没有 | `.env` 变量名见 `SETUP.md §0` |
| `AGENTS.md` | 公网忽略 | 公网没有 | 只随内网 rsync；公网侧靠 `README.md` |
| `scripts/publish_vibe_mirror.sh`、`rebuild_public_repo.sh`、`HANDOVER_INTERNAL.md` | 公网忽略 | 公网没有 | 含内网标识 |
| `~/.hermes/scripts/public_push_gate.sh` | 在仓库外 | **没有** | 换机器要另拷 |

### 13.4 脚本清单（`scripts/`，37 个，按职责）
- **抓取与归属**：`fetch_statements.py`、`fetch_youtube_kol.py`（听风的蚕专用）、`attribution.py`（两道归属闸）、`revalidate_attribution.py`、`purge_homonyms.py`、`merge_raw.py`
- **抽取与加工**：`extract_thesis.py`（五要素）、`enrich_dates.py`、`propagate_dates_to_thesis.py`、`translate.py`、`build_layers.py`、`reclassify_directions.py`
- **名册与评分**：`sync_kol_from_notion.py`、`write_roster_to_notion.py`、`select_roster.py`、`compute_ratings.py`（旧百分位，仅保留）、`rescore_kols.py`（现行固定分数线）
- **看板**：`build_dashboard.py`（2000+ 行，唯一渲染器 `layerBody()`）、`world_map.py`、`stance_tracker.py`、`weekly_rollup.py`
- **Notion**：`build_notion_dbs.py`、`patch_notion_schema.py`、`write_statements_to_notion.py`、`write_weekly_to_notion.py`、`patch_daily_cron_prompt.py`
- **发布与守护**：`publish.sh`、`publish_cloudflare.sh`、`publish_vibe_mirror.sh`、`publish_fingerprint.sh`、`rebuild_public_repo.sh`、`daily_chain.sh`、`layers_watchdog.sh`、`finalize_watchdog.sh`、`delivery_fallback.sh`（**未被调度**）、`chainctl.sh`、`enrich_extra.sh`

---

