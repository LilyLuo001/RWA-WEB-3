#!/usr/bin/env python3
"""L1 取数层 —— 把帖子规范化后落到 data/raw/YYYY-MM-DD.jsonl

数据源可插拔，因为选型还没定（等 X API 档位核实结果）：
  --source xapi      走官方 API（需在 credentials.env 配好，且档位支持读取）
  --source manual    从文件导入（现在就能用，不依赖任何 API）

规范化 schema 是稳定的，换数据源不影响 L2/L3/L4。

用法：
  python3 scripts/fetch_posts.py --source manual --from-json exports/today.json
  python3 scripts/fetch_posts.py --source xapi --lookback-minutes 30
  python3 scripts/fetch_posts.py --stats
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    DATA, ROOT, load_accounts, load_credentials, load_settings,
    load_state, save_state,
)

RAW = DATA / "raw"

# X API v2 请求字段。这些是稳定的；变的是各档位允许的调用频率，
# 那部分从 config 读，不硬编码。
TWEET_FIELDS = ",".join([
    "created_at", "author_id", "conversation_id", "in_reply_to_user_id",
    "referenced_tweets", "public_metrics", "lang", "source",
    "possibly_sensitive", "entities",
])
EXPANSIONS = "author_id,referenced_tweets.id,referenced_tweets.id.author_id"
USER_FIELDS = "username,name,public_metrics,verified"


# ---------- 规范化 ----------

def canonical(
    raw: dict,
    users: dict[str, dict] | None = None,
    tier_by_author_id: dict[str, str] | None = None,
    source: str = "xapi",
) -> dict:
    """X API v2 tweet 对象 → 内部规范记录。

    `quoted_post_id` 单独保留：晨报要区分「回声」和「收敛」，
    靠的就是追溯这些帖子是否指向同一个源头。
    """
    users = users or {}
    tier_by_author_id = tier_by_author_id or {}
    m = raw.get("public_metrics") or {}
    author_id = str(raw.get("author_id") or "")
    u = users.get(author_id, {})

    quoted = None
    is_retweet = is_reply = False
    in_reply_to = None
    for ref in raw.get("referenced_tweets") or []:
        t = ref.get("type")
        if t == "quoted":
            quoted = str(ref.get("id"))
        elif t == "retweeted":
            is_retweet = True
        elif t == "replied_to":
            is_reply = True
            in_reply_to = str(ref.get("id"))

    ents = raw.get("entities") or {}
    urls = [x.get("expanded_url") or x.get("url") for x in ents.get("urls") or []]
    mentions = [x.get("username") for x in ents.get("mentions") or []]

    created = raw.get("created_at")
    created_dt = None
    if created:
        try:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            pass

    return {
        "id": str(raw.get("id")),
        "author_id": author_id,
        "author_handle": u.get("username"),
        "author_name": u.get("name"),
        "author_followers": (u.get("public_metrics") or {}).get("followers_count"),
        "tier": tier_by_author_id.get(author_id),
        "created_at": created_dt.isoformat() if created_dt else None,
        "text": raw.get("text") or raw.get("full_text") or "",
        "lang": raw.get("lang"),
        "metrics": {
            "like": m.get("like_count"),
            "retweet": m.get("retweet_count"),
            "reply": m.get("reply_count"),
            "quote": m.get("quote_count"),
            "impression": m.get("impression_count"),
        },
        "is_retweet": is_retweet,
        "is_reply": is_reply,
        "in_reply_to": in_reply_to,
        "quoted_post_id": quoted,
        "conversation_id": raw.get("conversation_id"),
        "urls": [u_ for u_ in urls if u_],
        "mentions": [x for x in mentions if x],
        "source": source,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def canonical_from_any(obj: dict, source: str = "manual") -> dict:
    """接受已经是规范格式的记录，或 X API v2 单条 tweet 对象。"""
    if "fetched_at" in obj and "metrics" in obj:
        obj.setdefault("source", source)
        return obj
    return canonical(obj, source=source)


# ---------- 存储与去重 ----------

def append_raw(records: list[dict]) -> tuple[int, int]:
    """写入按天分片的 jsonl。返回 (新写入数, 跳过重复数)。"""
    RAW.mkdir(parents=True, exist_ok=True)
    seen = set(load_state("seen_posts", {}).get("ids", []))
    new = dup = 0
    buckets: dict[str, list[dict]] = {}
    for r in records:
        pid = r.get("id")
        if not pid:
            continue
        if pid in seen:
            dup += 1
            continue
        seen.add(pid)
        day = (r.get("created_at") or r.get("fetched_at") or "")[:10] or "unknown"
        buckets.setdefault(day, []).append(r)
        new += 1

    for day, rows in buckets.items():
        with open(RAW / f"{day}.jsonl", "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 只保留最近 14 天的 id，状态文件不会无限增长
    ids = sorted(seen)[-20000:]
    save_state("seen_posts", {
        "ids": ids,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    return new, dup


def parse_ts(ts: str) -> datetime | None:
    """兼容 'Z' 后缀（浏览器抓取）与 '+00:00'（API）。Python 3.10 的
    fromisoformat 不认 'Z'，必须先替换 —— 之前这导致 browser 记录被静默丢弃。"""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def read_raw(hours: int) -> list[dict]:
    """读取最近 N 小时的记录。按 created_at 过滤，缺失则用 fetched_at。"""
    if not RAW.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    # 注意：文件按 created_at 日期分片，不止最近 10 天的窗口也要能读到
    files = sorted(RAW.glob("*.jsonl"))
    if not files:
        return []
    # 只读窗口可能覆盖的日期文件（含 fetched_at 兜底，往前多留 2 天）
    earliest_day = (datetime.now(timezone.utc) - timedelta(hours=hours + 48)).strftime("%Y-%m-%d")
    files = [p for p in files if p.stem >= earliest_day]
    for p in files:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = r.get("created_at") or r.get("fetched_at")
            dt = parse_ts(ts) if ts else None
            if dt and dt >= cutoff:
                out.append(r)
    return out


# ---------- 数据源 ----------

def fetch_manual(path_str: str, as_jsonl: bool) -> list[dict]:
    p = Path(path_str)
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}")
    txt = p.read_text(encoding="utf-8")

    objs: list[dict] = []
    users: dict[str, dict] = {}

    if as_jsonl:
        for line in txt.splitlines():
            line = line.strip()
            if line:
                objs.append(json.loads(line))
        return [canonical_from_any(o) for o in objs]

    doc = json.loads(txt)
    # 支持 X API v2 的响应形状：{data:[...], includes:{users:[...]}}
    # 也支持单个响应数组、或裸 tweet 数组
    payloads = doc if isinstance(doc, list) else [doc]
    out = []
    for pl in payloads:
        if isinstance(pl, dict) and "data" in pl:
            for u in ((pl.get("includes") or {}).get("users") or []):
                users[str(u.get("id"))] = u
            for t in pl["data"] or []:
                out.append(canonical(t, users))
        elif isinstance(pl, dict) and "id" in pl:
            out.append(canonical(pl, users))
        elif isinstance(pl, dict):
            out.append(canonical_from_any(pl))
    return out


def fetch_xapi(lookback_minutes: int) -> list[dict]:
    """走官方 X API 拉取名单账号的时间线。

    ⚠️ 未验证：各档位是否允许读取他人时间线、以及每月读取配额，
    取决于 API 调研结果。填好 config/api_limits.yaml 后再启用。
    """
    try:
        import requests  # noqa: F401
    except ImportError:
        raise SystemExit("需要 requests：pip3 install requests")

    accounts = load_accounts()
    if not accounts:
        raise SystemExit("config/accounts.yaml 名单为空，先填充名单。")

    creds = load_credentials()
    token = creds.get("X_BEARER_TOKEN") or creds.get("X_ACCESS_TOKEN")
    if not token:
        raise SystemExit("credentials.env 里没有可用的读取 token（X_BEARER_TOKEN / X_ACCESS_TOKEN）。")

    limits_path = ROOT / "config" / "api_limits.yaml"
    if not limits_path.exists():
        raise SystemExit(
            "缺少 config/api_limits.yaml。\n"
            "这个文件记录你所在档位实际允许的调用量，用于在撞上配额前自动停手。\n"
            "等 API 档位调研结果出来后我会生成它 —— 在此之前请用 --source manual。"
        )

    raise SystemExit(
        "xapi 数据源尚未启用：需要先根据 API 调研结果确定\n"
        "  (1) 你的档位能否读他人时间线  (2) 每月/每15分钟读取配额\n"
        "然后生成 config/api_limits.yaml 并在此实现分页与配额保护。\n"
        "现在请用 --source manual，或等调研结果。"
    )


# ---------- 统计 ----------

def print_stats() -> None:
    settings = load_settings()
    print(f"{'窗口':<10}{'帖子数':>8}{'账号数':>8}{'中位互动':>10}")
    for h in (6, 24, 72, 168):
        rows = read_raw(h)
        authors = {r.get("author_handle") for r in rows if r.get("author_handle")}
        engs = sorted(
            (r.get("metrics") or {}).get("like") or 0
            for r in rows
        )
        med = engs[len(engs) // 2] if engs else 0
        print(f"{h}h{'':<7}{len(rows):>8}{len(authors):>8}{med:>10}")

    files = sorted(RAW.glob("*.jsonl")) if RAW.exists() else []
    if files:
        print(f"\n最早分片：{files[0].name}   最新分片：{files[-1].name}")
        print(f"已见帖子 id：{len(load_state('seen_posts', {}).get('ids', []))}")
    else:
        print("\ndata/raw/ 为空 —— 还没有取到任何数据。")
    names = [a.get("handle") for a in load_accounts()]
    print(f"监听名单：{len(names)} 个账号" + (f"（{', '.join(names[:8])}{'…' if len(names) > 8 else ''}）" if names else "（未填充）"))


def main() -> int:
    ap = argparse.ArgumentParser(description="L1 取数")
    ap.add_argument("--source", choices=["xapi", "manual"], default="manual")
    ap.add_argument("--from-json", dest="from_json", help="JSON 文件（X API v2 响应 / 数组 / 规范记录）")
    ap.add_argument("--from-jsonl", dest="from_jsonl", help="JSONL 文件（每行一条规范记录）")
    ap.add_argument("--lookback-minutes", type=int, default=30)
    ap.add_argument("--stats", action="store_true", help="只看库存统计，不取数")
    ap.add_argument("--dry-run", action="store_true", help="解析但不写入")
    args = ap.parse_args()

    if args.stats:
        print_stats()
        return 0

    if args.source == "manual":
        src = args.from_jsonl or args.from_json
        if not src:
            raise SystemExit("--source manual 需要 --from-json 或 --from-jsonl")
        records = fetch_manual(src, as_jsonl=bool(args.from_jsonl))
    else:
        records = fetch_xapi(args.lookback_minutes)

    if not records:
        print("解析到 0 条记录。检查文件格式。")
        return 0

    bad = [r for r in records if not r.get("id")]
    if bad:
        print(f"⚠️  {len(bad)} 条缺少 id，已跳过")
        records = [r for r in records if r.get("id")]

    if args.dry_run:
        print(f"[dry-run] 解析到 {len(records)} 条，未写入。样例：")
        for r in records[:3]:
            print(f"  {r.get('id')} @{r.get('author_handle')} "
                  f"likes={(r.get('metrics') or {}).get('like')} "
                  f"quoted={r.get('quoted_post_id')} :: {r.get('text','')[:60]}")
        return 0

    new, dup = append_raw(records)
    print(f"✅ 新写入 {new} 条，跳过重复 {dup} 条 → {RAW}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
