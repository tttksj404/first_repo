#!/bin/sh
set -eu

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <fixture-json> [output-summary-json]" >&2
  exit 1
fi

FIXTURE="$1"
OUTPUT="${2:-output/paper-live-test-order/latest/summary.json}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"
sh "$SCRIPT_DIR/quant_python.sh" -m quant_binance.runtime --mode paper-live-test-order --exchange "${EXCHANGE:-bitget}" --fixture "$FIXTURE" --output "$OUTPUT"
