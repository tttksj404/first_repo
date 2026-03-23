#!/bin/sh
set -eu

resolve_python_bin() {
  if [ -n "${PYTHON_BIN:-}" ] && [ -x "${PYTHON_BIN}" ]; then
    printf '%s
' "$PYTHON_BIN"
    return 0
  fi
  for candidate in "$(command -v python3 2>/dev/null || true)"                    "$(command -v python 2>/dev/null || true)"                    /Library/Frameworks/Python.framework/Versions/3.14/bin/python3                    /opt/homebrew/bin/python3                    /usr/local/bin/python3                    /usr/bin/python3; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
      printf '%s
' "$candidate"
      return 0
    fi
  done
  printf '%s
' python3
}

PYTHON_BIN="$(resolve_python_bin)"

OUTPUT_BASE="${1:-quant_runtime}"
CHECK_INTERVAL_SECONDS="${QUANT_SUPERVISOR_WATCHDOG_INTERVAL_SECONDS:-60}"
STALE_SECONDS="${QUANT_SUPERVISOR_WATCHDOG_STALE_SECONDS:-240}"
RESTART_COOLDOWN_SECONDS="${QUANT_SUPERVISOR_WATCHDOG_RESTART_COOLDOWN_SECONDS:-45}"
LOG_DIR="$OUTPUT_BASE"
SUPERVISOR_LOG="$LOG_DIR/live_supervisor.log"
PID_PATH="$LOG_DIR/live_supervisor.pid"
WATCHDOG_PID_PATH="$LOG_DIR/live_supervisor_watchdog.pid"
SUMMARY_PATH="$OUTPUT_BASE/output/paper-live-shell/latest/summary.state.json"
START_CMD="env QUANT_TELEGRAM_NOTIFICATIONS=${QUANT_TELEGRAM_NOTIFICATIONS:-0} QUANT_BYPASS_POLICY_GUARDRAILS=${QUANT_BYPASS_POLICY_GUARDRAILS:-1} sh scripts/quant_run_live_orders.sh $OUTPUT_BASE"

mkdir -p "$LOG_DIR"
cd "$(dirname "$0")/.."
printf '%s\n' "$$" >"$WATCHDOG_PID_PATH"
trap 'rm -f "$WATCHDOG_PID_PATH"' INT TERM EXIT

log() {
  printf '[WATCHDOG] %s at %s\n' "$1" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
}

supervisor_alive() {
  if [ ! -f "$PID_PATH" ]; then
    return 1
  fi
  pid="$(cat "$PID_PATH" 2>/dev/null || true)"
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null
}

summary_fresh() {
  "$PYTHON_BIN" - <<'PY' "$SUMMARY_PATH" "$STALE_SECONDS"
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
path = Path(sys.argv[1])
stale_seconds = int(sys.argv[2])
if not path.exists():
    raise SystemExit(1)
try:
    data = json.loads(path.read_text(encoding='utf-8'))
    raw = data.get('updated_at')
    if not isinstance(raw, str):
        raise SystemExit(1)
    updated = datetime.fromisoformat(raw)
except Exception:
    raise SystemExit(1)
age = (datetime.now(timezone.utc) - updated).total_seconds()
raise SystemExit(0 if age <= stale_seconds else 1)
PY
}

restart_supervisor() {
  log "restarting supervisor"
  nohup sh -c "$START_CMD" >>"$SUPERVISOR_LOG" 2>&1 &
  sleep "$RESTART_COOLDOWN_SECONDS"
}

log "watchdog started pid=$$ interval=${CHECK_INTERVAL_SECONDS}s stale=${STALE_SECONDS}s"
while :; do
  if ! supervisor_alive; then
    log "supervisor missing"
    restart_supervisor
  elif ! summary_fresh; then
    log "summary stale or missing"
    pid="$(cat "$PID_PATH" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 2
    fi
    restart_supervisor
  fi
  sleep "$CHECK_INTERVAL_SECONDS"
done
