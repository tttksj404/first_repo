#!/bin/sh
set -eu

OUTPUT_BASE="${1:-quant_runtime}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
PYTHON_LAUNCHER="$SCRIPT_DIR/quant_python.sh"
HEALTH_STATE_PATH="$OUTPUT_BASE/live_supervisor_health.json"

mkdir -p "$SCRIPT_DIR"
printf 'stop\n' >"$SCRIPT_DIR/_supervisor_stop"
printf 'stop\n' >"$SCRIPT_DIR/_safety_guardian_stop"

slot_pid() {
  slot_path="$1"
  awk 'NR == 1 { print $1; exit }' "$slot_path" 2>/dev/null || true
}

write_health_state() {
  if [ ! -f "$PYTHON_LAUNCHER" ]; then
    return 0
  fi
  if ! sh "$PYTHON_LAUNCHER" - "$HEALTH_STATE_PATH" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

now = datetime.now(tz=timezone.utc).isoformat()
payload = {
    "checked_at": now,
    "reason": "stopped_by_quant_stop",
    "status": "stopped",
    "summary": "runtime intentionally stopped via quant_stop.sh",
    "updated_at": now,
}
path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
PY
  then
    return 0
  fi
}

write_health_state

for pid_path in \
  "$OUTPUT_BASE/live_supervisor.pid" \
  "$OUTPUT_BASE/live_supervisor_watchdog.pid" \
  "$OUTPUT_BASE/live_supervisor.lock/pid"
do
  pid="$(slot_pid "$pid_path")"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
  fi
done

pkill -f 'quant_binance.runtime --mode live-auto-trade-daemon' || true
pkill -f 'quant_binance.runtime --mode live-paper-daemon' || true
pkill -f 'scripts/quant_live_watchdog.py' || true
pkill -f 'scripts/quant_run_live_orders.sh' || true

sleep 2

pkill -9 -f 'quant_binance.runtime --mode live-auto-trade-daemon' || true
pkill -9 -f 'quant_binance.runtime --mode live-paper-daemon' || true
pkill -9 -f 'scripts/quant_live_watchdog.py' || true
pkill -9 -f 'scripts/quant_run_live_orders.sh' || true

rm -f "$OUTPUT_BASE/live_supervisor.pid" "$OUTPUT_BASE/live_supervisor_watchdog.pid"
rm -rf "$OUTPUT_BASE/live_supervisor.lock"

echo "stopped"
