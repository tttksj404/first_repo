#!/bin/sh
set -eu

OUTPUT_BASE="${1:-quant_runtime}"

cd "$(dirname "$0")/.."
python3 -m quant_binance.runtime \
  --mode live-paper-daemon \
  --output-base "$OUTPUT_BASE" \
  --max-retries 999999 \
  --insecure-ssl
