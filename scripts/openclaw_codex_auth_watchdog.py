#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


KST = timezone(timedelta(hours=9))
ROOT = Path("/Users/tttksj/first_repo")
OPENCLAW_DIR = Path("/Users/tttksj/.openclaw")
CODEX_AUTH_PATH = Path("/Users/tttksj/.codex/auth.json")
AUTH_STORE_PATH = OPENCLAW_DIR / "agents" / "main" / "agent" / "auth-profiles.json"
OPENCLAW_CONFIG_PATH = OPENCLAW_DIR / "openclaw.json"
GATEWAY_ERR_LOG_PATH = OPENCLAW_DIR / "logs" / "gateway.err.log"
STATE_PATH = OPENCLAW_DIR / "memory" / "codex-auth-watchdog-state.json"
OPENCLAW_BIN = "/Users/tttksj/.npm-global/bin/openclaw"
REMOTE_LOGIN_SCRIPT = "/Users/tttksj/first_repo/scripts/openclaw_codex_remote_login.py"
PROFILE_DEFAULT = "openai-codex:default"
PROFILE_CODEX_CLI = "openai-codex:codex-cli"
OLLAMA_FALLBACK_MODEL = "ollama/qwen2.5-coder:7b"
LOOKBACK_MINUTES = 20


@dataclass
class WatchdogResult:
    synced: bool = False
    restarted_gateway: bool = False
    auth_order_fixed: bool = False
    fallback_added: bool = False
    login_link_started: bool = False
    sent_notice: bool = False
    status: str = "ok"
    detail: str = ""


def _load_state() -> dict[str, Any]:
    value = _load_json(STATE_PATH, {})
    return value if isinstance(value, dict) else {}


