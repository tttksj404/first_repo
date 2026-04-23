#!/bin/sh
set -eu

WORKDIR="${1:-quant_runtime}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"
sh "$SCRIPT_DIR/quant_python.sh" - <<'PY' "$WORKDIR"
from quant_binance.bootstrap import initialize_workspace
import sys

layout = initialize_workspace(sys.argv[1])
print(layout.root)
PY
