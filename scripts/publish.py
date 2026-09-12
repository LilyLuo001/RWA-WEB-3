#!/usr/bin/env python3
"""发布推文/回复。

安全模型：
  - 凭据只从 config/credentials.env 读，不接受命令行传入
  - 限速闸门在代码里（common.check_safety），不给"这次特殊"留口子
  - 默认 --dry-run。真正发送必须显式 --yes
  - 所有发送写审计日志 data/audit.jsonl

用法：
  # 发送草稿里的某个选项
  python3 scripts/publish.py --draft 2026-09-11-0920-comment --pick B --yes

  # 直接发一条主帖
  python3 scripts/publish.py --text "..." --yes

  # 只看不发
  python3 scripts/publish.py --draft <id> --pick A
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    DATA, check_safety, load_credentials, load_draft, load_settings,
    quota_summary, record_action,
)

API = "https://api.x.com"
TWEETS_ENDPOINT = f"{API}/2/tweets"
TOKEN_ENDPOINT = f"{API}/2/oauth2/token"


def weighted_len(text: str) -> int:
    """X 加权长度近似：CJK/全角字符计 2，其余计 1，上限 280。"""
    w = 0
    for ch in text:
        cp = ord(ch)
        if (0x1100 <= cp <= 0x115F or 0x2E80 <= cp <= 0x9FFF or 0xA960 <= cp <= 0xA97F
                or 0xAC00 <= cp <= 0xD7FF or 0xF900 <= cp <= 0xFAFF or 0xFE30 <= cp <= 0xFE6F
                or 0xFF00 <= cp <= 0xFF60 or 0xFFE0 <= cp <= 0xFFE6 or 0x20000 <= cp <= 0x3FFFD):
            w += 2
        else:
            w += 1
    return w


def audit(event: str, detail: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **detail}
    with open(DATA / "audit.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def refresh_access_token(creds: dict) -> str:
    """用 refresh_token 换新的 access_token，并把新 token 写回 credentials.env。

    X 的 user-context access token 会过期，无人值守运行必须能自动续期，
    否则每次 cron 都会失败。
    """
    need = ("X_CLIENT_ID", "X_CLIENT_SECRET", "X_REFRESH_TOKEN")
    missing = [k for k in need if not creds.get(k)]
    if missing:
        raise SystemExit(f"credentials.env 缺少刷新所需字段：{', '.join(missing)}")

    basic = base64.b64encode(
        f"{creds['X_CLIENT_ID']}:{creds['X_CLIENT_SECRET']}".encode()
    ).decode()
    r = requests.post(
        TOKEN_ENDPOINT,
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "refresh_token",
            "refresh_token": creds["X_REFRESH_TOKEN"],
            "client_id": creds["X_CLIENT_ID"],
        },
        timeout=30,
    )
    if r.status_code != 200:
        raise SystemExit(f"token 刷新失败 HTTP {r.status_code}: {r.text[:500]}")
    tok = r.json()

    path = Path(__file__).resolve().parent.parent / "config" / "credentials.env"
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    seen = set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.strip().startswith("#") else None
        if key == "X_ACCESS_TOKEN":
            out.append(f"X_ACCESS_TOKEN={tok['access_token']}")
            seen.add(key)
        elif key == "X_REFRESH_TOKEN" and tok.get("refresh_token"):
            # refresh token 可能轮换，必须持久化，否则下次续期失败
            out.append(f"X_REFRESH_TOKEN={tok['refresh_token']}")
            seen.add(key)
        else:
            out.append(line)
    for k in ("X_ACCESS_TOKEN", "X_REFRESH_TOKEN"):
        if k not in seen and (k == "X_ACCESS_TOKEN" or tok.get("refresh_token")):
            out.append(f"{k}={tok.get('refresh_token') if k == 'X_REFRESH_TOKEN' else tok['access_token']}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("↻ access token 已刷新并写回 credentials.env")
    return tok["access_token"]


def post_tweet(access_token: str, text: str, in_reply_to: str | None = None) -> dict:
    body: dict = {"text": text}
    if in_reply_to:
        body["reply"] = {"in_reply_to_tweet_id": str(in_reply_to)}
    r = requests.post(
        TWEETS_ENDPOINT,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=30,
    )
    if r.status_code == 401:
        return {"__retry_after_refresh__": True, "status": 401, "body": r.text[:500]}
    if r.status_code not in (200, 201):
        raise SystemExit(f"发布失败 HTTP {r.status_code}: {r.text[:800]}")
    return r.json()


def resolve_text(args) -> tuple[str, str | None, str | None, str]:
    """返回 (正文, in_reply_to, 作者handle, 描述)。"""
    if args.draft:
        draft = load_draft(args.draft)
        picks = draft.get("drafts") or []
        if not picks:
            raise SystemExit(f"草稿 {args.draft} 里没有 drafts[] 选项")
        if args.pick:
            match = [d for d in picks if str(d.get("label", "")).upper().startswith(args.pick.upper())]
            if not match:
                labels = ", ".join(str(d.get("label")) for d in picks)
                raise SystemExit(f"草稿里没有选项 '{args.pick}'。可选：{labels}")
            chosen = match[0]
        elif len(picks) == 1:
            chosen = picks[0]
        else:
            print("草稿有多个选项，请用 --pick 指定：\n")
            for d in picks:
                print(f"  [{d.get('label')}] {d.get('text')}\n")
            raise SystemExit(2)
        text = chosen["text"]
        reply_to = draft.get("post_id")
        author = draft.get("author")
        desc = f"回复 @{author} · 策略 {chosen.get('label')} · 原帖分数 {draft.get('score')}"
        if not reply_to:
            raise SystemExit("草稿缺少 post_id，无法作为回复发送")
        return text, str(reply_to), author, desc

    if args.text:
        return args.text, args.in_reply_to, args.author, "直接发布"
    raise SystemExit("需要 --draft 或 --text")


def main() -> int:
    ap = argparse.ArgumentParser(description="发布推文/回复（默认 dry-run）")
    ap.add_argument("--draft", help="data/drafts/ 下的草稿 id")
    ap.add_argument("--pick", help="选草稿里的哪个选项，如 A / B / C")
    ap.add_argument("--text", help="直接发布的正文")
    ap.add_argument("--in-reply-to", dest="in_reply_to", help="回复的 tweet id（配合 --text）")
    ap.add_argument("--author", help="回复对象的 handle（浏览器通道回复时必填，配合 --text）")
    ap.add_argument("--yes", action="store_true", help="真正发送。不加则只 dry-run")
    ap.add_argument("--via", choices=["auto", "api", "browser"], default="auto",
                    help="auto = 有 X_ACCESS_TOKEN 走 API，否则走浏览器会话")
    ap.add_argument("--headed", action="store_true", help="浏览器通道使用可见窗口")
    ap.add_argument("--force", action="store_true", help="跳过限速闸门（会在审计日志标记）")
    args = ap.parse_args()

    settings = load_settings()
    text, reply_to, author, desc = resolve_text(args)
    kind = "reply" if reply_to else "post"

    limit = weighted_len(text)
    maxlen = 280
    print(f"\n{desc}")
    print(f"类型：{'回复' if reply_to else '主帖'}   加权字符数：{limit}/{maxlen}")
    if limit > maxlen:
        print(f"❌ 超出 {limit - maxlen}，无法发布。请缩短后重试。")
        return 1
    print(f"\n---\n{text}\n---\n")

    ok, reason = check_safety(settings, kind)
    if not ok:
        if args.force:
            print(f"⚠️  限速闸门未通过（{reason}），但 --force 已指定，继续。")
            audit("safety_override", {"reason": reason, "kind": kind, "text": text[:200]})
        else:
            print(f"⛔ {reason}")
            print("   这是账号保护闸门。冷账号高频互动是最快的限流路径。")
            print("   确有理由绕过时用 --force（会记入审计日志）。")
            return 1

    print(quota_summary(settings))

    # 通道选择
    via = args.via
    token = None
    if via in ("auto", "api"):
        try:
            token = load_credentials().get("X_ACCESS_TOKEN")
        except SystemExit:
            if via == "api":
                raise
        if via == "auto":
            via = "api" if token else "browser"
    print(f"发送通道：{via}")

    if not args.yes:
        print("\n[dry-run] 未发送。确认无误后加 --yes")
        audit("dry_run", {"kind": kind, "via": via, "text": text[:200], "reply_to": reply_to})
        return 0

    # ---------- 浏览器通道 ----------
    if via == "browser":
        import random as _rand
        from x_browser import get_playwright_and_context, is_logged_in
        import x_send
        if reply_to and not author:
            raise SystemExit("浏览器通道回复需要作者 handle 构造 URL："
                             "草稿应包含 author 字段，或用 --author 指定。")
        pw, ctx = get_playwright_and_context(headless=not args.headed)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if not is_logged_in(page):
            ctx.close(); pw.stop()
            raise SystemExit("未登录或会话失效。先运行：python3 scripts/x_browser.py --login")
        page.wait_for_timeout(_rand.randint(1500, 3500))
        if reply_to:
            sent, detail = x_send.send_reply(page, author, reply_to, text)
        else:
            sent, detail = x_send.send_post(page, text)
        ctx.close(); pw.stop()
        if not sent:
            audit("publish_failed", {"via": "browser", "kind": kind, "detail": detail,
                                     "text": text[:200]})
            raise SystemExit(f"❌ 浏览器发送失败：{detail}")
        record_action(kind)
        audit("published", {"kind": kind, "via": "browser", "reply_to": reply_to,
                            "author": author, "text": text})
        print(f"\n✅ 已通过浏览器发送（{detail}）")
        print(f"   {quota_summary(settings)}")
        return 0

    # ---------- API 通道 ----------
    creds = load_credentials()
    token = token or creds.get("X_ACCESS_TOKEN")
    if not token:
        raise SystemExit("credentials.env 里没有 X_ACCESS_TOKEN。先完成 OAuth 授权流程。")

    res = post_tweet(token, text, reply_to)
    if res.get("__retry_after_refresh__"):
        token = refresh_access_token(creds)
        res = post_tweet(token, text, reply_to)
        if res.get("__retry_after_refresh__"):
            audit("publish_failed", {"status": 401, "body": res.get("body")})
            raise SystemExit("刷新 token 后仍然 401。检查 OAuth scope 是否含 tweet.write。")

    tid = (res.get("data") or {}).get("id")
    record_action(kind)
    audit("published", {"tweet_id": tid, "kind": kind, "reply_to": reply_to, "text": text})
    print(f"\n✅ 已发布  id={tid}")
    print(f"   https://x.com/i/web/status/{tid}")
    print(f"   {quota_summary(settings)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(130)
