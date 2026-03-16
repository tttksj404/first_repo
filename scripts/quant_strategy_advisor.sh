#!/bin/sh
set -eu

PROVIDER="${1:-codex}"
BASE_DIR="${2:-quant_runtime}"
MODE="${3:-advisor}"
SEND_FLAG="${4:-}"

ARGS="--base-dir $BASE_DIR --provider $PROVIDER --mode $MODE"
if [ "$SEND_FLAG" = "--send-telegram" ]; then
  ARGS="$ARGS --send-telegram"
fi

cd "$(dirname "$0")/.."
python3 -m quant_binance.report_strategy_advisor $ARGS
