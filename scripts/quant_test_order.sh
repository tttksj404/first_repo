#!/bin/sh
set -eu

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <fixture-json> [output-summary-json]" >&2
  exit 1
fi

FIXTURE="$1"
OUTPUT="${2:-output/paper-live-test-order/latest/summary.json}"

cd "$(dirname "$0")/.."
python3 -m quant_binance.runtime --mode paper-live-test-order --fixture "$FIXTURE" --output "$OUTPUT"
