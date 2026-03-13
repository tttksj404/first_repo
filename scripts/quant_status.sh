#!/bin/sh
set -eu

BASE_DIR="${1:-quant_runtime}"
STATE_FILE="$(python3 - <<'PY' "$BASE_DIR"
from pathlib import Path
import sys
base = Path(sys.argv[1])
latest = base / 'output' / 'paper-live-shell' / 'latest' / 'summary.state.json'
paths = [p for p in base.rglob('summary.state.json') if p.exists()]
if latest.exists() and latest not in paths:
    paths.append(latest)
paths = sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)
print(paths[0] if paths else '')
PY
)"
SUMMARY_FILE=""

if [ -n "$STATE_FILE" ]; then
  RUN_DIR="$(dirname "$STATE_FILE")"
  if [ -f "$RUN_DIR/summary.json" ]; then
    SUMMARY_FILE="$RUN_DIR/summary.json"
  fi
fi

if [ -z "$SUMMARY_FILE" ]; then
  SUMMARY_FILE="$(python3 - <<'PY' "$BASE_DIR"
from pathlib import Path
import sys
base = Path(sys.argv[1])
latest = base / 'output' / 'paper-live-shell' / 'latest' / 'summary.json'
paths = [p for p in base.rglob('summary.json') if p.exists()]
if latest.exists() and latest not in paths:
    paths.append(latest)
paths = sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)
print(paths[0] if paths else '')
PY
)"
fi

if [ -z "$STATE_FILE" ]; then
  echo "No runtime state file found under $BASE_DIR"
  exit 1
fi

echo "STATE_FILE=$STATE_FILE"
[ -n "$SUMMARY_FILE" ] && echo "SUMMARY_FILE=$SUMMARY_FILE"
echo
python3 - <<'PY' "$STATE_FILE" "$SUMMARY_FILE"
import json, sys
from pathlib import Path

state_path = Path(sys.argv[1])
summary_path = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else None
state = json.loads(state_path.read_text(encoding='utf-8'))
summary = json.loads(summary_path.read_text(encoding='utf-8')) if summary_path and summary_path.exists() else {}

print("updated_at:", state.get("updated_at"))
print("heartbeat_count:", state.get("heartbeat_count"))
print("decision_count:", state.get("decision_count"))
print("tested_order_count:", state.get("tested_order_count"))
print("live_order_count:", state.get("live_order_count"))
print("last_event_timestamp:", state.get("last_event_timestamp"))
print("last_decision_timestamp:", state.get("last_decision_timestamp"))
print("kill_switch:", state.get("kill_switch"))
self_healing = state.get("self_healing") or summary.get("self_healing") or {}
print("self_healing_status:", self_healing.get("status"))
print("self_healing_active_guards:", self_healing.get("active_guards"))
print("self_healing_recent_events:", self_healing.get("recent_events"))
paper_futures_positions = state.get("paper_open_futures_positions")
if paper_futures_positions is None:
    paper_futures_positions = summary.get("paper_open_futures_positions") or summary.get("open_futures_positions") or []
exchange_futures_positions = state.get("exchange_live_futures_positions")
if exchange_futures_positions is None:
    exchange_futures_positions = summary.get("exchange_live_futures_positions") or []
mismatch_details = state.get("futures_position_mismatch_details") or summary.get("futures_position_mismatch_details") or {}
print("paper_open_futures_position_count:", state.get("paper_open_futures_position_count", len(paper_futures_positions)))
print("paper_open_futures_symbols:", [item.get("symbol") for item in paper_futures_positions])
print("exchange_live_futures_position_count:", state.get("exchange_live_futures_position_count", len(exchange_futures_positions)))
print("exchange_live_futures_symbols:", [item.get("symbol") for item in exchange_futures_positions])
print("futures_position_mismatch:", state.get("futures_position_mismatch"))
print(
    "futures_position_warning:",
    {
        "missing_in_paper": mismatch_details.get("missing_in_paper") or [],
        "missing_on_exchange": mismatch_details.get("missing_on_exchange") or [],
    },
)
for item in exchange_futures_positions[:5]:
    print(
        "live_position:",
        item.get("symbol"),
        item.get("holdSide"),
        "roe=",
        round((float(item.get("unrealizedPL") or 0.0) / max(float(item.get("marginSize") or 1e-9), 1e-9)) * 100.0, 2),
        "marginRatio=",
        item.get("marginRatio"),
    )
recent_decisions = summary.get("recent_decisions") or []
if recent_decisions:
    print("recent_decisions:", recent_decisions)
top_rejections = summary.get("top_rejection_reasons") or {}
if top_rejections:
    print("top_rejection_reasons:", top_rejections)
PY
