#!/bin/sh
set -eu

slot_pid() {
  slot_path="$1"
  awk 'NR == 1 { print $1; exit }' "$slot_path" 2>/dev/null || true
}

pid_is_visible() {
  pid="$1"
  case "$pid" in
    ''|*[!0-9]*) return 1 ;;
  esac
  if kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  if command -v lsof >/dev/null 2>&1 && lsof -a -p "$pid" -d cwd >/dev/null 2>&1; then
    return 0
  fi
  if ps -p "$pid" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
SUPERVISOR_STOP_FILE="$REPO_ROOT/scripts/_supervisor_stop"
PYTHON_LAUNCHER="$SCRIPT_DIR/quant_python.sh"

run_python() {
  sh "$PYTHON_LAUNCHER" "$@"
}

supervisor_stop_requested() {
  [ -f "$SUPERVISOR_STOP_FILE" ] && grep -qi 'stop' "$SUPERVISOR_STOP_FILE" 2>/dev/null
}

OUTPUT_BASE="${1:-quant_runtime}"
LOG_DIR="$OUTPUT_BASE"
SUPERVISOR_LOG="$LOG_DIR/live_supervisor.log"
SUPERVISOR_PID_PATH="$LOG_DIR/live_supervisor.pid"

mkdir -p "$LOG_DIR"
if supervisor_stop_requested; then
  printf '[SUPERVISOR] stop file present; refusing to start at %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
  exit 0
fi
if [ -f "$SUPERVISOR_PID_PATH" ]; then
  EXISTING_SUPERVISOR_PID="$(slot_pid "$SUPERVISOR_PID_PATH")"
  if pid_is_visible "$EXISTING_SUPERVISOR_PID"; then
    printf '[SUPERVISOR] existing supervisor pid=%s already running at %s\n' "$EXISTING_SUPERVISOR_PID" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
    exit 0
  fi
fi

if [ ! -f "$PYTHON_LAUNCHER" ]; then
  printf '[BOOT] python launcher missing: %s\n' "$PYTHON_LAUNCHER" >&2
  exit 1
fi

SYNC_INTERVAL_SECONDS="${SYNC_INTERVAL_SECONDS:-15}"
WATCHDOG_POLL_SECONDS="${QUANT_LIVE_WATCHDOG_POLL_SECONDS:-30}"
WATCHDOG_STALE_SECONDS="${QUANT_LIVE_WATCHDOG_STALE_SECONDS:-150}"
WATCHDOG_DECISION_STALL_SECONDS="${QUANT_LIVE_WATCHDOG_DECISION_STALL_SECONDS:-420}"
STARTUP_GRACE_SECONDS="${QUANT_LIVE_STARTUP_GRACE_SECONDS:-120}"
RESTART_SLEEP_SECONDS="${QUANT_LIVE_RESTART_SLEEP_SECONDS:-5}"
STARTUP_FAILURE_BACKOFF_SECONDS="${QUANT_LIVE_STARTUP_FAILURE_BACKOFF_SECONDS:-180}"
REPORT_INTERVAL_SECONDS="${QUANT_REPORT_INTERVAL_SECONDS:-14400}"
REPORT_PROVIDER="${QUANT_REPORT_PROVIDER:-codex}"
REPORT_MODE="${QUANT_REPORT_MODE:-advisor}"
QUANT_TELEGRAM_NOTIFICATIONS="${QUANT_TELEGRAM_NOTIFICATIONS:-0}"
REPORT_SEND_FLAG="${QUANT_REPORT_SEND_FLAG:-}"
if [ "$QUANT_TELEGRAM_NOTIFICATIONS" = "1" ] && [ -z "$REPORT_SEND_FLAG" ]; then
  REPORT_SEND_FLAG="--send-telegram"
fi
HEALTH_STATE_PATH="$LOG_DIR/live_supervisor_health.json"
SUPERVISOR_WATCHDOG_PID_PATH="$LOG_DIR/live_supervisor_watchdog.pid"
SUPERVISOR_LOCK_DIR="$LOG_DIR/live_supervisor.lock"

