#!/bin/sh
set -eu

HOST_PYTHON_DEFAULT="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
PATH="/Library/Frameworks/Python.framework/Versions/3.14/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
export PATH
if [ -x "${PYTHON_BIN:-}" ]; then
  :
elif [ -x "$HOST_PYTHON_DEFAULT" ]; then
  PYTHON_BIN="$HOST_PYTHON_DEFAULT"
elif [ -x /usr/bin/python3 ]; then
  PYTHON_BIN="/usr/bin/python3"
elif PATH_PYTHON_BIN="$(command -v python3 2>/dev/null || true)" && [ -n "$PATH_PYTHON_BIN" ] && [ -x "$PATH_PYTHON_BIN" ]; then
  PYTHON_BIN="$PATH_PYTHON_BIN"
else
  printf '[BOOT] fixed python bootstrap failed in %s at %s PATH=%s\n' "$0" "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$PATH" >&2
  exit 1
fi
export PYTHON_BIN

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$PYTHON_BIN" "$SCRIPT_DIR/quant_live_watchdog.py" "$@"
