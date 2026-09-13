#!/usr/bin/env python3
"""自动发现新账号 —— 补上管道里唯一还靠人工的环节。

为什么存在：`follow_list.py` 只关注 accounts.yaml 里已有的账号，
名单关完就空转（实测连续两天输出"全部已关注，无操作"）。
所以"每 2 小时新增关注"实际从未发生 —— 缺的不是关注频率，是**发现机制**。

方法：从已抓帖子里做 @提及 频次分析。
圈内真实在对话的人出现在别人的推文里，不出现在榜单文章里。
（第一版名单抄自榜单，15 个里 4 个是死号，最久的 923 天没发帖。）

流程：挖掘 → 加为候选 → 抓取 → 体检 → 通过则关注，未过则记入黑名单不再重查

用法：
  .venv/bin/python scripts/discover_accounts.py                 # 只看挖到了谁
  .venv/bin/python scripts/discover_accounts.py --run --max 3   # 完整跑一轮
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG, DATA, ROOT, load_accounts, load_state, save_state  # noqa: E402

VENV_PY = str(ROOT / ".venv" / "bin" / "python")

# 提及来自不同 tier 的账号，信息量不同：
# 监管/学术/真人 KOL 提到的，比营销号提到的更可能是真人物。
TIER_WEIGHT = {
    "reg": 3.0, "acad": 3.0, "kol": 2.5,
    "data": 1.5, "inst": 1.5, "issuer": 1.0,
    "zh": 1.0, "watch": 0.4, "candidate": 1.0,
}

# 不是个人账号 / 已知无价值的提及。挖掘时直接跳过。
NOISE = {
    # 通用平台与协议
    "rwa", "base", "monad", "arc", "avax", "aave", "uniswap", "coinbase",
    "symbioticfi", "layerzero_core", "solana", "ethereum", "binance",
    # 机构但非内容源
    "nyse", "fda", "whitehouse", "cnbc", "bloomberg", "forbes", "reuters",
    "dukefuqua", "columbia", "ra_insights", "cfainstitute", "iscopress",
    "ioscopress", "rbi", "kansascityfed", "gfffintechfest", "fintechtvglobal",
    "broadridge", "dtcc", "finra", "sec", "imf", "bis",
    # 政治人物（与 niche 无关）
    "realdonaldtrump", "pmarca", "chairmanselig",
}

HANDLE_RE = re.compile(r"@(\w{3,15})")

# 相关性闸门：只统计出现在**主题相关推文**里的提及。
# 没有这道闸门，@IMFNews 这类什么都发的账号会把名单灌满欧盟入盟论文、
# 非洲 AI、泰国央行之类的无关提及 —— 而且因为 acad 权重高(3.0)，排名还很靠前。
RELEVANT_RE = re.compile(
    r"RWA|tokeniz|代币化|token|stablecoin|稳定币|treasur|国债|"
    r"onchain|on-chain|链上|blockchain|区块链|DeFi|custod|托管|"
    r"settle|结算|securit|证券|SEC\b|CLARITY|clearing|清算|"
    r"liquidit|流动性|collateral|抵押|redemption|赎回|yield|收益",
    re.I,
)


def load_browser_posts(days: int = 7) -> list[dict]:
    out = []
    raw = DATA / "raw"
    if not raw.exists():
        return out
    for p in sorted(raw.glob("*.jsonl"))[-days - 3:]:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("source") == "browser":
                out.append(r)
    return out


def mine(posts: list[dict], known: set[str], rejected: set[str]) -> list[tuple]:
    """返回 [(handle, 加权分, 原始次数, 谁提的, 上下文), ...]，按分数降序。"""
    tier_of = {a["handle"].lower(): a.get("tier", "") for a in load_accounts()}
    score: Counter = Counter()
    raw_count: Counter = Counter()
    ctx: dict[str, tuple] = {}

    for r in posts:
        text = r.get("text") or ""
        if not RELEVANT_RE.search(text):
            continue  # 无关推文里的提及不算
        src = (r.get("author_handle") or "").lower()
        w = TIER_WEIGHT.get(tier_of.get(src, ""), 1.0)
        for m in HANDLE_RE.findall(text):
            ml = m.lower()
            if ml in known or ml in rejected or ml in NOISE:
                continue
            if ml == src:
                continue
            score[m] += w
            raw_count[m] += 1
            ctx.setdefault(m, (r.get("author_handle"),
                               text[:110].replace("\n", " ")))

    rows = []
    for h, s in score.most_common():
        who, snippet = ctx[h]
        rows.append((h, round(s, 1), raw_count[h], who, snippet))
    return rows


def add_candidates(cands: list[tuple]) -> None:
    """写进 accounts.yaml 的 candidate 区。保留注释，不用 yaml.dump。"""
    path = CONFIG / "accounts.yaml"
    t = path.read_text(encoding="utf-8")
    backup = t
    block = "\n  # ---------- 自动发现（discover_accounts.py）----------\n"
    for h, s, n, who, snippet in cands:
        safe = snippet.replace('"', "'")[:90]
        block += (f'  - handle: "{h}"\n'
                  f'    name: "{h}"\n'
                  f'    tier: "candidate"\n'
                  f'    covers: "自动发现，待体检。被 @{who} 提及 {n} 次"\n'
                  f'    source: "@提及挖掘：「{safe}」"\n')
    # 必须插在 accounts 列表**末尾**。用 find 会命中文件头部的注释块，
    # 插错位置会直接把 yaml 弄坏（实测：抓取报 ParserError，
    # 后续体检拿不到结果，候选被全部误判拉黑）。
    marker = "\n# ============================================================"
    idx = t.rfind(marker)          # ← rfind，不是 find
    if idx <= 0:
        idx = len(t.rstrip()) 
        t = t.rstrip() + "\n" + block
    else:
        t = t[:idx] + block + t[idx:]
    path.write_text(t, encoding="utf-8")

    # 写完立刻验证能否解析，坏了就回滚 —— 不要把损坏的配置留给下游
    import yaml as _yaml
    try:
        _yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        path.write_text(backup, encoding="utf-8")
        raise SystemExit(f"写入后 yaml 解析失败，已回滚：{e}")


def remove_from_yaml(handles: list[str]) -> None:
    path = CONFIG / "accounts.yaml"
    t = path.read_text(encoding="utf-8")
    for h in handles:
        t = re.sub(rf'  - handle: "{re.escape(h)}".*?(?=\n  - handle:|\n\n  #|\n# =)',
                   "", t, flags=re.S)
    path.write_text(t, encoding="utf-8")


def sh(args: list[str]) -> tuple[int, str]:
    r = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True, timeout=900)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser(description="自动发现新账号")
    ap.add_argument("--run", action="store_true", help="执行完整流程（默认只挖不动）")
    ap.add_argument("--max", type=int, default=3, help="本轮最多处理几个候选")
    ap.add_argument("--daily-cap", type=int, default=12, help="每日新增关注上限（冷号保护）")
    args = ap.parse_args()

    accounts = load_accounts()
    known = {a["handle"].lower() for a in accounts}
    rejected = {k.lower() for k in load_state("rejected", {})}
    followed = load_state("followed", {})

    posts = load_browser_posts()
    rows = mine(posts, known, rejected)

    print(f"数据池 {len(posts)} 帖 · 名单 {len(accounts)} 个 · 黑名单 {len(rejected)} 个")
    if not rows:
        print("没有挖到新候选（可能名单已覆盖圈内主要对话者）。")
        return 0

    print(f"\n挖到 {len(rows)} 个候选（分数 = 提及次数 × 提及者 tier 权重）：")
    for h, s, n, who, snip in rows[:12]:
        print(f"  {s:>5}分 ({n}次)  @{h:<18} ←@{who}")
        print(f"          「{snip[:88]}」")

    if not args.run:
        print("\n[只看模式] 加 --run 执行：加候选 → 抓取 → 体检 → 关注/拉黑")
        return 0

    # 冷号保护：当日新增关注总量封顶
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    today_follows = sum(1 for v in followed.values()
                        if isinstance(v, dict) and str(v.get("at", ""))[:10] == today)
    room = max(0, args.daily_cap - today_follows)
    if room == 0:
        print(f"\n今日新增关注已达上限 {args.daily_cap}，本轮只挖不关注。")
        return 0

    batch = rows[: min(args.max, room)]
    handles = [h for h, *_ in batch]
    print(f"\n本轮处理 {len(batch)} 个：{', '.join('@'+h for h in handles)}")
    print(f"（今日已关注 {today_follows}/{args.daily_cap}）")

    add_candidates(batch)
    print("→ 已加入 accounts.yaml 候选区")

    code, out = sh([VENV_PY, "scripts/fetch_browser.py",
                    "--accounts", *handles, "--per-account", "12"])
    print("→ 抓取完成" if code == 0 else f"→ 抓取异常: {out[-300:]}")

    code, out = sh([VENV_PY, "scripts/vet_accounts.py", "--write"])
    verdicts = {}
    for line in out.splitlines():
        for h in handles:
            if f"@{h} " in line or line.startswith(f"@{h}"):
                verdicts[h] = "pass" if "✅" in line else "fail"
    print("→ 体检结果：" + ", ".join(f"@{h}={v}" for h, v in verdicts.items()))

    passed = [h for h in handles if verdicts.get(h) == "pass"]
    failed = [h for h in handles if verdicts.get(h) != "pass"]

    if failed:
        rej = load_state("rejected", {})
        for h in failed:
            rej[h] = {"at": today, "why": "体检未过（死号或跑题）"}
        save_state("rejected", rej)
        remove_from_yaml(failed)
        print(f"→ {len(failed)} 个未过体检，已移出名单并拉黑不再重查：{failed}")

    if passed:
        code, out = sh([VENV_PY, "scripts/follow_list.py", "--max", str(len(passed))])
        print("→ 关注：" + "\n".join("  " + l for l in out.splitlines()[-4:]))
    else:
        print("→ 本轮无通过体检的账号，不关注。")

    print(f"\n完成。通过 {len(passed)} 个，拉黑 {len(failed)} 个。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
