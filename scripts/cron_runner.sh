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

# ---- 浏览器互斥锁 ----
# Playwright 的 persistent profile 同一时刻只能被一个进程打开。
# fetch(20min) 和 comment_watch(2h) 必然重叠，单次抓取超过 20 分钟还会自己撞自己。
# 撞上时的症状是假的「会话失效」——会误导人去重新登录。
LOCK="state/browser.lock"

# 上一轮没干净退出时，chrome-headless-shell 会残留并占住 profile 的 SingletonLock，
# 后续运行拿不到 profile，Playwright 报的却是「会话失效」——会误导人去重新登录。
# 真实原因是孤儿进程，不是登录态。
reap_orphans() {
  local prof; prof="$(pwd)/state/browser-profile"
  local pids; pids=$(pgrep -f "user-data-dir=$prof" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "🧹 清理残留浏览器进程: $(echo "$pids" | tr '\n' ' ')"
    echo "$pids" | xargs kill 2>/dev/null || true
    sleep 3
    pids=$(pgrep -f "user-data-dir=$prof" 2>/dev/null || true)
    [ -n "$pids" ] && echo "$pids" | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
  rm -f "$prof"/Singleton* 2>/dev/null || true
}

acquire_lock() {
  local waited=0 max=${1:-300}
  while ! mkdir "$LOCK" 2>/dev/null; do
    # 陈旧锁清理：持有超过 25 分钟视为残留（进程已死）
    if [ -d "$LOCK" ]; then
      local age=$(( $(date +%s) - $(stat -f %m "$LOCK" 2>/dev/null || echo 0) ))
      if [ "$age" -gt 1500 ]; then
        echo "⚠️  清理陈旧锁（持有 ${age}s）"
        rm -rf "$LOCK"
        continue
      fi
    fi
    if [ "$waited" -ge "$max" ]; then
      echo "⏭  浏览器被占用超过 ${max}s，本轮跳过（不是错误，下一轮会补）"
      return 1
    fi
    sleep 15
    waited=$((waited + 15))
  done
  trap 'rm -rf "$LOCK"' EXIT INT TERM
  reap_orphans   # 拿到锁之后再清理，确保清掉的一定是孤儿而不是同僚
  return 0
}

run_claude() {
  # $1 = prompt 文件  $2 = 期望的成功标记
  local prompt_file="$1" marker="$2"
  if [ ! -x "$CLAUDE" ]; then
    echo "❌ 找不到 claude CLI ($CLAUDE)，判断层无法执行"
    return 1
  fi
  local out attempt
  # 判断层会因额度/鉴权临时 403。静默失败的后果是"看起来在跑，其实什么都没产出"，
  # 所以重试 + 失败必须可见。
  for attempt in 1 2 3; do
    # 两个坑：
    #  1) 直接把规范文档塞进 -p，模型会当成"一份文档"来读，回你一句
    #     "我看到了这个文件，你想让我做什么？" —— 必须显式下达执行指令
    #  2) 不重定向 stdin 会卡在等标准输入（no stdin data received in 3s）
    out=$("$CLAUDE" -p "立即执行下面这份工作流程规范。这不是待讨论的文档，\
是你现在就要完成的任务：读取数据、产出文件、按规范末尾的要求发邮件，\
最后在 stdout 打印成功标记。不要询问、不要复述规范、不要征求确认。

--- 规范开始 ---
$(cat "$prompt_file")
--- 规范结束 ---

现在开始执行。" \
          --allowedTools "$TOOLS" \
          --permission-mode acceptEdits \
          --add-dir "$ROOT" < /dev/null 2>&1)
    if echo "$out" | grep -q "$marker"; then
      echo "$out" | tail -20
      echo "✅ $marker"
      return 0
    fi
    if echo "$out" | grep -qiE "403|rate limit|authenticate|usage limit|overloaded"; then
      echo "⏳ 第 $attempt 次受限（$(echo "$out" | grep -oiE '40[0-9]|rate limit|usage limit' | head -1)），等待后重试"
      sleep $((attempt * 120))
      continue
    fi
    break
  done
  echo "$out" | tail -20
  echo "⚠️  未见成功标记 $marker —— 判断层三次均未完成"
  # 失败要让人知道，不然管道看起来在跑其实什么都没出
  local stamp="state/last_judge_fail"
  date +%s > "$stamp"
  $VENV_PY - <<'PYEOF' 2>/dev/null || true
import sys, pathlib
sys.path.insert(0, "scripts")
from notify import send_email
send_email("⚠️ rwa-signal 判断层失败",
           "claude -p 连续三次未完成。\n\n"
           "常见原因：额度用尽 / 鉴权 403。\n"
           "管道仍在抓数据，但晨报和评论草稿不会产出，直到判断层恢复。\n\n"
           "自查：claude -p \"reply OK\" --max-turns 1\n"
           "日志：data/cron.log")
PYEOF
  return 1
}

case "${1:-}" in
  fetch)
    acquire_lock 120 || exit 0
    $VENV_PY scripts/fetch_browser.py --per-account 6
    ;;
  comment_watch)
    # 抓取要锁，判断层不需要（它只读文件）—— 所以抓完就放锁
    if acquire_lock 600; then
      $VENV_PY scripts/fetch_browser.py --per-account 6
      rm -rf "$LOCK"; trap - EXIT INT TERM
    fi
    run_claude prompts/comment_watch.md "WATCH_OK"
    ;;
  digest)
    if acquire_lock 900; then
      $VENV_PY scripts/fetch_browser.py --per-account 8
      rm -rf "$LOCK"; trap - EXIT INT TERM
    fi
    run_claude prompts/morning_digest.md "DIGEST_OK"
    ;;
  follow)
    # 每日一批。冷号安全节奏：每天 ≤8 个，不是每 2 小时一批。
    acquire_lock 600 || exit 0
    $VENV_PY scripts/follow_list.py --max 8
    ;;
  status)
    acquire_lock 300 || exit 0
    $VENV_PY scripts/x_browser.py --status
    $VENV_PY scripts/stats.py --days 2
    ;;
  *)
    echo "usage: $0 {fetch|comment_watch|digest|follow|status}" >&2
    exit 2
    ;;
esac
