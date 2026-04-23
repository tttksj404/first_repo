#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"
sh "$SCRIPT_DIR/quant_python.sh" -m quant_binance.runtime --mode env-check --exchange "${EXCHANGE:-bitget}"
