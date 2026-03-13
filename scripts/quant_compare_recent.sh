#!/bin/sh
set -eu

export STRATEGY_PROFILE="${STRATEGY_PROFILE:-active}"

cd "$(dirname "$0")/.."
python3 -m quant_binance.compare_recent "$@"
