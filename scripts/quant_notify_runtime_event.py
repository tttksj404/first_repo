from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_binance.telegram_notify import send_telegram_message
from quant_binance.telegram_reports import format_runtime_telegram_report


def _load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_latest_jsonl_record(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    for raw in reversed(path.read_text(encoding="utf-8").splitlines()):
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _parse_metadata(items: list[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            metadata[key] = value
    return metadata


def _load_alert_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _should_suppress_alert(*, state_path: Path, signature: str, now_ts: float, cooldown_seconds: int = 300) -> bool:
    state = _load_alert_state(state_path)
    previous_signature = str(state.get("signature", ""))
    previous_ts = float(state.get("timestamp", 0.0) or 0.0)
    if previous_signature == signature and now_ts - previous_ts < cooldown_seconds:
        return True
    state_path.write_text(
        json.dumps({"signature": signature, "timestamp": now_ts}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return False


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if len(args) < 2:
        print("usage: quant_notify_runtime_event.py <event> <output_base>", file=sys.stderr)
        return 1

    event = args[0].strip()
    output_base = Path(args[1]).resolve()
    metadata = _parse_metadata(args[2:])
    latest_root = output_base / "output" / "paper-live-shell" / "latest"
    state = _load_json(latest_root / "summary.state.json")
    summary = _load_json(latest_root / "summary.json")
    health = _load_json(output_base / "live_supervisor_health.json")
    order_error = _load_latest_jsonl_record(latest_root / "logs" / "order_errors.jsonl")
    alert_state_path = output_base / "runtime_alert_state.json"

    signature = "|".join(
        [
            event,
            str(metadata.get("reason", "")),
            str(metadata.get("exit_code", "")),
            str(health.get("reason", "")),
            str(order_error.get("error_message", "")),
        ]
    )
    now_ts = time.time()
    if _should_suppress_alert(state_path=alert_state_path, signature=signature, now_ts=now_ts):
        print(json.dumps({"event": event, "sent": False, "reason": "suppressed_duplicate"}, indent=2, sort_keys=True))
        return 0

    report_text = format_runtime_telegram_report(
        output_base,
        event=event,
        metadata=metadata,
    )
    result = send_telegram_message(report_text)
    print(json.dumps({"event": event, "sent": result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