acquire_supervisor_lock() {
  if mkdir "$SUPERVISOR_LOCK_DIR" 2>/dev/null; then
    printf '%s\n' "$$" >"$SUPERVISOR_LOCK_DIR/pid"
    return 0
  fi

  if [ -f "$SUPERVISOR_PID_PATH" ]; then
    EXISTING_SUPERVISOR_PID="$(slot_pid "$SUPERVISOR_PID_PATH")"
    if pid_is_visible "$EXISTING_SUPERVISOR_PID"; then
      printf '[SUPERVISOR] existing supervisor pid=%s already running at %s\n' "$EXISTING_SUPERVISOR_PID" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
      exit 0
    fi
  fi

  LOCK_OWNER_PID="$(slot_pid "$SUPERVISOR_LOCK_DIR/pid")"
  if pid_is_visible "$LOCK_OWNER_PID"; then
    printf '[SUPERVISOR] supervisor lock held by pid=%s at %s\n' "$LOCK_OWNER_PID" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
    exit 0
  fi

  rm -rf "$SUPERVISOR_LOCK_DIR"
  if mkdir "$SUPERVISOR_LOCK_DIR" 2>/dev/null; then
    printf '%s\n' "$$" >"$SUPERVISOR_LOCK_DIR/pid"
    return 0
  fi

  printf '[SUPERVISOR] could not acquire supervisor lock at %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
  exit 0
}

acquire_supervisor_lock

if [ -f "$SUPERVISOR_PID_PATH" ]; then
  EXISTING_SUPERVISOR_PID="$(slot_pid "$SUPERVISOR_PID_PATH")"
  if pid_is_visible "$EXISTING_SUPERVISOR_PID"; then
    printf '[SUPERVISOR] existing supervisor pid=%s already running at %s\n' "$EXISTING_SUPERVISOR_PID" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
    exit 0
  fi
fi

export EXCHANGE="bitget"
export STRATEGY_PROFILE="${STRATEGY_PROFILE:-live-ultra-aggressive}"
export STRATEGY_OVERRIDE_PATH="${STRATEGY_OVERRIDE_PATH:-$OUTPUT_BASE/artifacts/strategy_override.approved.json}"
DEFAULT_MACRO_INPUTS_PATH="$OUTPUT_BASE/artifacts/news_macro_inputs.json"
MANUAL_MACRO_INPUTS_PATH="$OUTPUT_BASE/artifacts/news_macro_inputs.manual.json"
if [ -z "${MACRO_INPUTS_PATH:-}" ]; then
  if [ -f "$MANUAL_MACRO_INPUTS_PATH" ]; then
    export MACRO_INPUTS_PATH="$MANUAL_MACRO_INPUTS_PATH"
    export QUANT_DISABLE_NEWS_MACRO_LOOP="${QUANT_DISABLE_NEWS_MACRO_LOOP:-1}"
  else
    export MACRO_INPUTS_PATH="$DEFAULT_MACRO_INPUTS_PATH"
  fi
fi
export TELEGRAM_REPORT_ONLY="${TELEGRAM_REPORT_ONLY:-1}"
export QUANT_BYPASS_POLICY_GUARDRAILS="${QUANT_BYPASS_POLICY_GUARDRAILS:-1}"

cd "$REPO_ROOT"

CHILD_PID=""
REPORT_PID=""
NEWS_PID=""

