#!/usr/bin/env python3
"""X 浏览器会话管理（零预算方案的核心）。

原理：Playwright 持久化 profile。你第一次手动登录，cookie 存在
state/browser-profile/（已 gitignore），之后脚本复用该会话。
不存密码、不碰密码 —— 密码只经过你自己的手。

用法：
  python3 scripts/x_browser.py --login     # 第一次：弹窗手动登录（唯一需要你参与的一步）
  python3 scripts/x_browser.py --status    # 检查会话是否仍然有效
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import STATE  # noqa: E402

PROFILE_DIR = STATE / "browser-profile"

STEALTH_JS = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"


def get_playwright_and_context(headless: bool = True, channel: str | None = None):
    """返回 (playwright, context)。调用方负责 close 两者。"""
    from playwright.sync_api import sync_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    pw = sync_playwright().start()
    kwargs = dict(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        viewport={"width": 1320, "height": 900},
        locale="en-US",
        args=["--disable-blink-features=AutomationControlled"],
    )
    if channel:  # 例如 channel="chrome" 用系统 Chrome，指纹更自然
        kwargs["channel"] = channel
    ctx = pw.chromium.launch_persistent_context(**kwargs)
    ctx.add_init_script(STEALTH_JS)
    return pw, ctx


def is_logged_in(page, timeout_ms: int = 20000) -> bool:
    """用 /home 是否被重定向到登录流来判断。"""
    try:
        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(2500)
    except Exception:
        return False
    url = page.url
    if "/i/flow/login" in url or "login" in url.split("?")[0]:
        return False
    try:
        return page.locator(
            '[data-testid="SideNav_AccountSwitcher_Button"], [data-testid="AppTabBar_Home_Link"]'
        ).first.is_visible(timeout=8000)
    except Exception:
        return False


def cmd_login(channel: str | None, timeout_min: int = 20) -> int:
    """打开浏览器等你登录。全程被动观察页面状态，绝不主动跳转 ——
    任何 goto 都会打断你正在填的表单并触发 X 风控（上一版的 bug 就在这）。"""
    pw, ctx = get_playwright_and_context(headless=False, channel=channel)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        page.goto("https://x.com/login", wait_until="domcontentloaded", timeout=60000)
    except Exception:
        pass  # 加载慢没关系，窗口已经打开
    print("浏览器已打开，这次不会刷新/跳转你的页面，慢慢来。")
    print("验证页出现就按提示做完。最长等 20 分钟，成功后自动保存会话。")
    logged = False
    deadline = time.time() + timeout_min * 60
    while time.time() < deadline:
        try:
            page.wait_for_timeout(4000)
            if page.locator('div[data-testid="SideNav_AccountSwitcher_Button"]').count() > 0:
                logged = True
                break
        except Exception as e:
            if "closed" in str(e).lower():
                print("浏览器窗口被关闭了。准备好之后重新运行 --login 即可，随时都行。")
                try:
                    pw.stop()
                except Exception:
                    pass
                return 1
    if logged:
        print("✅ 检测到已登录。会话已实时保存在 state/browser-profile/。")
        print("   这个窗口可以关掉了（也可以留着继续浏览）。")
    else:
        print("⏱ 20 分钟到了。没关系，重新运行 --login 再来一次。")
    try:
        ctx.close()
        pw.stop()
    except Exception:
        pass
    return 0 if logged else 1


def cmd_status(channel: str | None) -> int:
    if not PROFILE_DIR.exists() or not any(PROFILE_DIR.iterdir()):
        print("还没有会话。先运行：python3 scripts/x_browser.py --login")
        return 1
    pw, ctx = get_playwright_and_context(headless=True, channel=channel)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    ok = is_logged_in(page)
    ctx.close()
    pw.stop()
    print("✅ 会话有效" if ok else "❌ 会话已失效，需要重新 --login")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="X 浏览器会话")
    ap.add_argument("--login", action="store_true", help="弹窗手动登录（一次性）")
    ap.add_argument("--status", action="store_true", help="检查会话有效性")
    ap.add_argument("--channel", help="用系统浏览器内核，如 chrome")
    args = ap.parse_args()

    if args.login:
        return cmd_login(args.channel)
    if args.status:
        return cmd_status(args.channel)
    ap.print_help()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(130)
