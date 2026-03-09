#!/bin/sh
set -eu

BASE_DIR="${1:-quant_runtime}"
STATE_FILE="$(python3 - <<'PY' "$BASE_DIR"
from pathlib import Path
import sys
base = Path(sys.argv[1])
paths = sorted(base.rglob('summary.state.json'), key=lambda p: p.stat().st_mtime, reverse=True)
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
paths = sorted(base.rglob('summary.json'), key=lambda p: p.stat().st_mtime, reverse=True)
print(paths[0] if paths else '')
PY
)"
fi

if [ -z "$SUMMARY_FILE" ] || [ -z "$STATE_FILE" ]; then
  echo "no summary/state files found under $BASE_DIR"
  exit 1
fi

python3 - <<'PY' "$SUMMARY_FILE" "$STATE_FILE"
import json, sys
summary = json.load(open(sys.argv[1], encoding='utf-8'))
state = json.load(open(sys.argv[2], encoding='utf-8'))
print("summary_file:", sys.argv[1])
print("state_file:", sys.argv[2])
print("decision_count:", summary.get("decision_count"))
print("live_order_count:", summary.get("live_order_count"))
print("tested_order_count:", summary.get("tested_order_count"))
print("symbols:", summary.get("symbols"))
print("modes:", summary.get("modes"))
print("kill_switch:", summary.get("kill_switch"))
print("updated_at:", state.get("updated_at"))
print("heartbeat_count:", state.get("heartbeat_count"))
print("last_event_timestamp:", state.get("last_event_timestamp"))
print("last_decision_timestamp:", state.get("last_decision_timestamp"))
capital = summary.get("capital_report") or {}
if capital:
    print("spot_available_balance_usd:", capital.get("spot_available_balance_usd"))
    print("futures_available_balance_usd:", capital.get("futures_available_balance_usd"))
    print("can_trade_spot_any:", capital.get("can_trade_spot_any"))
    print("can_trade_futures_any:", capital.get("can_trade_futures_any"))
PY
