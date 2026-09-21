#!/usr/bin/env bash
# 只列/杀真正的 daily_chain.sh 进程，排除 agent 自己的 wrapper shell。
# ★ 踩坑：pgrep -f 'daily_chain.sh' 会命中 agent 执行命令的那个 bash -c
#   （它的命令行里含这个字符串）→ kill 时把自己的 shell 杀掉，返回 SIGTERM。
#   判据改成：命令行必须【恰好】是 "bash scripts/daily_chain.sh"。
ACT="${1:-list}"
pids=$(pgrep -f 'daily_chain' | while read -r p; do
  cl=$(tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null | sed 's/ *$//')
  case "$cl" in
    "bash scripts/daily_chain.sh"|"/bin/bash scripts/daily_chain.sh") echo "$p" ;;
  esac
done)
if [ "$ACT" = "kill" ]; then
  for p in $pids; do kill "$p" 2>/dev/null; done
  echo "killed: ${pids:-none}"
else
  echo "chain pids: ${pids:-none}"
fi
