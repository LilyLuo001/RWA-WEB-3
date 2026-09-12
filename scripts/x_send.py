#!/usr/bin/env python3
"""浏览器发送层 —— 在已登录会话里真正执行 回复 / 发帖 / 点赞。

选择器策略：只用 X 稳定的 data-testid，避免 class 名（会变）。
每一步都验证结果，失败返回原因而不是假装成功。

用法（一般通过 publish.py 调用，也可单测）：
  .venv/bin/python scripts/x_send.py --post "测试文本"            # dry-run 打印
  .venv/bin/python scripts/x_send.py --post "..." --yes
  .venv/bin/python scripts/x_send.py --reply sampledata_acct 9001 "文本" --yes
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_settings, quota_summary  # noqa: E402

TOAST_CHECK_MS = 1500


def _human_type(page, locator, text: str) -> None:
    locator.click()
    page.wait_for_timeout(random.randint(300, 800))
    page.keyboard.type(text, delay=random.randint(28, 55))


def _toast_text(page) -> str:
    try:
        loc = page.locator('[data-testid="toast"]')
        if loc.count():
            return loc.first.inner_text()[:200]
    except Exception:
        pass
    return ""


def send_reply(page, author: str, post_id: str, text: str) -> tuple[bool, str]:
    """打开原帖 → 点回复 → 输入 → 发送 → 验证。"""
    url = f"https://x.com/{author}/status/{post_id}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector('article', timeout=15000)
        page.wait_for_timeout(random.randint(1200, 2500))
        page.locator('article button[data-testid="reply"]').first.click()
        page.wait_for_selector('div[data-testid="tweetTextarea_0"]', timeout=8000)
        _human_type(page, page.locator('div[data-testid="tweetTextarea_0"]').first, text)
        page.locator('div[data-testid="tweetButtonInline"]').first.click()
        # 验证：composer 消失 或 页面出现回复文本
        deadline = time.time() + 10
        while time.time() < deadline:
            page.wait_for_timeout(800)
            if page.locator('div[data-testid="tweetTextarea_0"]').count() == 0:
                return True, "composer closed"
            toast = _toast_text(page)
            if "posted" in toast.lower():
                return True, toast
        return False, f"发送后状态未确认。toast: {_toast_text(page)!r}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e} · toast: {_toast_text(page)!r}"


def send_post(page, text: str) -> tuple[bool, str]:
    try:
        page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector('div[data-testid="tweetTextarea_0"]', timeout=10000)
        _human_type(page, page.locator('div[data-testid="tweetTextarea_0"]').first, text)
        page.locator('div[data-testid="tweetButton"]').first.click()
        deadline = time.time() + 10
        while time.time() < deadline:
            page.wait_for_timeout(800)
            if page.locator('div[data-testid="tweetTextarea_0"]').count() == 0:
                return True, "posted"
            toast = _toast_text(page)
            if "posted" in toast.lower():
                return True, toast
        return False, f"未确认。toast: {_toast_text(page)!r}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e} · toast: {_toast_text(page)!r}"


def like_post(page, author: str, post_id: str) -> tuple[bool, str]:
    try:
        page.goto(f"https://x.com/{author}/status/{post_id}",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector('article', timeout=15000)
        btn = page.locator('article button[data-testid="like"]').first
        btn.click()
        page.wait_for_timeout(random.randint(800, 1500))
        pressed = btn.get_attribute("aria-pressed")
        label = btn.get_attribute("aria-label") or ""
        if pressed == "true" or "Unlike" in label:
            return True, "liked"
        if "Like" not in label and pressed != "false":
            return True, "clicked"
        return False, f"aria-pressed={pressed} label={label!r}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def quote_post(page, author: str, post_id: str, text: str) -> tuple[bool, str]:
    """引用转发（Quote Retweet）—— 借势流：大V爆帖 + 你的深度二创。
    走 /compose/post 页面（带 quote 参数），比点 UI 按钮更稳。"""
    try:
        url = (f"https://x.com/compose/post?quote_url="
               f"https%3A%2F%2Fx.com%2F{author}%2Fstatus%2F{post_id}")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector('div[data-testid="tweetTextarea_0"]', timeout=10000)
        _human_type(page, page.locator('div[data-testid="tweetTextarea_0"]').first, text)
        page.locator('div[data-testid="tweetButton"]').first.click()
        deadline = time.time() + 10
        while time.time() < deadline:
            page.wait_for_timeout(800)
            if page.locator('div[data-testid="tweetTextarea_0"]').count() == 0:
                return True, "quoted"
            toast = _toast_text(page)
            if "posted" in toast.lower():
                return True, toast
        return False, f"未确认。toast: {_toast_text(page)!r}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e} · toast: {_toast_text(page)!r}"


def _newest_own_post_id(page, handle: str) -> str | None:
    """发帖后回自己主页取最新一条的 id。

    为什么不从 URL 抠：send_post 发完之后浏览器停在 /compose/post，
    URL 里根本没有 /status/ —— 旧实现在这里必然拿到垃圾值，
    导致推串第 2 条去访问一个拼接错误的地址。
    """
    import re
    try:
        page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector('article[data-testid="tweet"]', timeout=15000)
        page.wait_for_timeout(1200)
        for art in page.locator('article[data-testid="tweet"]').all()[:4]:
            # 跳过置顶帖，它不是刚发的那条
            try:
                if "Pinned" in art.inner_text(timeout=2000) or "已置顶" in art.inner_text(timeout=2000):
                    continue
            except Exception:
                pass
            for a in art.locator('a[href*="/status/"]').all():
                m = re.search(r"/status/(\d+)", a.get_attribute("href") or "")
                if m:
                    return m.group(1)
    except Exception:
        return None
    return None


def send_thread(page, texts: list[str], handle: str | None = None) -> tuple[bool, str]:
    """长推串。逐条发送，第 i 条回复第 i-1 条。

    handle 不传就自动探测当前登录账号 —— 手填的值和实际登录账号不一致时，
    推串会静默发错地方。
    """
    from x_browser import get_own_handle
    try:
        if not handle:
            handle = get_own_handle(page)
        if not handle:
            return False, "无法确定当前登录账号的 handle，推串中止（不猜）"

        ids: list[str] = []
        for i, text in enumerate(texts):
            if i == 0:
                ok, detail = send_post(page, text)
            else:
                ok, detail = send_reply_to_own(page, ids[-1], text)
            if not ok:
                return False, f"第 {i+1} 条失败: {detail}（已发出 {len(ids)} 条，需手动收尾）"

            pid = _newest_own_post_id(page, handle)
            if not pid:
                return False, (f"第 {i+1} 条已发出，但取不到它的 post id，"
                               f"无法续接。已发 {len(ids)+1} 条，需手动收尾")
            if pid in ids:
                return False, (f"第 {i+1} 条取到的 id 与上一条相同（{pid}），"
                               f"疑似未真正发出。中止以免重复发送")
            ids.append(pid)
            page.wait_for_timeout(random.randint(4000, 9000))
        return True, f"thread of {len(ids)}: {ids}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def send_reply_to_own(page, prev_id: str, text: str) -> tuple[bool, str]:
    """回复自己刚发的帖子（推串续接）。"""
    try:
        url = f"https://x.com/i/web/status/{prev_id}"
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector('article', timeout=15000)
        page.locator('article button[data-testid="reply"]').first.click()
        page.wait_for_selector('div[data-testid="tweetTextarea_0"]', timeout=8000)
        _human_type(page, page.locator('div[data-testid="tweetTextarea_0"]').first, text)
        page.locator('div[data-testid="tweetButtonInline"]').first.click()
        deadline = time.time() + 10
        while time.time() < deadline:
            page.wait_for_timeout(800)
            if page.locator('div[data-testid="tweetTextarea_0"]').count() == 0:
                return True, "threaded"
            toast = _toast_text(page)
            if "posted" in toast.lower():
                return True, toast
        return False, f"未确认。toast: {_toast_text(page)!r}"
    except Exception as e:
        visiting = _toast_text(page)
        return False, f"{type(e).__name__}: {e} · toast: {visiting!r}"


def main() -> int:
    ap = argparse.ArgumentParser(description="浏览器发送")
    ap.add_argument("--post", help="主帖文本")
    ap.add_argument("--reply", nargs=2, metavar=("AUTHOR", "POST_ID"), help="回复目标")
    ap.add_argument("--reply-text", default=None, help="回复文本（配合 --reply）")
    ap.add_argument("--like", nargs=2, metavar=("AUTHOR", "POST_ID"))
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()

    from x_browser import get_playwright_and_context, is_logged_in

    text = args.post or args.reply_text or ""
    target = (args.reply[0], args.reply[1]) if args.reply else (
        (args.like[0], args.like[1]) if args.like else None)

    kind = "like" if args.like else ("reply" if args.reply else "post")
    print(f"类型：{kind}  文本：{text[:80]!r}  目标：{target}")
    if not args.yes:
        print("[dry-run] 未发送。加 --yes")
        return 0

    # 限速闸门（与 API 路径同一道门）
    from common import check_safety, record_action
    ok, reason = check_safety(load_settings(), kind)
    if not ok:
        print(f"⛔ {reason}")
        return 1

    pw, ctx = get_playwright_and_context(headless=not args.headed)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    if not is_logged_in(page):
        ctx.close(); pw.stop()
        raise SystemExit("未登录。先运行：python3 scripts/x_browser.py --login")
    page.wait_for_timeout(random.randint(1500, 3500))

    if args.reply:
        ok, detail = send_reply(page, args.reply[0], args.reply[1], text)
    elif args.like:
        ok, detail = like_post(page, args.like[0], args.like[1])
    else:
        ok, detail = send_post(page, text)

    ctx.close(); pw.stop()
    if ok:
        record_action(kind)
        print(f"✅ 成功（{detail}）  {quota_summary(load_settings())}")
        return 0
    print(f"❌ 失败：{detail}")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(130)
