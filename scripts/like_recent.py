#!/usr/bin/env python3
"""自动点赞 —— 给名单里值得的帖子点赞。

⚠️ **点赞是公开的。** 任何人都能查你赞过什么。所以这里不做无差别点赞：
赞了 meme 币帖，会直接拆掉正在建的严肃分析者定位。

筛选规则（三道）：
  1. tier 白名单：只赞 kol/reg/acad/issuer/inst/data，**跳过 watch**
     （watch 层是 BTCdayu/ZssBecker 这类，留在名单里只为感知情绪）
  2. 主题相关：帖子文本必须命中 RWA/代币化/监管/学术关键词
  3. 非转发、有实质文字

限速：settings.yaml 的 max_likes_per_day（默认 30），走 common.check_safety
同一道闸门。每次点赞之间随机 20-70 秒 —— 匀速是机器人特征。

用法：
  .venv/bin/python scripts/like_recent.py                 # dry-run，只列要赞什么
  .venv/bin/python scripts/like_recent.py --yes --max 6   # 真赞
"""
from __future__ import annotations

import argparse
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    check_safety, load_accounts, load_settings, load_state, quota_summary,
    record_action, save_state,
)
from fetch_posts import parse_ts, read_raw  # noqa: E402
from publish import audit  # noqa: E402

# 只赞这些 tier。watch 明确排除。
LIKE_TIERS = {"kol", "reg", "acad", "issuer", "inst", "data", "zh", "candidate"}

# 两层判定。泛金融词（机构/基金/监管）不够 —— 实测 @IMFNews 讲亚洲增长、
# 欧盟入盟的帖子会因为"机构"命中而漏进来，跟代币化毫无关系。
CORE = re.compile(
    r"RWA|tokeniz|代币化|代币|token|stablecoin|稳定币|onchain|on-?chain|链上|"
    r"blockchain|区块链|DeFi|国债代币|tokenized|数字资产|digital asset|"
    r"custod|托管|结算上链|atomic settle|智能合约|smart contract",
    re.I,
)
# 有核心词的前提下，这些加分项说明是实质内容而非口号
SUBSTANTIVE = re.compile(
    r"securit|证券|SEC\b|FINRA|CLARITY|regulat|监管|rule|规则|"
    r"liquidit|流动性|settle|结算|clearing|清算|collateral|抵押|"
    r"redemption|赎回|yield|收益|custody|AUM|数据|data|research|研究|"
    r"treasur|国债|credit|信贷|fund|基金",
    re.I,
)
# 政治内容一律不赞 —— **点赞是公开的，等于站队**。
# 对一个正在建专业形象的学术账号，这是实打实的风险。
POLITICAL = re.compile(
    r"Trump|特朗普|Biden|拜登|Democrat|Republican|民主党|共和党|"
    r"political|政治立场|election|选举|partisan|administration|"
    r"每一个美国公民|patriot|America First",
    re.I,
)


def candidates(hours: int, min_likes: int) -> list[dict]:
    tier_of = {a["handle"].lower(): a.get("tier", "") for a in load_accounts()}
    liked = set(load_state("liked", {}).get("ids", []))
    now = datetime.now(timezone.utc)

    out = []
    for r in read_raw(hours):
        if r.get("source") != "browser" or r.get("is_retweet"):
            continue
        pid = r.get("id")
        if not pid or pid in liked:
            continue
        h = (r.get("author_handle") or "").lower()
        tier = tier_of.get(h, "")
        if tier not in LIKE_TIERS:
            continue                       # watch 层与名单外账号一律跳过
        text = r.get("text") or ""
        if len(text.strip()) < 25:
            continue
        if POLITICAL.search(text):
            continue                       # 政治内容不赞：点赞公开=站队
        if not CORE.search(text):
            continue                       # 必须有核心词，泛金融词不算
        if not SUBSTANTIVE.search(text):
            continue                       # 还要有实质内容，不赞纯口号
        m = r.get("metrics") or {}
        if (m.get("like") or 0) < min_likes:
            continue                       # 太冷清的帖子赞了没意义
        dt = parse_ts(r.get("created_at"))
        age_h = (now - dt).total_seconds() / 3600 if dt else 999
        r["_tier"] = tier
        r["_age_h"] = age_h
        out.append(r)

    # 新的优先，同龄按互动量
    out.sort(key=lambda x: (x["_age_h"], -(x.get("metrics") or {}).get("like", 0)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="自动点赞")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--max", type=int, default=6, help="本轮最多赞几条")
    ap.add_argument("--min-likes", type=int, default=3, help="原帖至少多少赞才值得赞")
    ap.add_argument("--yes", action="store_true", help="真的点赞（不加只 dry-run）")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()

    settings = load_settings()
    cands = candidates(args.hours, args.min_likes)
    if not cands:
        print("LIKE_OK 0 —— 近期没有值得点赞的新帖")
        return 0

    print(f"{len(cands)} 条候选（已过滤 watch 层与跑题帖），本轮最多赞 {args.max} 条：")
    for r in cands[: args.max]:
        m = r.get("metrics") or {}
        print(f"  @{r['author_handle']:<16} [{r['_tier']:<6}] {int(r['_age_h']):>3}h "
              f"❤{m.get('like') or 0:<5} {(r.get('text') or '')[:58]}")

    if not args.yes:
        print(f"\n[dry-run] 未点赞。{quota_summary(settings)}")
        return 0

    from x_browser import get_playwright_and_context, is_logged_in
    import x_send

    pw, ctx = get_playwright_and_context(headless=not args.headed)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    if not is_logged_in(page):
        ctx.close(); pw.stop()
        raise SystemExit("未登录或会话失效。")

    liked_state = load_state("liked", {"ids": []})
    done = 0
    for r in cands[: args.max]:
        ok, reason = check_safety(settings, "like")
        if not ok:
            print(f"⛔ {reason}")
            break
        ok2, detail = x_send.like_post(page, r["author_handle"], r["id"])
        if ok2:
            record_action("like")
            liked_state["ids"] = (liked_state.get("ids", []) + [r["id"]])[-5000:]
            save_state("liked", liked_state)
            audit("like", {"post_id": r["id"], "author": r["author_handle"],
                           "tier": r["_tier"]})
            done += 1
            print(f"  ❤️ @{r['author_handle']} {r['id']}")
        else:
            print(f"  ⚠️  @{r['author_handle']}: {detail}")
        # 匀速点赞是机器人特征，随机间隔
        if done < args.max:
            time.sleep(random.uniform(20, 70))

    ctx.close(); pw.stop()
    print(f"\nLIKE_OK {done} —— {quota_summary(settings)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(130)
