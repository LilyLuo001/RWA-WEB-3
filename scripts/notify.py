#!/usr/bin/env python3
"""邮件推送（零预算，双通道）。

两条路，凭据都只从 macOS Keychain 读取 —— 永远不出现在文件或 transcript 里：

  resend（推荐，不碰你的 Gmail 安全设置）
    免费层 3000 封/月。发件人显示 onboarding@resend.dev（"随机邮箱"）。
    注册时用 lilysharp88@gmail.com（免费层只能发给自己注册的邮箱，正好）。
    设置：resend.com 注册 → API Keys → Create → 终端运行：
      security add-generic-password -a resend -s rwa-signal-resend-api-key -w

  gmail_app_password（发件人是你自己的 gmail）
    myaccount.google.com/apppasswords 生成 → 终端运行：
      security add-generic-password -a lilysharp88 -s rwa-signal-gmail-app-password -w

用法：
  .venv/bin/python scripts/notify.py --send-file data/digests/2026-09-11.md
  .venv/bin/python scripts/notify.py --test
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
GMAIL_SERVICE = "rwa-signal-gmail-app-password"
RESEND_SERVICE = "rwa-signal-resend-api-key"
ACCOUNT = "lilysharp88"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def load_notify_config() -> dict:
    with open(ROOT / "config" / "notify.yaml", encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    return doc.get("notify") or {}


def keychain(service: str, account: str = "") -> str | None:
    """从 Keychain 读凭据值（-w）。没有则返回 None（不报错，由调用方处理）。"""
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", service]
            + (["-a", account] if account else []),
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0:
            v = out.stdout.strip()
            # 带换行/回车的值是写入 bug，宁可拒用也不带着脏字符发出去
            return v if v and "\n" not in v and "\r" not in v else (v.replace("\n", "").replace("\r", "") or None)
    except Exception:
        pass
    return None


def md_to_html(md: str) -> str:
    """极简 markdown → HTML。只处理晨报实际用到的语法。
    纯文本邮件里 markdown 表格会变成一堆竖线 —— 这是第 1 期排版崩掉的原因。"""
    import html as _html
    import re

    out, in_ul, in_code = [], False, False
    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("```"):
            in_code = not in_code
            out.append("<pre style='background:#f6f8fa;padding:10px;border-radius:6px;"
                       "overflow-x:auto;font-size:13px'>" if in_code else "</pre>")
            continue
        if in_code:
            out.append(_html.escape(line))
            continue

        esc = _html.escape(line)
        # 行内样式：**粗** `码` [文](链接)
        esc = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc)
        esc = re.sub(r"`(.+?)`", r"<code style='background:#f0f2f5;padding:1px 4px;"
                                r"border-radius:3px;font-size:13px'>\1</code>", esc)
        esc = re.sub(r"\[(.+?)\]\((https?://[^\s)]+)\)",
                     r"<a href='\2' style='color:#0969da'>\1</a>", esc)

        if not line.strip():
            if in_ul:
                out.append("</ul>"); in_ul = False
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            if in_ul:
                out.append("</ul>"); in_ul = False
            lvl = len(m.group(1))
            size = {1: 21, 2: 17, 3: 15, 4: 14}[lvl]
            top = 26 if lvl <= 2 else 20
            border = ("border-bottom:1px solid #d8dee4;padding-bottom:6px;" if lvl <= 2 else "")
            body_txt = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", _html.escape(m.group(2)))
            out.append(f"<h{lvl} style='font-size:{size}px;margin:{top}px 0 8px;{border}'>"
                       f"{body_txt}</h{lvl}>")
            continue
        if re.match(r"^---+$", line.strip()):
            if in_ul:
                out.append("</ul>"); in_ul = False
            out.append("<hr style='border:0;border-top:1px solid #e1e4e8;margin:22px 0'>")
            continue
        m = re.match(r"^\s*[-*]\s+(.*)", esc)
        if m:
            if not in_ul:
                out.append("<ul style='margin:8px 0;padding-left:22px'>"); in_ul = True
            out.append(f"<li style='margin:5px 0'>{m.group(1)}</li>")
            continue
        if in_ul:
            out.append("</ul>"); in_ul = False
        out.append(f"<p style='margin:9px 0'>{esc}</p>")
    if in_ul:
        out.append("</ul>")
    if in_code:
        out.append("</pre>")

    return (
        "<div style=\"font-family:-apple-system,'SF Pro Text',Helvetica,Arial,sans-serif;"
        "font-size:15px;line-height:1.62;color:#1f2328;max-width:660px;margin:0 auto;"
        "padding:8px 4px\">" + "\n".join(out) + "</div>"
    )


def send_via_resend(subject: str, body: str, to: str) -> bool:
    key = keychain(RESEND_SERVICE)
    if not key:
        print("⚠️  Keychain 里没有 Resend API key。")
        print("    resend.com 注册（用收件邮箱）→ API Keys → 终端运行：")
        print(f"    security add-generic-password -a resend -s {RESEND_SERVICE} -w")
        return False
    import requests
    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "from": "RWA Signal <onboarding@resend.dev>",
            "to": [to],
            "subject": subject,
            "html": md_to_html(body),
            "text": body,
        },
        timeout=30,
    )
    if r.status_code in (200, 201):
        return True
    print(f"❌ Resend 返回 {r.status_code}: {r.text[:300]}")
    return False


def send_via_gmail(subject: str, body: str, to: str) -> bool:
    pwd = keychain(GMAIL_SERVICE, ACCOUNT)
    if not pwd:
        print("⚠️  Keychain 里没有 Gmail 应用密码。")
        print("    myaccount.google.com/apppasswords → 终端运行：")
        print(f"    security add-generic-password -a {ACCOUNT} -s {GMAIL_SERVICE} -w")
        return False

    import smtplib
    from email.header import Header
    from email.mime.text import MIMEText
    from email.utils import formataddr

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr(("rwa-signal", to))
    msg["To"] = to

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.login(to, pwd)
        s.sendmail(to, [to], msg.as_string())
    return True


def send_email(subject: str, body: str) -> bool:
    cfg = load_notify_config()
    to = cfg.get("to") or "lilysharp88@gmail.com"
    method = cfg.get("method") or "resend"

    if method == "resend":
        return send_via_resend(subject, body, to)
    if method == "gmail_app_password":
        return send_via_gmail(subject, body, to)
    raise SystemExit(f"notify.yaml 里未知的 method: {method}")


def main() -> int:
    ap = argparse.ArgumentParser(description="邮件推送")
    ap.add_argument("--send-file", help="发送这个文件的内容（markdown 直接作为正文）")
    ap.add_argument("--subject", help="邮件主题，默认用文件名")
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args()

    if args.test:
        ok = send_email("rwa-signal 测试邮件", "如果你收到这封邮件，推送通道已打通。")
        print("✅ 已发送" if ok else "❌ 未发送（见上方提示）")
        return 0 if ok else 1

    if args.send_file:
        p = Path(args.send_file)
        if not p.is_absolute():
            p = ROOT / p
        if not p.exists():
            raise SystemExit(f"找不到 {p}")
        subject = args.subject or f"RWA Signal · {p.stem}"
        ok = send_email(subject, p.read_text(encoding="utf-8"))
        if ok:
            print(f"✅ 已发送 {p.name} → {load_notify_config().get('to')}")
        return 0 if ok else 1

    ap.print_help()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(130)