cleanup() {
  lock_owner_pid="$(slot_pid "$SUPERVISOR_LOCK_DIR/pid")"
  if [ "$lock_owner_pid" = "$$" ]; then
    rm -rf "$SUPERVISOR_LOCK_DIR"
  fi
  current_supervisor_pid="$(slot_pid "$SUPERVISOR_PID_PATH")"
  if [ "$current_supervisor_pid" = "$$" ]; then
    rm -f "$SUPERVISOR_PID_PATH"
  fi
  if [ -n "${REPORT_PID:-}" ] && kill -0 "$REPORT_PID" 2>/dev/null; then
    kill "$REPORT_PID" 2>/dev/null || true
    wait "$REPORT_PID" 2>/dev/null || true
  fi
  if [ -n "${NEWS_PID:-}" ] && kill -0 "$NEWS_PID" 2>/dev/null; then
    kill "$NEWS_PID" 2>/dev/null || true
    wait "$NEWS_PID" 2>/dev/null || true
  fi
  if [ -n "${CHILD_PID:-}" ] && kill -0 "$CHILD_PID" 2>/dev/null; then
    if [ "$QUANT_TELEGRAM_NOTIFICATIONS" = "1" ]; then
      run_python scripts/quant_notify_runtime_event.py stopped "$OUTPUT_BASE" "child_pid=$CHILD_PID" >>"$SUPERVISOR_LOG" 2>&1 || true
    fi
    kill "$CHILD_PID" 2>/dev/null || true
    wait "$CHILD_PID" 2>/dev/null || true
  fi
  exit 0
}

printf '%s %s\n' "$$" "v1:$(cksum "$0" | awk '{print $1}')" >"$SUPERVISOR_PID_PATH"
printf '[SUPERVISOR] python_launcher=%s at %s\n' "$PYTHON_LAUNCHER" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
trap cleanup INT TERM EXIT

start_watchdog() {
  if [ "${QUANT_ENABLE_SUPERVISOR_WATCHDOG:-1}" != "1" ]; then
    printf '[SUPERVISOR] watchdog autostart disabled at %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
    return 0
  fi
  nohup env \
    PATH="$PATH" \
    QUANT_TELEGRAM_NOTIFICATIONS="$QUANT_TELEGRAM_NOTIFICATIONS" \
    QUANT_BYPASS_POLICY_GUARDRAILS="$QUANT_BYPASS_POLICY_GUARDRAILS" \
    QUANT_PYTHON_BIN="${QUANT_PYTHON_BIN:-}" \
    sh "$PYTHON_LAUNCHER" scripts/quant_live_watchdog.py "$OUTPUT_BASE" >>"$SUPERVISOR_LOG" 2>&1 &
  watchdog_start_status=$?
  watchdog_pid=$!
  if [ "$watchdog_start_status" -ne 0 ]; then
    printf '[SUPERVISOR] watchdog start request failed status=%s at %s\n' "$watchdog_start_status" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
    return 0
  fi
  printf '[SUPERVISOR] requested watchdog start pid=%s at %s\n' "$watchdog_pid" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
}

run_report_cycle() {
  printf '[SUPERVISOR] running strategy advisor cycle provider=%s mode=%s send_flag=%s at %s\n' "$REPORT_PROVIDER" "$REPORT_MODE" "$REPORT_SEND_FLAG" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
  sh scripts/quant_strategy_advisor_cycle.sh "$OUTPUT_BASE" "$REPORT_PROVIDER" "$REPORT_MODE" "$REPORT_SEND_FLAG" >>"$SUPERVISOR_LOG" 2>&1 || \
    printf '[SUPERVISOR] strategy advisor cycle failed at %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
}

run_report_loop() {
  while :; do
    run_report_cycle
    sleep "$REPORT_INTERVAL_SECONDS"
  done
}

start_report_loop() {
  if [ "$QUANT_TELEGRAM_NOTIFICATIONS" != "1" ]; then
    printf '[SUPERVISOR] report loop disabled (telegram notifications off) at %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
    return 0
  fi
  run_report_loop &
  REPORT_PID=$!
  printf '[SUPERVISOR] started report loop pid=%s interval=%ss at %s\n' "$REPORT_PID" "$REPORT_INTERVAL_SECONDS" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
}

start_news_loop() {
  if [ "${QUANT_DISABLE_NEWS_MACRO_LOOP:-0}" = "1" ]; then
    printf '[SUPERVISOR] news macro loop disabled; using MACRO_INPUTS_PATH=%s at %s\n' "$MACRO_INPUTS_PATH" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
    return 0
  fi
  sh scripts/quant_news_macro_signal_cycle.sh "$OUTPUT_BASE" 900 >>"$SUPERVISOR_LOG" 2>&1 &
  NEWS_PID=$!
  printf '[SUPERVISOR] started news macro loop pid=%s at %s\n' "$NEWS_PID" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
}

