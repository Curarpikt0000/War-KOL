# SETUP — 接手 War-KOL 的运行手册

> 目标：另一个 agent `git pull` 后，按本文从上到下执行，重建全部自动化，不依赖原 agent。
> 背景、红线、坑见 `HANDOVER.md`。**先读它。**
> 路径约定：`<PROJECT_ROOT>` = 本仓库在你机器上的绝对路径；`<HOME>` = 你的 home。

## 0. 前置

- 已装 Hermes Agent，`~/.hermes/` 可写；Python 3.10+，`pip install requests beautifulsoup4 lxml pymupdf`。
- 本机 LLM 代理 `localhost:8800`（Anthropic 兼容 `/v1/messages`、OpenAI 兼容 `/v1/chat/completions`）可用。
- 凭证写进 `~/.hermes/.env`（**绝不进 git、绝不贴聊天**），变量名：
  - `NOTION_API_KEY`（脚本里也读 `NOTION_TOKEN`，两者设同值即可）
  - `TELEGRAM_BOT_TOKEN`
  - `CLOUDFLARE_API_TOKEN`、`CLOUDFLARE_ACCOUNT_ID`（公网发布）
  - `WARKOL_INTERNAL_MONOREPO`（内网 monorepo 本地 clone 路径；**不设则跳过内网同步**）
- 可选环境变量：`THESIS_MODEL` / `LAYER_MODEL` / `TRANSLATE_MODEL` / `SCORE_MODEL`（脚本直调模型用的名字）、`GENAI_PROXY`（默认本机 8800）、`TRANS_WORKERS`（翻译并发，默认 3，**不要调大**）。

## 1. 复制技能与脚本

```bash
mkdir -p ~/.hermes/skills/devops ~/.hermes/scripts
cp -r self-skill/* ~/.hermes/skills/devops/
sed "s#<PROJECT_ROOT>#$(pwd)#g; s#<HOME>#$HOME#g" ops/hermes-scripts/war_kol_selfheal.py        > ~/.hermes/scripts/war_kol_selfheal.py
sed "s#<PROJECT_ROOT>#$(pwd)#g; s#<HOME>#$HOME#g" ops/hermes-scripts/collect_topic_conversation.py > ~/.hermes/scripts/collect_topic_conversation.py
```

脚本里若还有写死的 telegram chat/thread id，换成你自己的。

## 2. 重建名册与 Notion 对接

`data/notion_ids.json`（Notion 库 id）是 gitignored 的，**需向 Chao 要**，或按 `scripts/build_notion_dbs.py` 重建。然后：

```bash
python3 scripts/sync_kol_from_notion.py          # 先 dry-run 看 diff
python3 scripts/sync_kol_from_notion.py --apply  # 确认后落盘
```

名册数应与 Notion 的 active 数一致（2026-10-01 为 67）。**名册只读，不手改。**

## 3. 建 cron

对照 `ops/cron-jobs.json`，每个 job 用 Hermes 的 cron 管理创建（把 `<PROJECT_ROOT>` 换成你的路径）：

| name | schedule | no_agent | script | workdir | deliver |
|---|---|---|---|---|---|
| war-kol-daily | `0 9 * * *` | 否 | — | PROJECT_ROOT | origin |
| war-kol-weekly | `0 9 * * 6` | 否 | — | PROJECT_ROOT | origin |
| war-kol-monthly | `0 9 1 * *` | 否 | — | PROJECT_ROOT | origin |
| war-kol-selfheal | `35 * * * *` | **是** | war_kol_selfheal.py | — | origin |
| war-kol-context-distill | `20 5 * * *` | 否 | collect_topic_conversation.py | PROJECT_ROOT | local |

模型：用 `claude-sonnet-5-5`（**别用 opus**，贵 67% 且没必要）。创建后**必须验证**：下一次 job 启动后，查 `~/.hermes/state.db` 的 `sessions.model` 字段确认真的是 sonnet（注意日志是 JST、库是 UTC）。

**系统 crontab（容灾，纯脚本）**：

```
*/5  * * * * cd <PROJECT_ROOT> && bash scripts/daily_chain.sh      >/dev/null 2>&1
*/5  * * * * cd <PROJECT_ROOT> && ./scripts/layers_watchdog.sh     >/dev/null 2>&1
*/10 * * * * cd <PROJECT_ROOT> && ./scripts/finalize_watchdog.sh   >/dev/null 2>&1
30 10-22 * * * cd <PROJECT_ROOT> && bash scripts/delivery_fallback.sh >/dev/null 2>&1
```

> ⚠ 两段式不要合并：抓取（no_agent 脚本）与分析写入（agent）必须分开，否则撞 agent 600s 空闲上限。

## 4. 验证（逐条）

```bash
python3 scripts/build_dashboard.py            # 应生成 dashboard/index.html（约 19MB）
ls data/thesis | tail -1                      # 最新五要素产物
tail -5 logs/chain_$(date +%F).status         # 链条进度
curl -s -A "Mozilla/5.0" -o /dev/null -w '%{http_code}\n' https://war-kol.pages.dev/   # 期望 200
```

发布前先 `bash scripts/publish.sh` 的 dry 读：红线扫描会拦住含内网标识的文件。**首次发布前不要自己 push，先让 Chao 确认你的 remote 指向。**

## 5. 日常

- 你**不需要每天手动跑任何东西**。看 Telegram 日报；异常时先查 `logs/chain_<日>.status` 与 `scratch/layers.log`。
- 看到 `总结0字`：先查 `no_body` 字段（原文抓不到的诚实标注，约 6%），不是故障。
- 想加人：用四维打分 → ≥7.9 才提议 → 写 Notion（`scripts/write_roster_to_notion.py --roster <json>`，先 dry-run）→ `sync_kol_from_notion.py --apply` → `fetch_statements.py --mode backfill --days 365 --limit N`（新人在名册前列）→ 后台跑 `extract_thesis.py` 与 `build_layers.py`。**名册增删最终由 Chao 拍板。**
- 长命令（抽取 / 四层）一律后台 + notify，前台会被 ~400s 工具超时打断。

## 6. 回滚

- 任一 cron 出问题：暂停（不删），原 agent 的 job 可 resume。
- 误发布：`git revert` 对应 commit 后重跑 `publish.sh`。
- 名册被误改：从 Notion 重新 `sync_kol_from_notion.py --apply`，本地有 `data/kol_registry.json.bak_*` 备份。
