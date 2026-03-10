#!/bin/sh
set -eu

OUTPUT_BASE="${1:-quant_runtime}"
export STRATEGY_PROFILE="${STRATEGY_PROFILE:-active}"

cd "$(dirname "$0")/.."
python3 -m quant_binance.runtime \
  --mode live-auto-trade-daemon \
  --output-base "$OUTPUT_BASE" \
  --max-retries 999999 \
  --insecure-ssl \
  --ack-live-risk I_UNDERSTAND_LIVE_TRADING
