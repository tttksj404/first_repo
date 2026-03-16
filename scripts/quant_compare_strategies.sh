#!/bin/sh
set -eu

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <paper-live-fixture-json> [output-report-json]" >&2
  exit 1
fi

FIXTURE="$1"
OUTPUT="${2:-}"
export STRATEGY_PROFILE="${STRATEGY_PROFILE:-active}"

cd "$(dirname "$0")/.."

if [ -n "$OUTPUT" ]; then
  python3 -m quant_binance.compare --fixture "$FIXTURE" --output "$OUTPUT"
else
  python3 -m quant_binance.compare --fixture "$FIXTURE"
fi
