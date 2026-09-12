#!/usr/bin/env python3
"""复盘统计 —— 晨报第四部分的数据来源。

只报实际发生的事：发了什么、限速状态、审计记录。
拉取已发帖的互动数据需要 API 读取权限；没有权限时明确说没有，
不用估算值填补。

用法：
  python3 scripts/stats.py                 # 昨天 + 今天
  python3 scripts/stats.py --days 7
  python3 scripts/stats.py --audit         # 审计日志明细
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    DATA, current_week_index, daily_reply_cap, load_draft, load_settings,
    load_state, drafts_dir,
)


def read_audit() -> list[dict]:
    p = DATA / "audit.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def day_str(d: datetime) -> str:
    return d.astimezone().strftime("%Y-%m-%d")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=2)
    ap.add_argument("--audit", action="store_true", help="打印审计明细")
    args = ap.parse_args()

    settings = load_settings()
    audit = read_audit()
    quota = load_state("quota", {})
    now = datetime.now(timezone.utc)

    print(f"账号周龄：第 {current_week_index(settings)} 周   "
          f"每日回复上限：{daily_reply_cap(settings)}\n")

    # --- 发送量 ---
    print(f"{'日期':<12}{'回复':>6}{'主帖':>6}{'点赞':>6}{'dry-run':>9}{'绕过限速':>10}")
    ev_by_day: dict[str, Counter] = defaultdict(Counter)
    for e in audit:
        try:
            ts = datetime.fromisoformat(e["ts"])
        except (KeyError, ValueError):
            continue
        ev_by_day[day_str(ts)][e.get("event", "?")] += 1

    for i in range(args.days, -1, -1):
        d = day_str(now - timedelta(days=i))
        q = quota.get(d, {})
        ev = ev_by_day.get(d, Counter())
        print(f"{d:<12}{q.get('replies',0):>6}{q.get('posts',0):>6}"
              f"{q.get('likes',0):>6}{ev.get('dry_run',0):>9}"
              f"{ev.get('safety_override',0):>10}")

    overrides = [e for e in audit if e.get("event") == "safety_override"]
    if overrides:
        print(f"\n⚠️  有 {len(overrides)} 次绕过限速闸门。冷账号阶段这会显著提高限流风险。")
        for e in overrides[-5:]:
            print(f"   {e.get('ts')}  {e.get('reason')}")

    # --- 已发布内容的互动 ---
    published = [e for e in audit if e.get("event") == "published" and e.get("tweet_id")]
    print(f"\n已发布 {len(published)} 条。")
    if published:
        print("互动数据需要通过 API 拉取（GET /2/tweets?id=... public_metrics）。")
        print("当前未实现自动拉取 —— 需要读取配额，等数据源选型确定后接入。")
        print("在此之前，晨报第四部分的互动对比无数据可用，会标注「数据不足」。")
        print("\n最近发布：")
        for e in published[-5:]:
            print(f"   {e.get('ts')}  id={e.get('tweet_id')}  "
                  f"{'回复' if e.get('reply_to') else '主帖'}  {str(e.get('text',''))[:50]}")

    # --- 草稿转化 ---
    drafts = sorted(drafts_dir().glob("*.json"))
    if drafts:
        pub_ids = {str(e.get("draft_id")) for e in audit if e.get("draft_id")}
        converted = sum(1 for p in drafts if p.stem in pub_ids)
        print(f"\n草稿 {len(drafts)} 份，其中 {converted} 份已发布。")
        # 过期草稿：机会窗口已过但没发
        stale = []
        for p in drafts:
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            exp = d.get("expires_at")
            if exp:
                try:
                    if datetime.fromisoformat(exp) < now and p.stem not in pub_ids:
                        stale.append(p.name)
                except ValueError:
                    pass
        if stale:
            print(f"已过期未发布 {len(stale)} 份（机会窗口已过）：{', '.join(stale[:5])}"
                  + ("…" if len(stale) > 5 else ""))
            print("→ 若过期比例高，说明 interval_minutes 太短或额度太紧，考虑调整。")

    if args.audit and audit:
        print(f"\n--- 审计明细（最近 20 条）---")
        for e in audit[-20:]:
            print(json.dumps(e, ensure_ascii=False)[:200])

    return 0


if __name__ == "__main__":
    sys.exit(main())
