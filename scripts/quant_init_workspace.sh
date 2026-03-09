#!/bin/sh
set -eu

WORKDIR="${1:-quant_runtime}"

cd "$(dirname "$0")/.."
python3 - <<'PY' "$WORKDIR"
from quant_binance.bootstrap import initialize_workspace
import sys

layout = initialize_workspace(sys.argv[1])
print(layout.root)
PY
