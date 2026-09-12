#!/usr/bin/env python3
"""名单体检 —— 把"已核验"从一句话变成一个可重跑的检查。

为什么存在：第一版名单是从榜单文章抄的 handle，只验证了"这个字符串出现过"，
结果 15 个账号里 4 个是死号（最久 923 天没发帖）、2 个活跃但完全不讲 RWA。
这个脚本用实际抓到的数据判定，结果写回 accounts.yaml。

判定：
  死号     last_post_days > 30
  跑题     rwa_ratio < 0.30（且样本 >= 5 条）
  低样本   抓到的帖子 < 5 条，不下结论，标 null

用法：
  .venv/bin/python scripts/vet_accounts.py              # 用已有数据体检
  .venv/bin/python scripts/vet_accounts.py --write      # 把结果写回 accounts.yaml
  .venv/bin/python scripts/vet_accounts.py --candidates a b c   # 体检候选新账号
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG, DATA, load_accounts  # noqa: E402
from fetch_posts import parse_ts  # noqa: E402

RWA_KW = re.compile(
    r"RWA|代币化|tokeniz|国债|treasur|T-bill|BUIDL|私募信贷|private credit|"
    r"合规|complian|SEC|证券|securit|机构|institution|on-?chain|链上|"
    r"stablecoin|稳定币|yield|收益|custod|托管|fund|基金",
    re.I,
)

DEAD_DAYS = 30
OFFTOPIC_RATIO = 0.30
MIN_SAMPLE = 5


def load_all_browser_posts() -> dict[str, list[dict]]:
    by_handle: dict[str, list[dict]] = defaultdict(list)
    raw = DATA / "raw"
    if not raw.exists():
        return by_handle
    for p in sorted(raw.glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("source") != "browser":
                continue
            h = r.get("author_handle")
            if h:
                by_handle[h.lower()].append(r)
    return by_handle


def vet_one(posts: list[dict]) -> dict:
    """返回 {last_post_days, rwa_ratio, sample, verdict}"""
    now = datetime.now(timezone.utc)
    dts = [parse_ts(p.get("created_at")) for p in posts]
    dts = [d for d in dts if d]
    own = [p for p in posts if not p.get("is_retweet")]
    sample = len(own)

    last_days = None
    if dts:
        last_days = (now - max(dts)).days

    ratio = None
    if sample >= MIN_SAMPLE:
        hits = sum(1 for p in own if RWA_KW.search(p.get("text") or ""))
        ratio = round(hits / sample, 2)

    if sample == 0:
        verdict = "无数据"
    elif last_days is not None and last_days > DEAD_DAYS:
        verdict = f"❌ 死号（{last_days} 天未发帖）"
    elif ratio is not None and ratio < OFFTOPIC_RATIO:
        verdict = f"⚠️  跑题（RWA 占比 {ratio:.0%}）→ 建议降级 watch"
    elif sample < MIN_SAMPLE:
        verdict = f"… 样本不足（{sample} 条），不下结论"
    else:
        verdict = "✅ 健康"
    return {
        "last_post_days": last_days,
        "rwa_ratio": ratio,
        "sample": sample,
        "verdict": verdict,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="名单体检")
    ap.add_argument("--write", action="store_true", help="把结果写回 accounts.yaml")
    ap.add_argument("--candidates", nargs="*", help="额外体检这些 handle（需先抓过数据）")
    args = ap.parse_args()

    by_handle = load_all_browser_posts()
    accounts = load_accounts()
    names = [a["handle"] for a in accounts] + list(args.candidates or [])

    print(f"{'账号':<20}{'tier':<8}{'样本':>5}{'最新':>7}{'RWA占比':>9}  判定")
    print("-" * 78)
    results: dict[str, dict] = {}
    tier_of = {a["handle"]: a.get("tier", "") for a in accounts}
    problems = []
    for h in names:
        posts = by_handle.get(h.lower(), [])
        v = vet_one(posts)
        results[h] = v
        last = f"{v['last_post_days']}d" if v["last_post_days"] is not None else "—"
        ratio = f"{v['rwa_ratio']:.0%}" if v["rwa_ratio"] is not None else "—"
        print(f"@{h:<19}{tier_of.get(h,'?'):<8}{v['sample']:>5}{last:>7}{ratio:>9}  {v['verdict']}")
        if v["verdict"].startswith(("❌", "⚠️")):
            problems.append((h, v["verdict"]))

    if problems:
        print(f"\n{len(problems)} 个账号需要处理：")
        for h, why in problems:
            print(f"  @{h}: {why}")
    else:
        print("\n全部健康。")

    if args.write:
        path = CONFIG / "accounts.yaml"
        txt = path.read_text(encoding="utf-8")
        today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
        for h, v in results.items():
            if h not in tier_of:
                continue
            # 只更新已存在的字段，保持文件里的注释和顺序不被 yaml.dump 破坏
            blk = re.search(rf'(  - handle: "{re.escape(h)}".*?)(?=\n  - handle:|\n# =|\Z)',
                            txt, re.S)
            if not blk:
                continue
            seg = blk.group(1)
            new = seg
            for key, val in (("last_post_days", v["last_post_days"]),
                             ("rwa_ratio", v["rwa_ratio"]),
                             ("vetted_at", f'"{today}"')):
                sval = "null" if val is None else val
                if re.search(rf"^    {key}:", new, re.M):
                    new = re.sub(rf"^    {key}:.*$", f"    {key}: {sval}", new, flags=re.M)
                else:
                    new = new.rstrip("\n") + f"\n    {key}: {sval}\n"
            txt = txt.replace(seg, new)
        path.write_text(txt, encoding="utf-8")
        print(f"\n已写回 {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
