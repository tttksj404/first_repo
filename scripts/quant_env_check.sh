#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
python3 -m quant_binance.runtime --mode env-check
