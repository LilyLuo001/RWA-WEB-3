#!/usr/bin/env python3
"""L1 取数（浏览器后端，零预算）—— 逐个访问名单账号主页，抓取最近帖子，
规范化后写入 data/raw/（复用 fetch_posts 的存储与去重）。

用法：
  python3 scripts/fetch_browser.py                  # 无头抓全部名单
  python3 scripts/fetch_browser.py --headed         # 可见窗口
  python3 scripts/fetch_browser.py --accounts Ondo Securitize
  python3 scripts/fetch_browser.py --per-account 15
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_accounts, load_state, save_state  # noqa: E402
from fetch_posts import append_raw  # noqa: E402
from publish import audit  # noqa: E402
from x_browser import get_playwright_and_context, is_logged_in  # noqa: E402

BLOCK_MARKERS = (
    "unusual activity", "Your account is temporarily limited",
    "异常活动", "验证你", "captcha", "Verify your identity",
)

STATUS_HREF = re.compile(r"/status/(\d+)")


def parse_count(s: str):
    s = (s or "").strip().replace(",", "")
    if not s:
        return 0
    m = re.match(r"^([\d.]+)([KMB]?)$", s, re.I)
    if not m:
        return 0
    n = float(m.group(1))
    mult = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[m.group(2).upper()]
    return int(n * mult)


def detect_block(page) -> bool:
    try:
        body = (page.content() or "").lower()
    except Exception:
        return False
    return any(m.lower() in body for m in BLOCK_MARKERS)


def scrape_profile(page, handle: str, per_account: int) -> list[dict]:
    """访问 /handle，解析时间线上的文章卡片为规范记录。"""
    page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(random.randint(2000, 4000))
    try:
        page.wait_for_selector('article[data-testid="tweet"]', timeout=15000)
    except Exception:
        return []

    # 轻微滚动以加载更多
    for _ in range(2):
        page.mouse.wheel(0, 1800)
        page.wait_for_timeout(random.randint(900, 1600))

    records: list[dict] = []
    seen_ids: set[str] = set()
    for art in page.locator('article[data-testid="tweet"]').all()[: per_account * 2]:
        try:
            rec = parse_article(art, handle)
        except Exception:
            continue
        if rec and rec["id"] not in seen_ids:
            seen_ids.add(rec["id"])
            records.append(rec)
        if len(records) >= per_account:
            break
    return records


def parse_article(art, profile_handle: str) -> dict | None:
    # post id
    hrefs = [a.get_attribute("href") for a in art.locator('a[href*="/status/"]').all()]
    pid = None
    for h in hrefs:
        m = STATUS_HREF.search(h or "")
        if m:
            pid = m.group(1)
            break
    if not pid:
        return None

    # 作者（User-Name 区第一个非 status 链接）
    author = profile_handle
    uname = art.locator('div[data-testid="User-Name"]')
    if uname.count():
        for a in uname.first.locator("a").all():
            h = a.get_attribute("href") or ""
            if h.startswith("/") and "/status/" not in h and len(h) > 1:
                author = h.strip("/")
                break

    # 文本
    text = ""
    tloc = art.locator('div[data-testid="tweetText"]')
    if tloc.count():
        text = tloc.first.inner_text()

    # 时间
    created = None
    ttime = art.locator("time[datetime]")
    if ttime.count():
        created = ttime.first.get_attribute("datetime")

    # 互动数
    def metric(testid: str):
        loc = art.locator(f'button[data-testid="{testid}"] div[dir="auto"] span, '
                          f'button[data-testid="{testid}"]')
        if loc.count():
            return parse_count(loc.first.inner_text())
        return 0

    metrics = {
        "like": metric("like"),
        "retweet": metric("retweet"),
        "reply": metric("reply"),
        "quote": 0,  # DOM 里不稳定，留空 —— 不估算
        "impression": None,
    }

    is_reply = bool(re.match(r"^Replying to ", text or ""))

    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": pid,
        "author_id": None,
        "author_handle": author,
        "author_name": None,
        "author_followers": None,
        "tier": None,
        "created_at": created,
        "text": text,
        "lang": None,
        "metrics": metrics,
        "is_retweet": author.lower() != profile_handle.lower(),
        "is_reply": is_reply,
        "in_reply_to": None,
        "quoted_post_id": None,
        "conversation_id": None,
        "urls": [],
        "mentions": [],
        "source": "browser",
        "fetched_at": now,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="浏览器取数")
    ap.add_argument("--per-account", type=int, default=10)
    ap.add_argument("--accounts", nargs="*", help="只抓这些 handle")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--channel", help="如 chrome")
    args = ap.parse_args()

    accounts = load_accounts()
    if not accounts:
        raise SystemExit("accounts.yaml 名单为空。")
    if args.accounts:
        want = {h.lower() for h in args.accounts}
        accounts = [a for a in accounts if a.get("handle", "").lower() in want]
        if not accounts:
            raise SystemExit("指定的 handle 不在名单里。")

    # 随机顺序，降低模式化痕迹
    random.shuffle(accounts)

    pw, ctx = get_playwright_and_context(headless=not args.headed, channel=args.channel)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    if not is_logged_in(page):
        ctx.close(); pw.stop()
        raise SystemExit("未登录或会话失效。先运行：python3 scripts/x_browser.py --login")

    total_new = total_dup = 0
    fails = []
    for a in accounts:
        h = a["handle"]
        try:
            recs = scrape_profile(page, h, args.per_account)
        except Exception as e:
            fails.append(f"@{h}: {type(e).__name__}")
            continue
        if not recs:
            fails.append(f"@{h}: 0 条（可能受限或页面变更）")
        # 补 tier
        for r in recs:
            r["tier"] = a.get("tier")
        new, dup = append_raw(recs)
        total_new += new
        total_dup += dup
        print(f"  @{h}: 抓到 {len(recs)} 条（新 {new}）")
        save_state("last_fetch", {
            "at": datetime.now(timezone.utc).isoformat(), "handle": h,
        })
        if detect_block(page):
            audit("blocked_signal", {"during": "fetch", "handle": h})
            print("\n⛔ 检测到风控/验证页面，提前终止。让账号安静 24 小时。")
            break
        time.sleep(random.uniform(3, 8))

    ctx.close(); pw.stop()
    print(f"\n✅ 新入库 {total_new} 条，重复 {total_dup} 条 → data/raw/")
    if fails:
        print("⚠️  异常：")
        for f in fails:
            print("   ", f)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(130)
