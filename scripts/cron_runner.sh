#!/bin/bash
# rwa-signal cron 入口。所有定时任务走这里，失败时把 stderr 落盘。
#
# 关键：判断层通过 `claude -p` 无头调用真正执行，不是打印一行提示。
# （第一版的 digest 分支只 echo 了一句话，等于晨报根本不会产生。）
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
LOG="data/cron.log"
mkdir -p data
exec >>"$LOG" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') cron_runner $* ==="

VENV_PY=".venv/bin/python"
CLAUDE="$HOME/.local/bin/claude"
TOOLS="Read,Write,Edit,Glob,Grep,Bash,WebSearch,WebFetch"

run_claude() {
  # $1 = prompt 文件  $2 = 期望的成功标记
  local prompt_file="$1" marker="$2"
  if [ ! -x "$CLAUDE" ]; then
    echo "❌ 找不到 claude CLI ($CLAUDE)，判断层无法执行"
    return 1
  fi
  local out
  out=$("$CLAUDE" -p "$(cat "$prompt_file")" \
        --allowedTools "$TOOLS" \
        --permission-mode acceptEdits \
        --add-dir "$ROOT" 2>&1)
  echo "$out" | tail -25
  if echo "$out" | grep -q "$marker"; then
    echo "✅ $marker"
    return 0
  fi
  echo "⚠️  未见成功标记 $marker —— 判断层可能没跑完"
  return 1
}

case "${1:-}" in
  fetch)
    $VENV_PY scripts/fetch_browser.py --per-account 6
    ;;
  comment_watch)
    $VENV_PY scripts/fetch_browser.py --per-account 6
    run_claude prompts/comment_watch.md "WATCH_OK"
    ;;
  digest)
    $VENV_PY scripts/fetch_browser.py --per-account 8
    run_claude prompts/morning_digest.md "DIGEST_OK"
    ;;
  follow)
    # 每日一批。冷号安全节奏：每天 ≤8 个，不是每 2 小时一批。
    $VENV_PY scripts/follow_list.py --max 8
    ;;
  status)
    $VENV_PY scripts/x_browser.py --status
    $VENV_PY scripts/stats.py --days 2
    ;;
  *)
    echo "usage: $0 {fetch|comment_watch|digest|follow|status}" >&2
    exit 2
    ;;
esac
