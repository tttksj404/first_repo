from __future__ import annotations

import json
import os
import ssl
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path("/Users/tttksj/first_repo")
ENV_FILES = [ROOT / ".env", ROOT / ".env.local"]
SSL_CONTEXT = ssl._create_unverified_context()


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


def send_telegram_message(text: str) -> dict[str, object]:
    token = load_env_value("TELEGRAM_BOT_TOKEN")
    allowed = load_env_value("TELEGRAM_CHAT_ID_ALLOWLIST")
    chat_ids = [item.strip() for item in allowed.split(",") if item.strip()]
    if not token or not chat_ids:
        return {"sent": False, "reason": "missing_token_or_allowlist"}
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    params = {"chat_id": chat_ids[0], "text": text[:4000]}
    data = urlencode(params).encode("utf-8")
    req = Request(url, data=data)
    with urlopen(req, timeout=60, context=SSL_CONTEXT) as resp:
        return json.loads(resp.read().decode("utf-8"))
