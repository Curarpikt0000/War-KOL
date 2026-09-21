#!/usr/bin/env bash
# War-KOL 日报投递兜底（Chao 2026-09-18 批准）
#
# ★ 为什么需要：
#   2026-09-18 war-kol-daily 正常跑完、日报正常生成、投递配置也正确
#   （telegram / chat -1003988268482 / thread 56995），last_delivery_error 为 null
#   ——系统认为发送成功，但 Chao 没收到。
#   旁证：同日 12:32 ai-daily-board 对【同一个 chat】明确报
#   "Telegram send failed: Timed out"。即 Hermes 网关投递当天不稳，
#   war-kol 大概率也超时了，只是它没把失败写进状态。
#   ⇒ 网关说"成功"不可信，需要一条不依赖网关的直连兜底通道。
#
# 做法：直连 api.telegram.org（绕开 Hermes 网关），HTTP ok=true 才算送达。
#      凭证只从 ~/.hermes/.env 读，绝不硬编码、不回显。
#
# ★ 去重靠「已送达文件名台账」，不是靠日期。
#   同一份日报只补发一次。（日期哨兵的坑刚在 publish_fingerprint.sh 踩过，不重犯。）
#
# 正常无事 = 完全静默。
set -u
cd "$(dirname "$0")/.." || exit 1

OUTDIR="$HOME/.hermes/cron/output"
JOB_ID="bebf9f3b45ba"                 # war-kol-daily
LEDGER="scratch/.daily_delivered"
LOG="scratch/delivery_fallback.log"
LOCK="scratch/delivery_fallback.lock"

mkdir -p scratch
exec 9>"$LOCK" || exit 1
flock -n 9 || exit 0

log() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }

ENVF="$HOME/.hermes/.env"
[ -f "$ENVF" ] || exit 0
TG_TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENVF" | head -1 | cut -d= -f2- | tr -d '"'"'"' ')
[ -n "$TG_TOKEN" ] || exit 0

# 找最近 36h 内产出、台账中没有的那份日报
touch "$LEDGER"
LATEST=$(find "$OUTDIR" -maxdepth 1 -name "${JOB_ID}_*.txt" -mmin -2160 2>/dev/null | sort | tail -1)
[ -n "$LATEST" ] || exit 0
BASE=$(basename "$LATEST")
grep -qxF "$BASE" "$LEDGER" && exit 0

log "发现未确认送达的日报: $BASE"

RESULT=$(TG_TOKEN="$TG_TOKEN" python3 - "$LATEST" <<'PY'
import json, os, re, sys, time, urllib.parse, urllib.request

path  = sys.argv[1]
token = os.environ["TG_TOKEN"]          # 走环境变量，不进命令行（ps 可见）
chat, thread = "-1003988268482", "56995"

raw = open(path, encoding="utf-8").read()
raw = re.sub(r"^Cronjob Response:.*?\n-+\n", "", raw, flags=re.S)   # 去 cron 抬头
raw = re.sub(r"\nTo stop or manage this job.*$", "", raw, flags=re.S)  # 去尾部提示
body = raw.strip()
if not body:
    print("EMPTY"); sys.exit(0)

body = "⚠️ 以下日报由兜底通道补发（Hermes 网关投递未确认送达）\n\n" + body

LIMIT = 3500                              # Telegram 上限 4096，留余量
chunks, cur, n = [], [], 0
for line in body.split("\n"):
    if n + len(line) + 1 > LIMIT and cur:
        chunks.append("\n".join(cur)); cur, n = [], 0
    cur.append(line); n += len(line) + 1
if cur:
    chunks.append("\n".join(cur))

for i, ch in enumerate(chunks, 1):
    data = {"chat_id": chat, "text": ch, "disable_web_page_preview": "true",
            "message_thread_id": thread}
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=urllib.parse.urlencode(data).encode())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            if not json.loads(r.read().decode()).get("ok"):
                print(f"FAIL chunk{i}: api ok=false"); sys.exit(1)
    except Exception as e:
        print(f"FAIL chunk{i}: {type(e).__name__} {str(e)[:80]}"); sys.exit(1)
    time.sleep(1.2)                        # 避开 Telegram 限流

print(f"OK {len(chunks)} chunks")
PY
)

log "发送结果: $RESULT"
case "$RESULT" in
  OK*)    echo "$BASE" >> "$LEDGER"; log "已记入台账，不再重发" ;;
  EMPTY*) echo "$BASE" >> "$LEDGER"; log "正文为空，记台账避免空转" ;;
  *)      log "未送达，下轮重试" ;;
esac
