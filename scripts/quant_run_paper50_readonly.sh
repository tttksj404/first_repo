#!/bin/sh
set -eu

OUTPUT_BASE="${1:-quant_runtime_paper50}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p "$OUTPUT_BASE" scripts

# Optional fail-closed mode for operators who intentionally want a paper-only
# session to block the live-auto wrappers. Keep the default side-effect free so
# read-only research probes never modify live stop sentinels.
if [ "${QUANT_PAPER50_BLOCK_LIVE_AUTO:-0}" = "1" ]; then
  printf 'stop\n' > scripts/_supervisor_stop
  printf 'stop\n' > scripts/_safety_guardian_stop
fi

rotate_if_large() {
  path="$1"
  max_bytes="${2:-52428800}"
  if [ -f "$path" ]; then
    size="$(wc -c < "$path" | tr -d ' ')"
    if [ "${size:-0}" -ge "$max_bytes" ]; then
      mv "$path" "$path.$(date -u +%Y%m%dT%H%M%SZ)"
    fi
  fi
}

rotate_if_large "$OUTPUT_BASE/_paper50.out.log"
rotate_if_large "$OUTPUT_BASE/_paper50.err.log"

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

MONITOR_PID_PATH="$OUTPUT_BASE/_monitor.pid"
EXISTING_MONITOR_PID="$(slot_pid "$MONITOR_PID_PATH")"
if ! pid_is_visible "$EXISTING_MONITOR_PID"; then
  nohup sh -c "
    printf '%s\n' \"\$\$\" > '$MONITOR_PID_PATH'
    exec sh '$SCRIPT_DIR/quant_python.sh' scripts/monitor_daemon_health.py '$OUTPUT_BASE'
  " >/dev/null 2>>"$OUTPUT_BASE/_paper50.err.log" &
fi

export QUANT_READ_ONLY_PAPER_MODE=1
export QUANT_PAPER_VERIFY_EQUITY_USD=50
export QUANT_PAPER_VERIFY_USE_CAPPED_ENTRY=1
export QUANT_PAPER_VERIFY_STOP_ON_KILL_SWITCH=0
export QUANT_BYPASS_POLICY_GUARDRAILS=1
export QUANT_BINANCE_ALLOW_FILE_RUNTIME_OVERRIDES=0
export STRATEGY_OVERRIDE_PATH="$OUTPUT_BASE/paper50_multi_symbol_filters.json"
export STRATEGY_PROFILE=live-ultra-aggressive
export UNIVERSE_SYMBOLS=PEPEUSDT,DOGEUSDT,XRPUSDT,SOLUSDT,ETHUSDT,BTCUSDT
export QUANT_TELEGRAM_NOTIFICATIONS=0
export SELF_HEAL_MAX_STALL_RESTARTS=999
export NO_PROXY=*
export no_proxy=*
export HTTP_PROXY=
export HTTPS_PROXY=
export ALL_PROXY=
export GIT_HTTP_PROXY=
export GIT_HTTPS_PROXY=
export http_proxy=
export https_proxy=
export all_proxy=

exec sh "$SCRIPT_DIR/quant_python.sh" -m quant_binance.runtime \
  --mode live-paper-daemon \
  --exchange bitget \
  --output-base "$OUTPUT_BASE" \
  --max-retries 999999 \
  --sync-interval-seconds 60 \
  --insecure-ssl \
  >> "$OUTPUT_BASE/_paper50.out.log" \
  2>> "$OUTPUT_BASE/_paper50.err.log"