run_child() {
  CHILD_STARTED_AT_EPOCH="$(date +%s)"
  run_python -m quant_binance.runtime \
    --mode live-auto-trade-daemon \
    --exchange "bitget" \
    --output-base "$OUTPUT_BASE" \
    --max-retries 999999 \
    --insecure-ssl \
    --ack-live-risk I_UNDERSTAND_LIVE_TRADING \
    --sync-interval-seconds "$SYNC_INTERVAL_SECONDS" \
    --equity-usd 75 >>"$SUPERVISOR_LOG" 2>&1 &
  CHILD_PID=$!
  printf '[SUPERVISOR] started child pid=%s supervisor_pid=%s at %s\n' "$CHILD_PID" "$$" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
  if [ "$QUANT_TELEGRAM_NOTIFICATIONS" = "1" ]; then
    run_python scripts/quant_notify_runtime_event.py started "$OUTPUT_BASE" "child_pid=$CHILD_PID" >>"$SUPERVISOR_LOG" 2>&1 || true
  fi
}

health_check() {
  run_python - <<'PY' "$OUTPUT_BASE" "$WATCHDOG_STALE_SECONDS" "$WATCHDOG_DECISION_STALL_SECONDS" "$STARTUP_GRACE_SECONDS" "$HEALTH_STATE_PATH" "${CHILD_STARTED_AT_EPOCH:-0}"
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

output_base = Path(sys.argv[1])
stale_seconds = int(sys.argv[2])
decision_stall_seconds = int(sys.argv[3])
startup_grace_seconds = int(sys.argv[4])
state_path = Path(sys.argv[5])
child_started_epoch = float(sys.argv[6] or 0)
summary_state_path = output_base / "output" / "paper-live-shell" / "latest" / "summary.state.json"
now = datetime.now(tz=timezone.utc)

if not summary_state_path.exists():
    payload = {"status": "starting", "reason": "missing_summary_state", "checked_at": now.isoformat()}
    state_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    sys.exit(0)

data = json.loads(summary_state_path.read_text(encoding="utf-8"))
runtime_status = str(data.get("status") or "")
updated_at_raw = data.get("updated_at")
updated_at = datetime.fromisoformat(updated_at_raw) if isinstance(updated_at_raw, str) else None
if updated_at is None:
    payload = {"status": "unhealthy", "reason": "missing_updated_at", "checked_at": now.isoformat()}
    state_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    sys.exit(1)

age_seconds = max((now - updated_at).total_seconds(), 0.0)
decision_emitted_raw = data.get("last_decision_emitted_at")
decision_emitted_at = datetime.fromisoformat(decision_emitted_raw) if isinstance(decision_emitted_raw, str) else None
decision_age_seconds = max((now - decision_emitted_at).total_seconds(), 0.0) if decision_emitted_at else None
heartbeat_count = int(data.get("heartbeat_count") or 0)
decision_count = int(data.get("decision_count") or 0)

payload = {
    "status": "healthy",
    "checked_at": now.isoformat(),
    "updated_at": updated_at.isoformat(),
    "updated_age_seconds": round(age_seconds, 3),
    "heartbeat_count": heartbeat_count,
    "decision_count": decision_count,
    "last_decision_emitted_at": decision_emitted_at.isoformat() if decision_emitted_at else None,
    "decision_age_seconds": round(decision_age_seconds, 3) if decision_age_seconds is not None else None,
}

if child_started_epoch > 0 and updated_at.timestamp() < child_started_epoch:
    child_age_seconds = max(now.timestamp() - child_started_epoch, 0.0)
    if child_age_seconds <= startup_grace_seconds:
        payload["status"] = "starting"
        payload["reason"] = "previous_summary_state_startup_grace"
        payload["child_started_at_epoch"] = round(child_started_epoch, 3)
        payload["child_age_seconds"] = round(child_age_seconds, 3)
        state_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        sys.exit(0)

if runtime_status == "startup_failed":
    payload["status"] = "unhealthy"
    payload["reason"] = "startup_failed"
    if data.get("error"):
        payload["error"] = str(data.get("error"))
    state_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    sys.exit(1)

if age_seconds > stale_seconds:
    payload["status"] = "unhealthy"
    payload["reason"] = "summary_state_stale"
    state_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    sys.exit(1)

if heartbeat_count <= 0 and age_seconds <= startup_grace_seconds:
    payload["status"] = "starting"
    payload["reason"] = "startup_grace"
    state_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    sys.exit(0)

if decision_emitted_at is not None and decision_age_seconds is not None and decision_age_seconds > decision_stall_seconds:
    payload["status"] = "unhealthy"
    payload["reason"] = "decision_emission_stalled"
    state_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    sys.exit(1)

state_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
sys.exit(0)
PY
}

