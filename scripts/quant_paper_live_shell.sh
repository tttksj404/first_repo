#!/bin/sh
set -eu

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <fixture-json> [output-summary-json]" >&2
  exit 1
fi

FIXTURE="$1"
OUTPUT="${2:-output/paper-live-shell/latest/summary.json}"
export STRATEGY_PROFILE="${STRATEGY_PROFILE:-active}"

cd "$(dirname "$0")/.."
python3 -m quant_binance.runtime --mode paper-live-shell --fixture "$FIXTURE" --output "$OUTPUT" --max-retries 3
