"""共享工具：配置、凭据、状态。

凭据只从 config/credentials.env 读取。绝不接受从命令行或环境变量传入，
避免密钥落进 shell history 或对话 transcript。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"
STATE = ROOT / "state"


def load_settings() -> dict:
    with open(CONFIG / "settings.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_accounts() -> list[dict]:
    with open(CONFIG / "accounts.yaml", encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    return doc.get("accounts") or []


def load_credentials() -> dict:
    """读取 credentials.env。文件不存在时给出可操作的提示而非 traceback。"""
    path = CONFIG / "credentials.env"
    if not path.exists():
        raise SystemExit(
            f"缺少 {path}\n"
            f"  cp {CONFIG/'credentials.env.example'} {path}\n"
            f"  编辑后 chmod 600 {path}"
        )
    mode = oct(path.stat().st_mode & 0o777)
    if mode not in ("0o600", "0o400"):
        print(f"⚠️  {path} 权限是 {mode}，建议 chmod 600")
    creds: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        creds[k.strip()] = v.strip()
    return creds


# ---------- 状态 ----------

def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # 状态文件损坏不应该阻塞发布；备份后重建
        path.rename(path.with_suffix(".corrupt"))
        print(f"⚠️  {path.name} 损坏，已备份为 .corrupt 并重建")
        return default


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_state(name: str, default):
    return _read_json(STATE / f"{name}.json", default)


def save_state(name: str, obj) -> None:
    _write_json(STATE / f"{name}.json", obj)


def today() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


# ---------- 安全限速 ----------

def current_week_index(settings: dict) -> int:
    """账号周龄 = 配置里的起始周龄 + 系统启动后经过的整周数。"""
    base = int(settings.get("safety", {}).get("account_age_weeks", 0) or 0)
    started = load_state("started_at", None)
    if started is None:
        save_state("started_at", datetime.now(timezone.utc).isoformat())
        return base
    try:
        t0 = datetime.fromisoformat(started)
    except ValueError:
        return base
    elapsed = datetime.now(timezone.utc) - t0
    return base + max(0, elapsed.days // 7)


def daily_reply_cap(settings: dict) -> int:
    wk = current_week_index(settings)
    ramp = settings.get("safety", {}).get("ramp_schedule", {}) or {}
    if wk <= 1:
        return int(ramp.get("week_1", 3))
    if wk == 2:
        return int(ramp.get("week_2", 5))
    if wk == 3:
        return int(ramp.get("week_3", 8))
    return int(ramp.get("week_4_plus", 12))


def check_safety(settings: dict, kind: str = "reply") -> tuple[bool, str]:
    """发布前的硬性闸门。返回 (是否放行, 原因)。

    这一层在代码里而非 prompt 里，是故意的：
    冷账号的限速一旦靠"判断"来放宽，就一定会被放宽。
    """
    safety = settings.get("safety", {})
    q = load_state("quota", {})
    d = today()
    day = q.setdefault(d, {"replies": 0, "likes": 0, "posts": 0, "timestamps": []})

    if kind == "reply":
        cap = daily_reply_cap(settings)
        if day["replies"] >= cap:
            return False, f"今日回复已达上限 {day['replies']}/{cap}（第 {current_week_index(settings)} 周）"
        gap = int(safety.get("min_gap_minutes", 25))
        if day["timestamps"]:
            last = datetime.fromisoformat(day["timestamps"][-1])
            wait = gap - (datetime.now(timezone.utc) - last).total_seconds() / 60
            if wait > 0:
                return False, f"距上次回复不足 {gap} 分钟，还需等 {int(wait)+1} 分钟"
    elif kind == "like":
        cap = int(safety.get("max_likes_per_day", 30))
        if day["likes"] >= cap:
            return False, f"今日点赞已达上限 {day['likes']}/{cap}"
    return True, "ok"


def record_action(kind: str) -> None:
    """只在真正发布成功后调用。"""
    q = load_state("quota", {})
    d = today()
    day = q.setdefault(d, {"replies": 0, "likes": 0, "posts": 0, "timestamps": []})
    key = {"reply": "replies", "like": "likes", "post": "posts"}.get(kind, "posts")
    day[key] += 1
    if kind == "reply":
        day["timestamps"].append(datetime.now(timezone.utc).isoformat())
    # 只保留最近 30 天
    cutoff = (datetime.now(timezone.utc).astimezone() - timedelta(days=30)).strftime("%Y-%m-%d")
    for k in [k for k in q if k < cutoff]:
        del q[k]
    save_state("quota", q)


def quota_summary(settings: dict) -> str:
    q = load_state("quota", {})
    day = q.get(today(), {})
    cap = daily_reply_cap(settings)
    return f"今日回复 {day.get('replies', 0)}/{cap} · 点赞 {day.get('likes', 0)}/{settings.get('safety', {}).get('max_likes_per_day', 30)}"


def drafts_dir() -> Path:
    p = DATA / "drafts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_draft(draft_id: str) -> dict:
    """draft_id 可以是完整文件名，也可以是 YYYY-MM-DD-HHMM-comment 形式。"""
    d = drafts_dir()
    for cand in (f"{draft_id}.json", draft_id):
        p = d / cand
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    matches = sorted(d.glob(f"*{draft_id}*.json"))
    if len(matches) == 1:
        return json.loads(matches[0].read_text(encoding="utf-8"))
    if len(matches) > 1:
        raise SystemExit(f"'{draft_id}' 匹配到多个草稿：\n" + "\n".join(f"  {m.name}" for m in matches))
    raise SystemExit(f"找不到草稿 '{draft_id}'。现有草稿：\n" + ("\n".join(f"  {p.name}" for p in sorted(d.glob('*.json'))) or "  （无）"))
