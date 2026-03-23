#!/bin/sh
set -eu

HOST_PYTHON_DEFAULT="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
PATH="/Library/Frameworks/Python.framework/Versions/3.14/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
export PATH
if [ -z "${PYTHON_BIN:-}" ] && [ -x "$HOST_PYTHON_DEFAULT" ]; then
  PYTHON_BIN="$HOST_PYTHON_DEFAULT"
  export PYTHON_BIN
fi

resolve_python_bin() {
  if [ -n "${PYTHON_BIN:-}" ] && [ -x "${PYTHON_BIN}" ]; then
    printf '%s\n' "$PYTHON_BIN"
    return 0
  fi

  for candidate in /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3
  do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  printf '[BOOT] python resolver failed in %s at %s env_PYTHON_BIN=%s PATH=%s\n' "$0" "$(date '+%Y-%m-%d %H:%M:%S %Z')" "${PYTHON_BIN:-}" "$PATH" >&2
  exit 1
}

PYTHON_BIN="$(resolve_python_bin)"
export PYTHON_BIN

OUTPUT_BASE="${1:-quant_runtime}"
CHECK_INTERVAL_SECONDS="${QUANT_SUPERVISOR_WATCHDOG_INTERVAL_SECONDS:-60}"
STALE_SECONDS="${QUANT_SUPERVISOR_WATCHDOG_STALE_SECONDS:-240}"
RESTART_COOLDOWN_SECONDS="${QUANT_SUPERVISOR_WATCHDOG_RESTART_COOLDOWN_SECONDS:-45}"
LOG_DIR="$OUTPUT_BASE"
SUPERVISOR_LOG="$LOG_DIR/live_supervisor.log"
PID_PATH="$LOG_DIR/live_supervisor.pid"
WATCHDOG_PID_PATH="$LOG_DIR/live_supervisor_watchdog.pid"
SUMMARY_PATH="$OUTPUT_BASE/output/paper-live-shell/latest/summary.state.json"
QUANT_TELEGRAM_NOTIFICATIONS_VALUE="${QUANT_TELEGRAM_NOTIFICATIONS:-0}"
QUANT_BYPASS_POLICY_GUARDRAILS_VALUE="${QUANT_BYPASS_POLICY_GUARDRAILS:-1}"

mkdir -p "$LOG_DIR"
cd "$(dirname "$0")/.."
if [ -f "$WATCHDOG_PID_PATH" ]; then
  EXISTING_WATCHDOG_PID="$(cat "$WATCHDOG_PID_PATH" 2>/dev/null || true)"
  if [ -n "$EXISTING_WATCHDOG_PID" ] && kill -0 "$EXISTING_WATCHDOG_PID" 2>/dev/null; then
    printf '[WATCHDOG] existing watchdog pid=%s already running at %s\n' "$EXISTING_WATCHDOG_PID" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
    exit 0
  fi
fi
printf '%s\n' "$$" >"$WATCHDOG_PID_PATH"
trap 'rm -f "$WATCHDOG_PID_PATH"' INT TERM EXIT

log() {
  printf '[WATCHDOG] %s at %s\n' "$1" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
}

supervisor_alive() {
  pid=""
  if [ -f "$PID_PATH" ]; then
    pid="$(cat "$PID_PATH" 2>/dev/null || true)"
  fi
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    if printf '%s' "$cmd" | grep -F "scripts/quant_run_live_orders.sh $OUTPUT_BASE" >/dev/null 2>&1; then
      return 0
    fi
  fi
  fallback_pid="$(pgrep -f "sh scripts/quant_run_live_orders.sh $OUTPUT_BASE" | head -n 1 || true)"
  [ -n "$fallback_pid" ] || return 1
  printf '%s
' "$fallback_pid" >"$PID_PATH"
  return 0
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
  log "restarting supervisor python_bin=$PYTHON_BIN pwd=$(pwd)"
  nohup env     PATH="/Library/Frameworks/Python.framework/Versions/3.14/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"     QUANT_TELEGRAM_NOTIFICATIONS="$QUANT_TELEGRAM_NOTIFICATIONS_VALUE"     QUANT_BYPASS_POLICY_GUARDRAILS="$QUANT_BYPASS_POLICY_GUARDRAILS_VALUE"     PYTHON_BIN="$PYTHON_BIN"     sh scripts/quant_run_live_orders.sh "$OUTPUT_BASE" >>"$SUPERVISOR_LOG" 2>&1 &
  sleep "$RESTART_COOLDOWN_SECONDS"
}

log "watchdog started pid=$$ interval=${CHECK_INTERVAL_SECONDS}s stale=${STALE_SECONDS}s python_bin=$PYTHON_BIN"
while :; do
  if ! supervisor_alive; then
    if summary_fresh; then
      log "supervisor pid missing but summary still fresh; skipping restart"
    else
      log "supervisor missing"
      restart_supervisor
    fi
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
