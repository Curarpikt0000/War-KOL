#!/usr/bin/env bash
# War-KOL 公网发布 → Cloudflare Pages（项目 war-kol / war-kol.pages.dev）
#
# ★ 为什么需要这个脚本（2026-09-25 实测发现的洞）：
#   publish.sh 一直只做「GitHub push + 内网 vibe 镜像」两端。
#   但 Curarpikt0000 账号被封后 GitHub Pages 已死——
#   curl https://curarpikt0000.github.io/War-KOL/ 返回 404（实测）。
#   Cloudflare 那份是几天前手工传的，此后再没人更新 → 停在 09-19 的旧数据，
#   而日报里却一直贴着 GitHub Pages 链接。
#   = 「push 成功」被当成了「公网能看到最新的」，典型的用做过了代替做对了。
#
# ⇒ 把 Cloudflare 发布固化进流程，每次 publish.sh 自动跑，且靠内容 md5 判等幂等。
#
# ★ 判定铁律：成功必须由 EXIT CODE + 'Deployment complete' + 线上 md5 三者共同判定，
#   禁止 `cmd && echo ok` 冒充成功（HTTP 200 + 非空 ≠ 数据对）。
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"

CF_PROJECT="war-kol"
CF_DOMAIN="war-kol.pages.dev"
DIST="scratch/cfdist"
LOG="scratch/cloudflare.log"
mkdir -p scratch

log() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }

[ -s "$ROOT/index.html" ] || { log "无 index.html，跳过"; exit 0; }

# ---- 闸1：内网红线（与 publish.sh 的 SCAN_FILES 同口径）----
# ⚠️ 关键词必须带 \b 词边界：2026-09-25 实测 'bastion' 无边界时会被军事术语
#    「pro-SSBN bastion operations」误伤，'presto' 同理曾被人名误伤。
#    放宽关键词是危险的，加边界不是——它只是不再匹配单词内部。
if grep -qniE "code\.uber\.internal|uberinternal|\baifx\b|\bpresto\b|chao\.jin|hermeschao|ChaoProjects|ntn_[A-Za-z0-9]{15}|secret_[A-Za-z0-9]{15}|vibe-mcp|\bcerberus\b|@uber\.com|\bdevpod\b" \
     "$ROOT/index.html"; then
  log "✗ 红线命中，拒绝发布公网"
  echo "public: RED-LINE HIT，拒绝 Cloudflare 发布" >&2
  exit 3
fi

# ---- 闸2：产物体量（防半成品覆盖掉好版本）----
SZ=$(stat -c%s "$ROOT/index.html")
if [ "$SZ" -lt 1000000 ]; then
  log "✗ index.html 仅 ${SZ}B（<1MB），疑似半成品，已阻断"
  echo "public: index.html 过小 ${SZ}B，已阻断" >&2
  exit 4
fi
# 渲染自检：必须真有数据载荷，别发个空壳
grep -q "var STMTS" "$ROOT/index.html" || {
  log "✗ 产物缺 var STMTS 载荷，已阻断"; echo "public: 缺 STMTS 载荷" >&2; exit 4; }

# ---- 幂等：线上已是这份字节就不重传（18MB 上传不便宜）----
LOCAL_MD5=$(md5sum "$ROOT/index.html" | cut -d' ' -f1)
LIVE_MD5=$(curl -s --max-time 120 "https://$CF_DOMAIN/?cb=$(date +%s)" 2>/dev/null | md5sum | cut -d' ' -f1)
if [ "$LOCAL_MD5" = "$LIVE_MD5" ]; then
  log "线上已是当前产物（md5 ${LOCAL_MD5:0:12}），跳过"
  exit 0
fi

# ---- 凭据：只从 .env 读，绝不硬编码 ----
if [ -f "$HOME/.hermes/.env" ]; then set -a; . "$HOME/.hermes/.env" 2>/dev/null; set +a; fi
if [ -z "${CLOUDFLARE_API_TOKEN:-}" ] || [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then
  log "✗ 缺 CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID"
  echo "public: 缺 Cloudflare 凭据" >&2; exit 5
fi

# ⚠️ 禁用 `npx wrangler@latest`：npx 走本机默认 npm 源（Uber 内网 unpm），
#    凭据过期 → E401 → cron 静默失败。一律用本地固定副本。
WRANGLER="$HOME/opt/wrangler/node_modules/.bin/wrangler"
if [ ! -x "$WRANGLER" ]; then
  log "✗ 本地 wrangler 缺失 ($WRANGLER)"
  echo "public: 本地 wrangler 缺失，不回退 npx（内网源会 E401）" >&2; exit 5
fi

rm -rf "$DIST"; mkdir -p "$DIST"
cp "$ROOT/index.html" "$DIST/index.html"

OUT=$(cd "$ROOT" && timeout 900 "$WRANGLER" pages deploy "$DIST" \
        --project-name="$CF_PROJECT" --branch=main --commit-dirty=true 2>&1 \
        | grep -vE '^npm http|cache skip|cache hit|cache revalidated')
RC=$?
if [ "$RC" -ne 0 ] || ! echo "$OUT" | grep -q "Deployment complete"; then
  log "✗ wrangler 部署失败 rc=$RC: $(echo "$OUT" | tail -3 | tr '\n' ' ')"
  echo "public: Cloudflare 部署失败 rc=$RC" >&2
  echo "$OUT" | tail -5 >&2
  exit 6
fi

# ---- 线上实测：部署完成 ≠ 内容对。必须比 md5，不看状态码 ----
sleep 20
VERIFY=$(curl -s --max-time 120 "https://$CF_DOMAIN/?cb=$(date +%s)" 2>/dev/null | md5sum | cut -d' ' -f1)
if [ "$VERIFY" != "$LOCAL_MD5" ]; then
  # CDN 传播可能慢，再等 60s 复验一次
  sleep 60
  VERIFY=$(curl -s --max-time 120 "https://$CF_DOMAIN/?cb=$(date +%s)" 2>/dev/null | md5sum | cut -d' ' -f1)
fi
if [ "$VERIFY" != "$LOCAL_MD5" ]; then
  log "✗ 线上 md5 ${VERIFY:0:12} ≠ 本地 ${LOCAL_MD5:0:12}（部署报成功但内容没对上）"
  echo "public: 线上 md5 与本地不一致" >&2; exit 7
fi

log "✓ 已发布并校验 md5 ${LOCAL_MD5:0:12} → https://$CF_DOMAIN"
echo "public: deployed -> https://$CF_DOMAIN"
exit 0
