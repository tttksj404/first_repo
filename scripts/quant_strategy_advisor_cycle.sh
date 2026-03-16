#!/bin/sh
set -eu

BASE_DIR="${1:-quant_runtime}"
PROVIDER="${2:-codex}"
MODE="${3:-advisor}"
SEND_FLAG="${4:---send-telegram}"

cd "$(dirname "$0")/.."

python3 -m quant_binance.report_macro_event_calendar --output "$BASE_DIR/artifacts/official_macro_events.json"
python3 -m quant_binance.report_performance --base-dir "$BASE_DIR" >/dev/null
python3 -m quant_binance.report_validation --base-dir "$BASE_DIR" >/dev/null
python3 -m quant_binance.report_execution_quality --base-dir "$BASE_DIR" >/dev/null

MACRO_STRATEGY_EVENTS_PATH="${MACRO_STRATEGY_EVENTS_PATH:-$BASE_DIR/artifacts/official_macro_events.json}" \
python3 -m quant_binance.report_strategy_advisor \
  --base-dir "$BASE_DIR" \
  --provider "$PROVIDER" \
  --mode "$MODE" \
  $SEND_FLAG
