#!/bin/sh
set -eu

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <paper-live-fixture-json> [output-report-json]" >&2
  exit 1
fi

FIXTURE="$1"
OUTPUT="${2:-}"
export STRATEGY_PROFILE="${STRATEGY_PROFILE:-active}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

if [ -n "$OUTPUT" ]; then
  sh "$SCRIPT_DIR/quant_python.sh" -m quant_binance.compare --fixture "$FIXTURE" --output "$OUTPUT"
else
  sh "$SCRIPT_DIR/quant_python.sh" -m quant_binance.compare --fixture "$FIXTURE"
fi
