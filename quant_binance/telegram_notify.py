from __future__ import annotations

import hashlib
import json
import os
import ssl
import time
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
TELEGRAM_NOTIFY_STATE_PATH = ROOT / "quant_runtime" / "telegram_notify_state.json"
DEFAULT_DEDUP_WINDOW_SECONDS = 180
DEFAULT_BURST_WINDOW_SECONDS = 45
DEFAULT_BURST_THRESHOLD = 3


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


def _normalize_message_text(text: str) -> str:
    normalized = "\n".join(line.rstrip() for line in text.strip().splitlines())
    while "\n\n\n" in normalized:
        normalized = normalized.replace("\n\n\n", "\n\n")
    return normalized.strip()


def _message_signature(text: str) -> str:
    normalized = _normalize_message_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _message_preview(text: str, *, limit: int = 140) -> str:
    normalized = _normalize_message_text(text).replace("\n", " / ")
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _dedup_window_seconds() -> int:
    raw = load_env_value("TELEGRAM_NOTIFY_DEDUP_WINDOW_SECONDS")
    try:
        return max(int(raw), 0)
    except (TypeError, ValueError):
        return DEFAULT_DEDUP_WINDOW_SECONDS


def _burst_window_seconds() -> int:
    raw = load_env_value("TELEGRAM_NOTIFY_BURST_WINDOW_SECONDS")
    try:
        return max(int(raw), 0)
    except (TypeError, ValueError):
        return DEFAULT_BURST_WINDOW_SECONDS


def _burst_threshold() -> int:
    raw = load_env_value("TELEGRAM_NOTIFY_BURST_THRESHOLD")
    try:
        return max(int(raw), 1)
    except (TypeError, ValueError):
        return DEFAULT_BURST_THRESHOLD


def _load_notify_state(path: Path = TELEGRAM_NOTIFY_STATE_PATH) -> dict[str, object]:
    if not path.exists():
        return {"recent": [], "last_sent": {}, "burst": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"recent": [], "last_sent": {}, "burst": {}}
    if not isinstance(payload, dict):
        return {"recent": [], "last_sent": {}, "burst": {}}
    payload.setdefault("recent", [])
    payload.setdefault("last_sent", {})
    payload.setdefault("burst", {})
    return payload


def _save_notify_state(state: dict[str, object], path: Path = TELEGRAM_NOTIFY_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _compact_burst_summary(entries: list[dict[str, object]]) -> str:
    lines = ["[AUTO_SUMMARY] 짧은 시간에 응답이 몰려 정리해서 보냄"]
    for entry in entries[-5:]:
        preview = str(entry.get("preview", "")).strip()
        if preview:
            lines.append(f"- {preview}")
    return "\n".join(lines)


def _prepare_outbound_text(text: str, *, now_ts: float | None = None, state_path: Path = TELEGRAM_NOTIFY_STATE_PATH) -> tuple[str | None, dict[str, object]]:
    now_ts = now_ts if now_ts is not None else time.time()
    normalized = _normalize_message_text(text)
    signature = _message_signature(normalized)
    state = _load_notify_state(state_path)
    dedup_window = _dedup_window_seconds()
    burst_window = _burst_window_seconds()
    burst_threshold = _burst_threshold()

    last_sent = state.get("last_sent", {})
    if isinstance(last_sent, dict):
        previous = last_sent.get(signature)
        if isinstance(previous, (int, float)) and dedup_window > 0 and now_ts - float(previous) < dedup_window:
            state["recent"] = list(state.get("recent", []))[-20:]
            _save_notify_state(state, state_path)
            return None, {"sent": False, "reason": "dedup_suppressed", "signature": signature}

    recent = [item for item in list(state.get("recent", [])) if isinstance(item, dict)]
    if burst_window > 0:
        recent = [item for item in recent if now_ts - float(item.get("timestamp", 0.0) or 0.0) <= burst_window]
    recent.append({"timestamp": now_ts, "signature": signature, "preview": _message_preview(normalized)})
    state["recent"] = recent[-20:]

    burst = state.get("burst", {}) if isinstance(state.get("burst"), dict) else {}
    outgoing = normalized
    if len(recent) >= burst_threshold:
        burst_signature = hashlib.sha256("|".join(str(item.get("signature", "")) for item in recent[-burst_threshold:]).encode("utf-8")).hexdigest()
        last_burst_signature = str(burst.get("signature", ""))
        last_burst_ts = float(burst.get("timestamp", 0.0) or 0.0)
        if burst_signature == last_burst_signature and dedup_window > 0 and now_ts - last_burst_ts < dedup_window:
            _save_notify_state(state, state_path)
            return None, {"sent": False, "reason": "burst_summary_already_sent", "signature": signature}
        outgoing = _compact_burst_summary(recent)
        burst = {"signature": burst_signature, "timestamp": now_ts, "count": len(recent)}
        state["burst"] = burst
        signature = _message_signature(outgoing)

    state_last_sent = state.get("last_sent", {}) if isinstance(state.get("last_sent"), dict) else {}
    state_last_sent[signature] = now_ts
    if len(state_last_sent) > 200:
        trimmed = sorted(state_last_sent.items(), key=lambda item: float(item[1]))[-200:]
        state_last_sent = dict(trimmed)
    state["last_sent"] = state_last_sent
    _save_notify_state(state, state_path)
    return outgoing, {"sent": True, "signature": signature, "burst_count": len(recent)}


def _deliver_message(*, token: str, chat_ids: list[str], text: str) -> dict[str, object]:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    responses: list[dict[str, object]] = []
    for chat_id in chat_ids:
        params = {"chat_id": chat_id, "text": text[:4000]}
        data = urlencode(params).encode("utf-8")
        req = Request(url, data=data)
        with urlopen(req, timeout=60, context=SSL_CONTEXT) as resp:
            responses.append(json.loads(resp.read().decode("utf-8")))
    return {"sent": True, "chat_ids": chat_ids, "responses": responses}


def send_telegram_message(text: str) -> dict[str, object]:
    token = load_env_value("TELEGRAM_BOT_TOKEN")
    chat_ids = resolve_telegram_chat_ids()
    if not token or not chat_ids:
        return {"sent": False, "reason": "missing_token_or_allowlist"}
    prepared_text, meta = _prepare_outbound_text(text)
    if not prepared_text:
        return meta
    result = _deliver_message(token=token, chat_ids=chat_ids, text=prepared_text)
    return result | {"prepared": meta, "text": prepared_text}
