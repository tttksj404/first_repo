#!/bin/sh
set -eu

OUTPUT_BASE="${1:-quant_runtime_paper50}"
REPO_ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p "$OUTPUT_BASE" scripts

# Keep real live-auto paths fail-closed while this read-only paper monitor runs.
printf 'stop\n' > scripts/_supervisor_stop
printf 'stop\n' > scripts/_safety_guardian_stop

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

exec "${PYTHON_BIN:-python3}" -m quant_binance.runtime \
  --mode live-paper-daemon \
  --exchange bitget \
  --output-base "$OUTPUT_BASE" \
  --max-retries 999999 \
  --sync-interval-seconds 60 \
  --insecure-ssl \
  >> "$OUTPUT_BASE/_paper50.out.log" \
  2>> "$OUTPUT_BASE/_paper50.err.log"
