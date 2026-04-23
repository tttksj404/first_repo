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

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"
sh "$SCRIPT_DIR/quant_python.sh" -m quant_binance.report_strategy_advisor $ARGS
