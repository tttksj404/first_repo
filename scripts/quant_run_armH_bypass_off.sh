#!/bin/sh
set -eu
# Arm H: live-ultra-aggressive but with policy guardrails ENABLED (vs A which has them off)
# Tests whether policy guardrails meaningfully limit profit in this regime.

OUTPUT_BASE="${1:-quant_runtime_armH}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p "$OUTPUT_BASE"

export QUANT_READ_ONLY_PAPER_MODE=1
export QUANT_PAPER_VERIFY_EQUITY_USD=50
export QUANT_PAPER_VERIFY_USE_CAPPED_ENTRY=1
export QUANT_PAPER_VERIFY_STOP_ON_KILL_SWITCH=0
# DIFF FROM A: policy guardrails ON (A had =1)
export QUANT_BYPASS_POLICY_GUARDRAILS=0
export QUANT_BINANCE_ALLOW_FILE_RUNTIME_OVERRIDES=0
export STRATEGY_OVERRIDE_PATH="$OUTPUT_BASE/paper50_multi_symbol_filters.json"
export STRATEGY_PROFILE=live-ultra-aggressive
export UNIVERSE_SYMBOLS=PEPEUSDT,DOGEUSDT,XRPUSDT,SOLUSDT,ETHUSDT,BTCUSDT
export QUANT_TELEGRAM_NOTIFICATIONS=0
export QUANT_CROSS_COIN_GATE=1
export SELF_HEAL_MAX_STALL_RESTARTS=999
export NO_PROXY=*
export no_proxy=*
export HTTP_PROXY=
export HTTPS_PROXY=
export ALL_PROXY=

exec sh "$SCRIPT_DIR/quant_python.sh" -m quant_binance.runtime \
  --mode live-paper-daemon \
  --exchange bitget \
  --output-base "$OUTPUT_BASE" \
  --max-retries 999999 \
  --sync-interval-seconds 60 \
  --insecure-ssl \
  >> "$OUTPUT_BASE/_armH.out.log" \
  2>> "$OUTPUT_BASE/_armH.err.log"