start_report_loop
start_news_loop
start_watchdog

while :; do
  if supervisor_stop_requested; then
    printf '[SUPERVISOR] stop file present; exiting supervisor loop at %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
    exit 0
  fi
  run_child
  while kill -0 "$CHILD_PID" 2>/dev/null; do
    sleep "$WATCHDOG_POLL_SECONDS"
    if supervisor_stop_requested; then
      printf '[SUPERVISOR] stop file present; stopping child pid=%s at %s\n' "$CHILD_PID" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
      kill "$CHILD_PID" 2>/dev/null || true
      wait "$CHILD_PID" 2>/dev/null || true
      exit 0
    fi
    # Auto-restart watchdog if it died
    if [ "${QUANT_ENABLE_SUPERVISOR_WATCHDOG:-1}" = "1" ]; then
      WATCHDOG_SLOT_PID="$(slot_pid "$SUPERVISOR_WATCHDOG_PID_PATH")"
      if ! pid_is_visible "$WATCHDOG_SLOT_PID"; then
        printf '[SUPERVISOR] watchdog died, restarting at %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
        start_watchdog
      fi
    fi
    if ! health_check; then
      HEALTH_REASON="$(run_python - <<'PY' "$HEALTH_STATE_PATH"
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    data = {}
print(data.get("reason", "unknown"))
PY
)"
      printf '[SUPERVISOR] restarting unhealthy child pid=%s at %s\n' "$CHILD_PID" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
      if [ "$QUANT_TELEGRAM_NOTIFICATIONS" = "1" ]; then
        run_python scripts/quant_notify_runtime_event.py unhealthy "$OUTPUT_BASE" "child_pid=$CHILD_PID" "reason=$HEALTH_REASON" >>"$SUPERVISOR_LOG" 2>&1 || true
      fi
      if [ "$HEALTH_REASON" = "startup_failed" ] && [ "$STARTUP_FAILURE_BACKOFF_SECONDS" -gt 0 ]; then
        printf '[SUPERVISOR] startup_failed; backing off %ss before restart at %s\n' "$STARTUP_FAILURE_BACKOFF_SECONDS" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
        sleep "$STARTUP_FAILURE_BACKOFF_SECONDS"
      fi
      kill "$CHILD_PID" 2>/dev/null || true
      wait "$CHILD_PID" 2>/dev/null || true
      break
    fi
  done
  CHILD_EXIT_CODE=0
  wait "$CHILD_PID" 2>/dev/null || CHILD_EXIT_CODE=$?
  if supervisor_stop_requested; then
    printf '[SUPERVISOR] stop file present after child exit; not restarting at %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
    exit 0
  fi
  printf '[SUPERVISOR] child exited, restarting in %ss at %s\n' "$RESTART_SLEEP_SECONDS" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
  if [ "$QUANT_TELEGRAM_NOTIFICATIONS" = "1" ]; then
    run_python scripts/quant_notify_runtime_event.py exited "$OUTPUT_BASE" "child_pid=$CHILD_PID" "exit_code=$CHILD_EXIT_CODE" >>"$SUPERVISOR_LOG" 2>&1 || true
  fi
  sleep "$RESTART_SLEEP_SECONDS"
done
