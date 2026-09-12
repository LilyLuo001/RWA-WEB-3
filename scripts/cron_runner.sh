#!/bin/bash
# rwa-signal cron 入口。所有定时任务走这里，失败时把 stderr 落盘。
set -u
cd "$(dirname "$0")/.."
LOG="data/cron.log"
mkdir -p data
exec >>"$LOG" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') cron_runner $* ==="

VENV_PY=".venv/bin/python"

case "$1" in
  fetch)
    # L1 取数：抓名单账号最新帖。每 20 分钟一次。
    $VENV_PY scripts/fetch_browser.py --per-account 6
    ;;
  comment_watch)
    # L2 信号：抓完数据后跑机会扫描（Claude 层在对话里执行，这里只取数）。
    $VENV_PY scripts/fetch_browser.py --per-account 6
    echo "--- comment_watch: 见 prompts/comment_watch.md（在 Claude Code 会话里执行判断层）---"
    ;;
  digest)
    # 晨报：7 点生成并发邮件。
    $VENV_PY scripts/fetch_browser.py --per-account 6
    # digest 的判断层在 Claude Code 里跑（需要我来读数据、写晨报、发邮件）
    echo "--- digest: 见 prompts/morning_digest.md ---"
    ;;
  status)
    # 每晚检查会话有效性 + 账号健康度
    $VENV_PY scripts/x_browser.py --status
    ;;
  *)
    echo "usage: $0 {fetch|comment_watch|digest|status}" >&2
    exit 2
    ;;
esac
