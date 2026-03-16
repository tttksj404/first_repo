from __future__ import annotations

import json
import os
import ssl
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path("/Users/tttksj/first_repo")
ENV_FILES = [ROOT / ".env", ROOT / ".env.local"]
OPENCLAW_ALLOWLIST_FILES = [
    Path("/Users/tttksj/.openclaw/credentials/telegram-default-allowFrom.json"),
    Path("/Users/tttksj/.openclaw/openclaw.json"),
    Path("/Users/tttksj/.openclaw/openclaw.json.bak.1"),
    Path("/Users/tttksj/.openclaw/openclaw.json.bak.2"),
]
SSL_CONTEXT = ssl._create_unverified_context()


def _env_flag_enabled(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_env_value(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    for path in ENV_FILES:
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            if key.strip() == name:
                return val.strip().strip('"').strip("'")
    return ""


def _load_openclaw_chat_ids() -> list[str]:
    resolved: list[str] = []
    for path in OPENCLAW_ALLOWLIST_FILES:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        candidates: list[str] = []
        if isinstance(payload, dict):
            allow_from = payload.get("allowFrom")
            if isinstance(allow_from, list):
                candidates.extend(str(item).strip() for item in allow_from if str(item).strip())
            telegram = payload.get("channels", {}).get("telegram") if isinstance(payload.get("channels"), dict) else None
            if isinstance(telegram, dict):
                allow_from = telegram.get("allowFrom")
                if isinstance(allow_from, list):
                    candidates.extend(str(item).strip() for item in allow_from if str(item).strip())
        for candidate in candidates:
            if candidate and candidate not in resolved:
                resolved.append(candidate)
        if resolved:
            return resolved
    return resolved


def resolve_telegram_chat_ids() -> list[str]:
    resolved: list[str] = []
    raw_candidates = [
        load_env_value("TELEGRAM_CHAT_ID_ALLOWLIST"),
        load_env_value("TELEGRAM_CHAT_ID"),
    ]
    for raw in raw_candidates:
        for item in str(raw).split(","):
            chat_id = item.strip()
            if chat_id and chat_id not in resolved:
                resolved.append(chat_id)
    for chat_id in _load_openclaw_chat_ids():
        if chat_id and chat_id not in resolved:
            resolved.append(chat_id)
    return resolved


def telegram_report_only_enabled() -> bool:
    return _env_flag_enabled(load_env_value("TELEGRAM_REPORT_ONLY"))


def send_telegram_message(text: str) -> dict[str, object]:
    token = load_env_value("TELEGRAM_BOT_TOKEN")
    chat_ids = resolve_telegram_chat_ids()
    if not token or not chat_ids:
        return {"sent": False, "reason": "missing_token_or_allowlist"}
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    responses: list[dict[str, object]] = []
    for chat_id in chat_ids:
        params = {"chat_id": chat_id, "text": text[:4000]}
        data = urlencode(params).encode("utf-8")
        req = Request(url, data=data)
        with urlopen(req, timeout=60, context=SSL_CONTEXT) as resp:
            responses.append(json.loads(resp.read().decode("utf-8")))
    return {"sent": True, "chat_ids": chat_ids, "responses": responses}
