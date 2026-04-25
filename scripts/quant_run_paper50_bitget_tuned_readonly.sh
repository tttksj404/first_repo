#!/bin/sh
set -eu

OUTPUT_BASE="${1:-quant_runtime_paper50_bitget_tuned}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

TUNED_FILTERS="quant_runtime_paper50/bitget_overlay_tuning/paper50_multi_symbol_filters.bitget_tuned.json"
if [ ! -f "$TUNED_FILTERS" ]; then
  sh "$SCRIPT_DIR/quant_python.sh" "$SCRIPT_DIR/quant_bitget_overlay_tuner.py" --output-dir quant_runtime_paper50/bitget_overlay_tuning
fi

mkdir -p "$OUTPUT_BASE"

export QUANT_READ_ONLY_PAPER_MODE=1
export QUANT_PAPER_VERIFY_EQUITY_USD=50
export QUANT_PAPER_VERIFY_USE_CAPPED_ENTRY=1
export QUANT_PAPER_VERIFY_STOP_ON_KILL_SWITCH=0
export QUANT_BYPASS_POLICY_GUARDRAILS=1
export QUANT_BINANCE_ALLOW_FILE_RUNTIME_OVERRIDES=0
export STRATEGY_OVERRIDE_PATH="$TUNED_FILTERS"
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
