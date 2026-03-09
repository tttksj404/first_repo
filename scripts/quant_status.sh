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

if [ -z "$STATE_FILE" ]; then
  echo "No runtime state file found under $BASE_DIR"
  exit 1
fi

echo "STATE_FILE=$STATE_FILE"
[ -n "$SUMMARY_FILE" ] && echo "SUMMARY_FILE=$SUMMARY_FILE"
echo
python3 - <<'PY' "$STATE_FILE"
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding='utf-8'))

print("updated_at:", data.get("updated_at"))
print("heartbeat_count:", data.get("heartbeat_count"))
print("decision_count:", data.get("decision_count"))
print("tested_order_count:", data.get("tested_order_count"))
print("live_order_count:", data.get("live_order_count"))
print("last_event_timestamp:", data.get("last_event_timestamp"))
print("last_decision_timestamp:", data.get("last_decision_timestamp"))
print("kill_switch:", data.get("kill_switch"))
PY
