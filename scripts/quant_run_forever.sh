#!/bin/sh
set -eu

OUTPUT_BASE="${1:-quant_runtime}"
export STRATEGY_PROFILE="${STRATEGY_PROFILE:-active}"
export STRATEGY_OVERRIDE_PATH="${STRATEGY_OVERRIDE_PATH:-$OUTPUT_BASE/artifacts/strategy_override.approved.json}"
export MACRO_INPUTS_PATH="${MACRO_INPUTS_PATH:-$OUTPUT_BASE/artifacts/news_macro_inputs.json}"

cd "$(dirname "$0")/.."
python3 -m quant_binance.runtime \
  --mode live-paper-daemon \
  --exchange "${EXCHANGE:-bitget}" \
  --output-base "$OUTPUT_BASE" \
  --max-retries 999999 \
  --insecure-ssl
