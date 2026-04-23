#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
exec sh "$SCRIPT_DIR/quant_python.sh" "$SCRIPT_DIR/quant_live_watchdog.py" "$@"
