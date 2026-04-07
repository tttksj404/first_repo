#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pty
import re
import select
import signal
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


KST = timezone(timedelta(hours=9))
OPENCLAW_BIN = "/Users/tttksj/.npm-global/bin/openclaw"
OPENCLAW_DIR = Path("/Users/tttksj/.openclaw")
OPENCLAW_CONFIG_PATH = OPENCLAW_DIR / "openclaw.json"
STATE_PATH = OPENCLAW_DIR / "memory" / "codex-remote-login-state.json"
LOG_PATH = OPENCLAW_DIR / "logs" / "codex-remote-login.log"
URL_RE = re.compile(r"Open:\s+(https://\S+)")


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


def _load_telegram_config() -> tuple[str | None, str | None]:
    config = _load_json(OPENCLAW_CONFIG_PATH, {})
    telegram = dict(dict(config.get("channels", {}) or {}).get("telegram", {}) or {})
    token = str(telegram.get("botToken", "") or "").strip() or None
    allow_from = telegram.get("allowFrom") or []
    chat_id = str(allow_from[0]).strip() if allow_from else ""
    return token, (chat_id or None)


def _send_telegram_message(text: str) -> bool:
    token, chat_id = _load_telegram_config()
    if not token or not chat_id:
        return False
    try:
        req = Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=urlencode({"chat_id": chat_id, "text": text[:4000]}).encode("utf-8"),
        )
        with urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return bool(payload.get("ok"))
    except Exception:
        return False


def _pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _load_state() -> dict[str, Any]:
    value = _load_json(STATE_PATH, {})
    return value if isinstance(value, dict) else {}


def _save_state(updates: dict[str, Any]) -> dict[str, Any]:
    state = _load_state()
    state.update(updates)
    _atomic_write_json(STATE_PATH, state)
    return state


def main() -> int:
    state = _load_state()
    existing_pid = int(state.get("pid", 0) or 0)
    if _pid_alive(existing_pid):
        print(json.dumps({"status": "already_running", "pid": existing_pid}, ensure_ascii=False))
        return 0

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_handle = LOG_PATH.open("a", encoding="utf-8")
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        [OPENCLAW_BIN, "models", "auth", "login", "--provider", "openai-codex", "--set-default"],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        start_new_session=True,
        close_fds=True,
        text=False,
    )
    os.close(slave_fd)

    url: str | None = None
    deadline = time.time() + 45
    buffer = ""
    while time.time() < deadline and proc.poll() is None:
        ready, _, _ = select.select([master_fd], [], [], 1.0)
        if not ready:
            continue
        chunk = os.read(master_fd, 4096).decode("utf-8", errors="replace")
        if not chunk:
            continue
        log_handle.write(chunk)
        log_handle.flush()
        buffer += chunk
        match = URL_RE.search(buffer)
        if match:
            url = match.group(1).strip()
            break

    if url:
        _save_state(
            {
                "pid": proc.pid,
                "status": "waiting_browser_auth",
                "auth_url": url,
                "started_at": datetime.now(KST).isoformat(),
            }
        )
        _send_telegram_message(
            "[OpenClaw 로그인 필요]\n"
            "Codex 인증이 만료되어 새 로그인 링크를 만들었습니다.\n"
            f"{url}\n\n"
            "휴대폰 브라우저에서 열어 로그인하세요. "
            "같은 Mac 브라우저에서 열면 자동 완료될 확률이 더 높습니다."
        )
        print(json.dumps({"status": "started", "pid": proc.pid, "auth_url": url}, ensure_ascii=False))
        return 0

    if proc.poll() is None:
        os.kill(proc.pid, signal.SIGTERM)
    print(json.dumps({"status": "failed_to_capture_url", "pid": proc.pid}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