def _save_state(updates: dict[str, Any]) -> dict[str, Any]:
    state = _load_state()
    state.update(updates)
    _atomic_write_json(STATE_PATH, state)
    return state


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload.encode("utf-8"))
        value = json.loads(raw.decode("utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _build_profile_from_codex_auth(codex_auth: dict[str, Any]) -> dict[str, Any] | None:
    tokens = dict(codex_auth.get("tokens", {}) or {})
    access = str(tokens.get("access_token", "") or "").strip()
    refresh = str(tokens.get("refresh_token", "") or "").strip()
    if not access or not refresh:
        return None
    payload = _decode_jwt_payload(access)
    profile_data = dict(payload.get("https://api.openai.com/profile", {}) or {})
    email = str(profile_data.get("email", "") or "").strip() or None
    account_id = str(tokens.get("account_id", "") or "").strip() or None
    expires = payload.get("exp")
    try:
        expires_ms = int(float(expires) * 1000)
    except Exception:
        expires_ms = int(datetime.now(timezone.utc).timestamp() * 1000) + 3600 * 1000
    profile = {
        "type": "oauth",
        "provider": "openai-codex",
        "access": access,
        "refresh": refresh,
        "expires": expires_ms,
        "email": email,
        "accountId": account_id,
    }
    return {k: v for k, v in profile.items() if v is not None}


def sync_auth_profiles() -> tuple[bool, dict[str, Any] | None]:
    codex_auth = _load_json(CODEX_AUTH_PATH, {})
    profile = _build_profile_from_codex_auth(codex_auth)
    if profile is None:
        return False, None
    store = _load_json(AUTH_STORE_PATH, {"version": 1, "profiles": {}, "usageStats": {}})
    if not isinstance(store, dict):
        store = {"version": 1, "profiles": {}, "usageStats": {}}
    profiles = dict(store.get("profiles", {}) or {})
    changed = False
    for profile_id in (PROFILE_DEFAULT, PROFILE_CODEX_CLI):
        if profiles.get(profile_id) != profile:
            profiles[profile_id] = profile
            changed = True
    if changed:
        store["version"] = 1
        store["profiles"] = profiles
        store.setdefault("usageStats", {})
        _atomic_write_json(AUTH_STORE_PATH, store)
    return changed, profile


def ensure_auth_order() -> bool:
    proc = subprocess.run(
        [
            OPENCLAW_BIN,
            "models",
            "auth",
            "order",
            "get",
            "--agent",
            "main",
            "--provider",
            "openai-codex",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    current = (proc.stdout or "") + (proc.stderr or "")
    wanted = [PROFILE_CODEX_CLI, PROFILE_DEFAULT]
    if all(profile_id in current for profile_id in wanted):
        return False
    subprocess.run(
        [
            OPENCLAW_BIN,
            "models",
            "auth",
            "order",
            "set",
            "--agent",
            "main",
            "--provider",
            "openai-codex",
            *wanted,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return True


def _parse_log_time(raw: str) -> datetime | None:
    prefix = raw.split(" ", 1)[0].strip()
    try:
        return datetime.fromisoformat(prefix)
    except Exception:
        return None


def recent_gateway_errors() -> list[str]:
    if not GATEWAY_ERR_LOG_PATH.exists():
        return []
    now = datetime.now(KST)
    threshold = now - timedelta(minutes=LOOKBACK_MINUTES)
    selected: list[str] = []
    for raw in GATEWAY_ERR_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]:
        timestamp = _parse_log_time(raw)
        if timestamp is not None and timestamp < threshold:
            continue
        selected.append(raw)
    return selected


def latest_auth_error_key(lines: list[str]) -> str | None:
    patterns = (
        "OAuth token refresh failed for openai-codex",
        "refresh_token_reused",
        "Token refresh failed: 401",
    )
    for line in reversed(lines):
        if any(pattern in line for pattern in patterns):
            return line.strip()
    return None


def restart_gateway() -> bool:
    proc = subprocess.run(
        [OPENCLAW_BIN, "gateway", "restart"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc.returncode == 0


def ensure_local_fallback() -> bool:
    if shutil.which("ollama") is None:
        return False
    list_proc = subprocess.run(
        ["ollama", "list"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if "qwen2.5-coder:7b" not in (list_proc.stdout or ""):
        return False
    current_proc = subprocess.run(
        [OPENCLAW_BIN, "models", "fallbacks", "list"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    current = (current_proc.stdout or "") + (current_proc.stderr or "")
    if OLLAMA_FALLBACK_MODEL in current:
        return False
    add_proc = subprocess.run(
        [OPENCLAW_BIN, "models", "fallbacks", "add", OLLAMA_FALLBACK_MODEL],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return add_proc.returncode == 0


def ensure_remote_login_flow() -> bool:
    if os.environ.get("OPENCLAW_ALLOW_AUTO_OAUTH", "0").strip().lower() not in {"1", "true", "yes", "on"}:
        return False
    state = _load_state()
    last = str(state.get("last_remote_login_started_at", "") or "")
    if last:
        try:
            if datetime.now(KST) - datetime.fromisoformat(last) < timedelta(minutes=30):
                return False
        except Exception:
            pass
    proc = subprocess.run(
        ["/usr/bin/python3", REMOTE_LOGIN_SCRIPT],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    started = '"status": "started"' in output or '"status":"started"' in output or "already_running" in output
    if started:
        _save_state({"last_remote_login_started_at": datetime.now(KST).isoformat()})
    return started


def _load_telegram_config() -> tuple[str, str] | tuple[None, None]:
    config = _load_json(OPENCLAW_CONFIG_PATH, {})
    telegram = dict(dict(config.get("channels", {}) or {}).get("telegram", {}) or {})
    token = str(telegram.get("botToken", "") or "").strip()
    allow_from = telegram.get("allowFrom") or []
    chat_id = str(allow_from[0]).strip() if allow_from else ""
    return (token or None, chat_id or None)


def _send_telegram_message(text: str) -> bool:
    token, chat_id = _load_telegram_config()
    if not token or not chat_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urlencode({"chat_id": chat_id, "text": text[:4000]}).encode("utf-8")
        req = Request(url, data=data)
        with urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return bool(payload.get("ok"))
    except Exception:
        return False


def maybe_notify(result: WatchdogResult, lines: list[str]) -> bool:
    del result, lines
    return False

    # keep below logic for future rollback if needed
    state = _load_state()
    last_key = str(state.get("last_notice_key", "") or "")
    if result.restarted_gateway:
        key = "repair:" + datetime.now(KST).strftime("%Y-%m-%dT%H")
        if key == last_key:
            return False
        sent = _send_telegram_message(
            "[OpenClaw 자동복구]\n"
            "Codex 인증 토큰을 Codex CLI 기준으로 다시 동기화했고, "
            "OpenClaw gateway를 자동 재시작했습니다.\n"
            "원인: openai-codex OAuth refresh 실패(refresh_token_reused)."
        )
        if sent:
            _save_state({"last_notice_key": key})
        return sent
    if result.fallback_added:
        key = "fallback-added"
        if key == last_key:
            return False
        sent = _send_telegram_message(
            "[OpenClaw 자동복구]\n"
            "로컬 fallback 모델을 연결했습니다.\n"
            f"추가된 모델: {OLLAMA_FALLBACK_MODEL}\n"
            "이제 Codex 인증/쿨다운 중에도 OpenClaw가 로컬 모델로 우회할 수 있습니다."
        )
        if sent:
            _save_state({"last_notice_key": key})
        return sent
    if any("API rate limit reached" in line for line in lines):
        key = "rate-limit:" + datetime.now(KST).strftime("%Y-%m-%dT%H")
        if key == last_key:
            return False
        sent = _send_telegram_message(
            "[OpenClaw 상태 알림]\n"
            "openai-codex 사용량/쿨다운 제한이 감지되었습니다.\n"
            "이 경우 자동 재시작으로는 해결되지 않아 잠시 후 재시도됩니다."
        )
        if sent:
            _save_state({"last_notice_key": key})
        return sent
    return False


def main() -> int:
    result = WatchdogResult()
    state = _load_state()
    synced, profile = sync_auth_profiles()
    result.synced = synced
    result.auth_order_fixed = ensure_auth_order()
    result.fallback_added = ensure_local_fallback()
    lines = recent_gateway_errors()
    auth_error_key = latest_auth_error_key(lines)
    if auth_error_key and auth_error_key != str(state.get("last_handled_auth_error", "") or ""):
        result.restarted_gateway = restart_gateway()
        result.login_link_started = ensure_remote_login_flow()
        if result.restarted_gateway:
            result.status = "repaired"
            result.detail = "synced codex auth and restarted gateway"
            _save_state({"last_handled_auth_error": auth_error_key})
        else:
            result.status = "error"
            result.detail = "gateway restart failed"
    else:
        result.detail = "no auth refresh issue detected"
    result.sent_notice = maybe_notify(result, lines)
    payload = {
        "timestamp": datetime.now(KST).isoformat(),
        "status": result.status,
        "synced": result.synced,
        "auth_order_fixed": result.auth_order_fixed,
        "fallback_added": result.fallback_added,
        "login_link_started": result.login_link_started,
        "restarted_gateway": result.restarted_gateway,
        "sent_notice": result.sent_notice,
        "detail": result.detail,
        "profile_expires": profile.get("expires") if profile else None,
    }
    print(json.dumps(_save_state(payload), ensure_ascii=False))
    return 0 if result.status != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
