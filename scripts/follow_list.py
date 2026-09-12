#!/usr/bin/env python3
"""一次性/分批关注 accounts.yaml 里的名单。

冷账号安全策略：每次运行最多关注 --max 个（默认 8），随机间隔 6-18 秒。
已关注的记录在 state/followed.json，不会重复点。

用法：
  python3 scripts/follow_list.py                 # 无头模式关注（需已登录）
  python3 scripts/follow_list.py --headed        # 弹窗可见模式
  python3 scripts/follow_list.py --dry-run       # 只列出还要关注谁
  python3 scripts/follow_list.py --channel chrome
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_accounts, load_state, save_state  # noqa: E402
from publish import audit  # noqa: E402
from x_browser import get_playwright_and_context, is_logged_in  # noqa: E402

FOLLOW_TIMEOUT_MS = 15000

BLOCK_MARKERS = (
    "unusual activity", "Your account is temporarily limited",
    "异常活动", "验证你", "captcha", "Verify your identity",
)


def detect_block(page) -> bool:
    try:
        body = (page.content() or "").lower()
    except Exception:
        return False
    return any(m.lower() in body for m in BLOCK_MARKERS)


# 稳定选择器：button[data-testid$="-follow"]（testid 形如 "1368671059906469889-follow"）
FOLLOW_SEL = 'button[data-testid$="-follow"]'
UNFOLLOW_SEL = 'button[data-testid$="-unfollow"]'
# 已关注状态的按钮文字（英文 / 中文界面，中文是「正在关注」）
FOLLOWING_LABELS = {"following", "关注中", "正在关注", "已关注", "互相关注", "unfollow", "取消关注"}


def follow_one(page, handle: str) -> str:
    """返回 'followed' / 'already' / 'notfound' / 'blocked' / 'error:...'"""
    try:
        page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(random.randint(1800, 3500))

        if detect_block(page):
            return "blocked"

        # placementTracking 容器只存在于 profile header，避免抓到时间线里的按钮
        header_follow = page.locator(
            'div[data-testid="placementTracking"] button[data-testid$="-follow"]')
        header_unfollow = page.locator(
            'div[data-testid="placementTracking"] button[data-testid$="-unfollow"]')

        if header_unfollow.count() > 0:
            return "already"

        if header_follow.count() == 0:
            txt = ""
            try:
                txt = page.locator("main").inner_text(timeout=4000)
            except Exception:
                pass
            if "doesn't exist" in txt or "不存在" in txt or "suspended" in txt.lower() or "已冻结" in txt:
                return "notfound"
            if any(l in txt for l in FOLLOWING_LABELS):
                return "already"
            return "error: follow button not found"

        btn = header_follow.first
        btn.scroll_into_view_if_needed()
        page.wait_for_timeout(random.randint(400, 900))
        btn.click()
        page.wait_for_timeout(random.randint(1500, 2800))

        # 处理可能出现的确认弹层
        sheet = page.locator('[data-testid="confirmationSheetConfirm"]')
        if sheet.count():
            sheet.first.click()
            page.wait_for_timeout(random.randint(1200, 2000))

        if detect_block(page):
            return "blocked"

        # 终极验证：重新查询 header 按钮状态
        if page.locator(
                'div[data-testid="placementTracking"] button[data-testid$="-unfollow"]').count() > 0:
            return "followed"
        if page.locator(
                'div[data-testid="placementTracking"] button[data-testid$="-follow"]').count() == 0:
            return "followed"  # 按钮消失也说明状态变了
        # 刷新确认（有时 UI 慢）
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(random.randint(2000, 3000))
        if page.locator(
                'div[data-testid="placementTracking"] button[data-testid$="-unfollow"]').count() > 0:
            return "followed"
        return "error: click did not stick"
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description="关注 accounts.yaml 名单")
    ap.add_argument("--max", type=int, default=8, help="本次最多关注几个（冷账号别贪）")
    ap.add_argument("--headed", action="store_true", help="可见窗口模式")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--channel", help="如 chrome")
    args = ap.parse_args()

    accounts = load_accounts()
    if not accounts:
        raise SystemExit("accounts.yaml 名单为空。")

    followed = load_state("followed", {})
    todo = [a for a in accounts if a.get("handle") and a["handle"] not in followed]
    if not todo:
        print(f"全部 {len(accounts)} 个账号已关注。无操作。")
        return 0

    print(f"名单 {len(accounts)} 个，已关注 {len(followed)} 个，待关注 {len(todo)} 个：")
    for a in todo:
        print(f"  @{a['handle']}  [{a.get('tier')}]  {a.get('covers','')[:40]}")

    if args.dry_run:
        return 0

    pw, ctx = get_playwright_and_context(headless=not args.headed, channel=args.channel)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    if not is_logged_in(page):
        ctx.close(); pw.stop()
        raise SystemExit("未登录或会话失效。先运行：python3 scripts/x_browser.py --login")

    done = 0
    for a in todo[: args.max]:
        h = a["handle"]
        res = follow_one(page, h)
        ts = datetime.now(timezone.utc).isoformat()
        if res == "followed":
            followed[h] = {"at": ts}
            audit("follow", {"handle": h, "via": "browser"})
            print(f"  ✅ @{h} 已关注")
            done += 1
        elif res == "already":
            followed[h] = {"at": ts, "note": "already"}
            print(f"  ✔️  @{h} 已经关注过")
        elif res == "blocked":
            audit("blocked_signal", {"during": "follow", "handle": h})
            print(f"\n⛔ X 出现风控/验证页面。立即停止 —— 请手动打开浏览器完成验证，"
                  f"并让账号安静 24 小时再试。")
            break
        elif res == "notfound":
            print(f"  ❓ @{h} 账号不存在/被停用 —— 请核对 accounts.yaml")
            followed[h] = {"at": ts, "note": "notfound"}
        else:
            print(f"  ⚠️  @{h}: {res}")
        save_state("followed", followed)
        if done and done < len(todo[: args.max]):
            time.sleep(random.uniform(6, 18))

    ctx.close(); pw.stop()
    print(f"\n完成：本次新关注 {done} 个。剩余待关注 "
          f"{len([a for a in accounts if a.get('handle') not in followed])} 个（明天再跑一批）。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(130)
