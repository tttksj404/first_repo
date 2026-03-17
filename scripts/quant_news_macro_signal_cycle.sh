#!/bin/sh
set -eu

BASE_DIR="${1:-quant_runtime}"
SLEEP_SECONDS="${2:-900}"

cd "$(dirname "$0")/.."

while true; do
  python3 -m quant_binance.report_macro_event_calendar --output "$BASE_DIR/artifacts/official_macro_events.json" || true
  python3 -m quant_binance.report_news_macro_signal \
    --output "$BASE_DIR/artifacts/news_macro_signal.json" \
    --macro-output "$BASE_DIR/artifacts/news_macro_inputs.json" \
    --official-events "$BASE_DIR/artifacts/official_macro_events.json" \
    --state-output "$BASE_DIR/artifacts/news_macro_signal.state.json" || true
  sleep "$SLEEP_SECONDS"
done
