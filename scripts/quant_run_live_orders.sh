#!/bin/sh
set -eu

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
SYNC_INTERVAL_SECONDS="${SYNC_INTERVAL_SECONDS:-15}"
WATCHDOG_POLL_SECONDS="${QUANT_LIVE_WATCHDOG_POLL_SECONDS:-30}"
WATCHDOG_STALE_SECONDS="${QUANT_LIVE_WATCHDOG_STALE_SECONDS:-150}"
WATCHDOG_DECISION_STALL_SECONDS="${QUANT_LIVE_WATCHDOG_DECISION_STALL_SECONDS:-420}"
STARTUP_GRACE_SECONDS="${QUANT_LIVE_STARTUP_GRACE_SECONDS:-120}"
RESTART_SLEEP_SECONDS="${QUANT_LIVE_RESTART_SLEEP_SECONDS:-5}"
REPORT_INTERVAL_SECONDS="${QUANT_REPORT_INTERVAL_SECONDS:-14400}"
REPORT_PROVIDER="${QUANT_REPORT_PROVIDER:-codex}"
REPORT_MODE="${QUANT_REPORT_MODE:-advisor}"
QUANT_TELEGRAM_NOTIFICATIONS="${QUANT_TELEGRAM_NOTIFICATIONS:-0}"
REPORT_SEND_FLAG="${QUANT_REPORT_SEND_FLAG:-}"
if [ "$QUANT_TELEGRAM_NOTIFICATIONS" = "1" ] && [ -z "$REPORT_SEND_FLAG" ]; then
  REPORT_SEND_FLAG="--send-telegram"
fi
LOG_DIR="$OUTPUT_BASE"
SUPERVISOR_LOG="$LOG_DIR/live_supervisor.log"
HEALTH_STATE_PATH="$LOG_DIR/live_supervisor_health.json"
SUPERVISOR_PID_PATH="$LOG_DIR/live_supervisor.pid"
SUPERVISOR_WATCHDOG_PID_PATH="$LOG_DIR/live_supervisor_watchdog.pid"

mkdir -p "$LOG_DIR"
if [ -f "$SUPERVISOR_PID_PATH" ]; then
  EXISTING_SUPERVISOR_PID="$(cat "$SUPERVISOR_PID_PATH" 2>/dev/null || true)"
  if [ -n "$EXISTING_SUPERVISOR_PID" ] && kill -0 "$EXISTING_SUPERVISOR_PID" 2>/dev/null; then
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

cd "$(dirname "$0")/.."

CHILD_PID=""
REPORT_PID=""
NEWS_PID=""

cleanup() {
  rm -f "$SUPERVISOR_PID_PATH"
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
      "$PYTHON_BIN" scripts/quant_notify_runtime_event.py stopped "$OUTPUT_BASE" "child_pid=$CHILD_PID" >>"$SUPERVISOR_LOG" 2>&1 || true
    fi
    kill "$CHILD_PID" 2>/dev/null || true
    wait "$CHILD_PID" 2>/dev/null || true
  fi
  exit 0
}

printf '%s\n' "$$" >"$SUPERVISOR_PID_PATH"
printf '[SUPERVISOR] python_bin=%s at %s\n' "$PYTHON_BIN" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
trap cleanup INT TERM EXIT

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
  "$PYTHON_BIN" -m quant_binance.runtime \
    --mode live-auto-trade-daemon \
    --exchange "bitget" \
    --output-base "$OUTPUT_BASE" \
    --max-retries 999999 \
    --insecure-ssl \
    --ack-live-risk I_UNDERSTAND_LIVE_TRADING \
    --sync-interval-seconds "$SYNC_INTERVAL_SECONDS" >>"$SUPERVISOR_LOG" 2>&1 &
  CHILD_PID=$!
  printf '[SUPERVISOR] started child pid=%s supervisor_pid=%s at %s\n' "$CHILD_PID" "$$" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
  if [ "$QUANT_TELEGRAM_NOTIFICATIONS" = "1" ]; then
    "$PYTHON_BIN" scripts/quant_notify_runtime_event.py started "$OUTPUT_BASE" "child_pid=$CHILD_PID" >>"$SUPERVISOR_LOG" 2>&1 || true
  fi
}

health_check() {
  "$PYTHON_BIN" - <<'PY' "$OUTPUT_BASE" "$WATCHDOG_STALE_SECONDS" "$WATCHDOG_DECISION_STALL_SECONDS" "$STARTUP_GRACE_SECONDS" "$HEALTH_STATE_PATH"
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

output_base = Path(sys.argv[1])
stale_seconds = int(sys.argv[2])
decision_stall_seconds = int(sys.argv[3])
startup_grace_seconds = int(sys.argv[4])
state_path = Path(sys.argv[5])
summary_state_path = output_base / "output" / "paper-live-shell" / "latest" / "summary.state.json"
now = datetime.now(tz=timezone.utc)

if not summary_state_path.exists():
    payload = {"status": "starting", "reason": "missing_summary_state", "checked_at": now.isoformat()}
    state_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    sys.exit(0)

data = json.loads(summary_state_path.read_text(encoding="utf-8"))
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

while :; do
  run_child
  while kill -0 "$CHILD_PID" 2>/dev/null; do
    sleep "$WATCHDOG_POLL_SECONDS"
    if ! health_check; then
      HEALTH_REASON="$("$PYTHON_BIN" - <<'PY' "$HEALTH_STATE_PATH"
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
        "$PYTHON_BIN" scripts/quant_notify_runtime_event.py unhealthy "$OUTPUT_BASE" "child_pid=$CHILD_PID" "reason=$HEALTH_REASON" >>"$SUPERVISOR_LOG" 2>&1 || true
      fi
      kill "$CHILD_PID" 2>/dev/null || true
      wait "$CHILD_PID" 2>/dev/null || true
      break
    fi
  done
  CHILD_EXIT_CODE=0
  wait "$CHILD_PID" 2>/dev/null || CHILD_EXIT_CODE=$?
  printf '[SUPERVISOR] child exited, restarting in %ss at %s\n' "$RESTART_SLEEP_SECONDS" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >>"$SUPERVISOR_LOG"
  if [ "$QUANT_TELEGRAM_NOTIFICATIONS" = "1" ]; then
    "$PYTHON_BIN" scripts/quant_notify_runtime_event.py exited "$OUTPUT_BASE" "child_pid=$CHILD_PID" "exit_code=$CHILD_EXIT_CODE" >>"$SUPERVISOR_LOG" 2>&1 || true
  fi
  sleep "$RESTART_SLEEP_SECONDS"
done
