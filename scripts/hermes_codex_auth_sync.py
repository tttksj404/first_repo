#!/usr/bin/env python3
"""Codex OAuth 토큰 자동 갱신 데몬.

access_token이 만료되기 48시간 전에 refresh_token으로 자동 갱신.
갱신된 토큰을 ~/.codex/auth.json 과 ~/.hermes/auth.json 양쪽에 저장.
게이트웨이도 자동 재시작.

refresh_token 자체가 만료되면 (invalid_grant) Telegram으로 알림 → 수동 로그인 필요.

LaunchAgent로 5분마다 실행.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

KST = timezone(timedelta(hours=9))

CODEX_AUTH_PATH    = Path.home() / ".codex" / "auth.json"
HERMES_AUTH_PATH   = Path.home() / ".hermes" / "auth.json"
HERMES_GATEWAY_STATE_PATH = Path.home() / ".hermes" / "gateway_state.json"
HERMES_ENV_PATH = Path.home() / ".hermes" / ".env"
HERMES_GATEWAY_LOG_PATH = Path.home() / ".hermes" / "logs" / "gateway.log"
HERMES_ERRORS_LOG_PATH = Path.home() / ".hermes" / "logs" / "errors.log"
OPENCLAW_CONFIG_PATH = Path.home() / ".openclaw" / "openclaw.json"
HERMES_VENV_PYTHON = Path.home() / ".hermes" / "hermes-agent" / "venv" / "bin" / "python"
HERMES_MAIN        = Path.home() / ".hermes" / "hermes-agent" / "hermes_cli" / "main.py"

LOG_PATH   = Path.home() / ".hermes" / "logs" / "codex_auth_sync.log"
STATE_PATH = Path.home() / ".hermes" / "codex_auth_sync_state.json"

# 만료 48시간 전에 갱신 시작
REFRESH_THRESHOLD_HOURS = 48
OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
GATEWAY_ERROR_STORM_WINDOW_MINUTES = 15
GATEWAY_INVALID_RESPONSE_STORM_THRESHOLD = 2
GATEWAY_POLLING_CONFLICT_STORM_THRESHOLD = 4
GATEWAY_STORM_RESTART_COOLDOWN_MINUTES = 10


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    ts = datetime.now(KST).isoformat(timespec="seconds")
    line = f"{ts} {msg}"
    print(line, flush=True)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        # 로그 파일 5MB 초과 시 로테이션
        if LOG_PATH.stat().st_size > 5 * 1024 * 1024:
            bak = LOG_PATH.with_suffix(".log.1")
            LOG_PATH.rename(bak)
    except Exception:
        pass


def _load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def _tail_lines(path: Path, max_lines: int = 2000) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    if max_lines <= 0:
        return lines
    return lines[-max_lines:]


def _parse_log_timestamp(line: str) -> datetime | None:
    m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3}\b", line)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None
    return dt.replace(tzinfo=KST)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _decode_jwt_exp(token: str) -> float | None:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload.encode()))
        exp = claims.get("exp")
        return float(exp) if exp is not None else None
    except Exception:
        return None


def _hours_remaining(token: str) -> float | None:
    exp = _decode_jwt_exp(token)
    if exp is None:
        return None
    return (exp - time.time()) / 3600


# ---------------------------------------------------------------------------
# 토큰 읽기 / 쓰기
# ---------------------------------------------------------------------------

def _best_tokens() -> dict | None:
    """현재 가장 유효한 토큰 반환. hermes > codex 우선순위."""
    hermes = _hermes_tokens()
    codex  = _codex_tokens()

    def hours(t: dict | None) -> float:
        if not t:
            return -9999
        h = _hours_remaining(t.get("access_token", ""))
        return h if h is not None else -9999

    if hours(hermes) >= hours(codex):
        return hermes or codex
    return codex or hermes


def _hermes_tokens() -> dict | None:
    auth = _load_json(HERMES_AUTH_PATH)
    if not isinstance(auth, dict):
        return None
    state = (auth.get("providers") or {}).get("openai-codex") or {}
    t = state.get("tokens")
    return dict(t) if isinstance(t, dict) else None


def _codex_tokens() -> dict | None:
    auth = _load_json(CODEX_AUTH_PATH)
    if not isinstance(auth, dict):
        return None
    t = auth.get("tokens")
    return dict(t) if isinstance(t, dict) else None


def _save_both(tokens: dict) -> None:
    """갱신된 토큰을 ~/.codex/auth.json 과 ~/.hermes/auth.json 양쪽에 저장."""
    now_z = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

    # --- ~/.codex/auth.json ---
    codex_auth = _load_json(CODEX_AUTH_PATH) or {}
    codex_auth["tokens"] = tokens
    codex_auth["last_refresh"] = now_z
    codex_auth.setdefault("auth_mode", "chatgpt")
    _atomic_write_json(CODEX_AUTH_PATH, codex_auth)

    # --- ~/.hermes/auth.json ---
    hermes_auth = _load_json(HERMES_AUTH_PATH) or {}
    providers = dict(hermes_auth.get("providers") or {})
    state = dict(providers.get("openai-codex") or {})
    state["tokens"] = tokens
    state["last_refresh"] = now_z
    providers["openai-codex"] = state
    hermes_auth["version"] = hermes_auth.get("version", 1)
    hermes_auth["providers"] = providers
    hermes_auth["updated_at"] = now_z
    _atomic_write_json(HERMES_AUTH_PATH, hermes_auth)


# ---------------------------------------------------------------------------
# OAuth 갱신
# ---------------------------------------------------------------------------

def refresh_access_token(tokens: dict) -> dict:
    """refresh_token으로 새 access_token 발급. 새 토큰 dict 반환."""
    refresh_token = str(tokens.get("refresh_token") or "").strip()
    if not refresh_token:
        raise ValueError("refresh_token 없음")

    data = urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": OAUTH_CLIENT_ID,
    }).encode()

    req = Request(
        OAUTH_TOKEN_URL,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode())
    except HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body}") from e
    except URLError as e:
        raise RuntimeError(f"URLError: {e.reason}") from e

    new_at = str(payload.get("access_token") or "").strip()
    if not new_at:
        raise RuntimeError(f"응답에 access_token 없음: {payload}")

    updated = dict(tokens)
    updated["access_token"] = new_at
    # refresh_token이 rotate되면 저장
    new_rt = str(payload.get("refresh_token") or "").strip()
    if new_rt:
        updated["refresh_token"] = new_rt

    return updated


# ---------------------------------------------------------------------------
# 게이트웨이
# ---------------------------------------------------------------------------

def hermes_gateway_healthy() -> bool:
    state = _load_json(HERMES_GATEWAY_STATE_PATH) or {}
    pid = state.get("pid")
    pid_ok = False
    try:
        pid_ok = _pid_alive(int(pid))
    except Exception:
        pid_ok = False

    return (
        state.get("gateway_state") == "running"
        and (state.get("platforms") or {}).get("telegram", {}).get("state") == "connected"
        and pid_ok
    )


def restart_hermes_gateway() -> bool:
    try:
        cmd = [str(HERMES_VENV_PYTHON), "-m", "hermes_cli.main", "gateway", "restart"]
        proc = subprocess.run(
            cmd,
            cwd=str(HERMES_MAIN.parent.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=45,
            check=False,
        )

        # launchd restart 경로 실패 시 직접 실행으로 1회 폴백
        if proc.returncode != 0:
            subprocess.Popen(
                [str(HERMES_VENV_PYTHON), "-m", "hermes_cli.main", "gateway", "run", "--replace"],
                cwd=str(HERMES_MAIN.parent.parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

        # 최대 12초 대기
        for _ in range(12):
            time.sleep(1)
            if hermes_gateway_healthy():
                return True
        return hermes_gateway_healthy()
    except Exception as e:
        _log(f"WARN gateway restart error: {e}")
        return False


def _load_hermes_telegram_token() -> str | None:
    try:
        text = HERMES_ENV_PATH.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() != "TELEGRAM_BOT_TOKEN":
            continue
        token = v.strip().strip("\"'")
        return token or None
    return None


def _launchctl_print_loaded(label: str) -> bool:
    uid = os.getuid()
    cmd = ["launchctl", "print", f"gui/{uid}/{label}"]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return proc.returncode == 0


def _disable_openclaw_gateway_service() -> bool:
    label = "ai.openclaw.gateway"
    uid = os.getuid()
    plist = str(Path.home() / "Library" / "LaunchAgents" / f"{label}.plist")
    commands = [
        ["launchctl", "bootout", f"gui/{uid}", label],
        ["launchctl", "bootout", f"gui/{uid}", plist],
        ["launchctl", "disable", f"gui/{uid}/{label}"],
    ]
    success = False
    for cmd in commands:
        try:
            proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=20)
            if proc.returncode == 0:
                success = True
        except Exception:
            continue
    return success


def _enforce_single_telegram_poller(state: dict) -> tuple[dict, bool]:
    openclaw_token, _ = _load_telegram_config()
    hermes_token = _load_hermes_telegram_token()
    if not openclaw_token or not hermes_token:
        return state, False
    if openclaw_token != hermes_token:
        return state, False
    if not _launchctl_print_loaded("ai.openclaw.gateway"):
        return state, False

    disabled = _disable_openclaw_gateway_service()
    if disabled:
        _log("INFO: openclaw gateway disabled (same Telegram bot token as Hermes)")
        state["openclaw_gateway_disabled_at"] = datetime.now(KST).isoformat(timespec="seconds")
        state = _alert_once(
            state,
            "openclaw_disabled",
            "[Hermes] Telegram 중복 poller 방지: OpenClaw gateway를 자동 비활성화했습니다.",
        )
    else:
        _log("WARN: failed to disable openclaw gateway despite token collision")
    return state, disabled


def _collect_gateway_error_signals(window_minutes: int = GATEWAY_ERROR_STORM_WINDOW_MINUTES) -> dict:
    now = datetime.now(KST)
    cutoff = now - timedelta(minutes=window_minutes)
    invalid_keys: set[str] = set()
    conflict_keys: set[str] = set()

    for path in (HERMES_GATEWAY_LOG_PATH, HERMES_ERRORS_LOG_PATH):
        for line in _tail_lines(path, max_lines=2500):
            ts = _parse_log_timestamp(line)
            if ts is None or ts < cutoff:
                continue
            ts_key = ts.strftime("%Y-%m-%d %H:%M:%S")
            if "Invalid API response after 3 retries." in line:
                invalid_keys.add(ts_key)
            if "Telegram polling conflict" in line:
                conflict_keys.add(ts_key)

    return {
        "window_minutes": window_minutes,
        "invalid_api_response_count": len(invalid_keys),
        "polling_conflict_count": len(conflict_keys),
        "checked_at": now.isoformat(timespec="seconds"),
    }


def _detect_gateway_error_storm(signals: dict) -> tuple[bool, str]:
    invalid_count = int(signals.get("invalid_api_response_count", 0))
    conflict_count = int(signals.get("polling_conflict_count", 0))

    if invalid_count >= GATEWAY_INVALID_RESPONSE_STORM_THRESHOLD:
        return True, f"invalid_response_storm({invalid_count})"
    if conflict_count >= GATEWAY_POLLING_CONFLICT_STORM_THRESHOLD:
        return True, f"polling_conflict_storm({conflict_count})"
    return False, ""


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def _load_telegram_config() -> tuple[str | None, str | None]:
    config = _load_json(OPENCLAW_CONFIG_PATH) or {}
    telegram = (config.get("channels") or {}).get("telegram") or {}
    token = str(telegram.get("botToken") or "").strip() or None
    allow_from = telegram.get("allowFrom") or []
    chat_id = str(allow_from[0]).strip() if allow_from else None
    return token, chat_id


def _send_telegram(text: str) -> bool:
    token, chat_id = _load_telegram_config()
    if not token or not chat_id:
        return False
    try:
        data = urlencode({"chat_id": chat_id, "text": text[:4000]}).encode()
        req = Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
        with urlopen(req, timeout=15) as resp:
            return bool(json.loads(resp.read()).get("ok"))
    except Exception:
        return False


def _alert_once(state: dict, key: str, text: str) -> dict:
    """같은 key로 중복 알림 방지 (1시간 단위)."""
    now_h = datetime.now(KST).isoformat(timespec="hours")
    last = state.get(f"alert_{key}", "")
    if last != now_h:
        if _send_telegram(text):
            state[f"alert_{key}"] = now_h
    return state


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main() -> int:
    state = _load_json(STATE_PATH) or {}
    tokens = _best_tokens()

    if not tokens:
        _log("ERROR: 토큰 없음. 수동 로그인 필요.")
        state = _alert_once(state, "no_tokens",
            "[Hermes/Codex] ⚠️ 토큰 없음\n수동으로 Codex 앱 로그인 필요.")
        _atomic_write_json(STATE_PATH, state)
        return 1

    at = tokens.get("access_token", "")
    hours = _hours_remaining(at)
    _log(f"CHECK access_token_remaining={hours:.1f}h" if hours is not None else "CHECK access_token_remaining=unknown")

    refreshed = False
    gateway_restarted = False
    openclaw_disabled = False

    # access_token 만료 48시간 전부터 갱신
    needs_refresh = (hours is None) or (hours < REFRESH_THRESHOLD_HOURS)

    if needs_refresh:
        _log(f"REFRESH 시작 (remaining={hours:.1f}h)" if hours is not None else "REFRESH 시작 (exp 파싱 불가)")
        try:
            new_tokens = refresh_access_token(tokens)
            _save_both(new_tokens)
            new_hours = _hours_remaining(new_tokens.get("access_token", ""))
            _log(f"REFRESH 완료 → 새 토큰 {new_hours:.1f}h 유효" if new_hours else "REFRESH 완료")
            state["last_refreshed_at"] = datetime.now(KST).isoformat()
            state["last_refresh_hours"] = round(new_hours, 1) if new_hours else None
            refreshed = True
        except RuntimeError as e:
            err = str(e)
            _log(f"REFRESH 실패: {err}")
            # invalid_grant = refresh_token도 만료 → 수동 로그인 필요
            if any(x in err for x in ("invalid_grant", "invalid_token", "400", "401")):
                _log("CRITICAL: refresh_token 만료. 수동 로그인 필요.")
                state = _alert_once(state, "relogin_needed",
                    "[Hermes/Codex] ⚠️ 토큰 갱신 실패\n"
                    f"오류: {err[:200]}\n"
                    "Codex 앱에서 다시 로그인해 주세요.")
            else:
                state = _alert_once(state, "refresh_error",
                    f"[Hermes/Codex] 토큰 갱신 오류\n{err[:300]}\n잠시 후 재시도합니다.")

    # 게이트웨이 상태 확인
    if not hermes_gateway_healthy():
        _log("WARN: 게이트웨이 비정상. 재시작 중...")
        gateway_restarted = restart_hermes_gateway()
        _log(f"게이트웨이 재시작={'성공' if gateway_restarted else '실패'}")
        if not gateway_restarted:
            state = _alert_once(state, "gateway_down",
                "[Hermes] 게이트웨이 재시작 실패\n수동 확인 필요.")
    elif refreshed:
        # 갱신 후에는 게이트웨이도 재시작해서 새 토큰 로드
        _log("갱신 후 게이트웨이 재시작...")
        gateway_restarted = restart_hermes_gateway()
        _log(f"게이트웨이 재시작={'성공' if gateway_restarted else '실패'}")

    # Telegram poller 단일화: 같은 bot token 사용 시 OpenClaw 게이트웨이 비활성화
    state, openclaw_disabled = _enforce_single_telegram_poller(state)

    # 에러 폭주(Invalid API response / polling conflict) 감지 시 자동 재시작
    signals = _collect_gateway_error_signals()
    storm, storm_reason = _detect_gateway_error_storm(signals)
    state["gateway_error_signals"] = signals

    if storm:
        last_storm_restart = _parse_iso(state.get("last_storm_restart_at"))
        cooldown = timedelta(minutes=GATEWAY_STORM_RESTART_COOLDOWN_MINUTES)
        now = datetime.now(KST)
        in_cooldown = bool(last_storm_restart and now - last_storm_restart < cooldown)

        if in_cooldown:
            left = cooldown - (now - last_storm_restart)
            _log(f"WARN: gateway error storm detected ({storm_reason}) but cooldown active ({int(left.total_seconds())}s left)")
        else:
            _log(f"WARN: gateway error storm detected ({storm_reason}). Restarting gateway...")
            restarted = restart_hermes_gateway()
            gateway_restarted = gateway_restarted or restarted
            state["last_storm_reason"] = storm_reason
            state["last_storm_restart_at"] = now.isoformat(timespec="seconds")
            _log(f"storm restart result={'성공' if restarted else '실패'}")
            if not restarted:
                state = _alert_once(
                    state,
                    "gateway_storm_restart_failed",
                    f"[Hermes] 게이트웨이 에러 폭주 자동 복구 실패 ({storm_reason})\n수동 점검 필요.",
                )

    state.update({
        "checked_at": datetime.now(KST).isoformat(),
        "access_token_hours_remaining": round(hours, 1) if hours is not None else None,
        "refreshed": refreshed,
        "gateway_restarted": gateway_restarted,
        "gateway_healthy": hermes_gateway_healthy(),
        "openclaw_disabled": openclaw_disabled,
    })
    _atomic_write_json(STATE_PATH, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
