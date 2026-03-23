#!/bin/sh
set -eu

HOST_PYTHON_DEFAULT="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
PATH="/Library/Frameworks/Python.framework/Versions/3.14/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
export PATH
if [ -x "$HOST_PYTHON_DEFAULT" ]; then
  PYTHON_BIN="$HOST_PYTHON_DEFAULT"
elif [ -x /usr/bin/python3 ]; then
  PYTHON_BIN="/usr/bin/python3"
else
  printf '[BOOT] fixed python bootstrap failed in %s at %s PATH=%s\n' "$0" "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$PATH" >&2
  exit 1
fi
export PYTHON_BIN

OUTPUT_BASE="${1:-quant_runtime}"
export STRATEGY_PROFILE="${STRATEGY_PROFILE:-active}"
export STRATEGY_OVERRIDE_PATH="${STRATEGY_OVERRIDE_PATH:-$OUTPUT_BASE/artifacts/strategy_override.approved.json}"
export MACRO_INPUTS_PATH="${MACRO_INPUTS_PATH:-$OUTPUT_BASE/artifacts/news_macro_inputs.json}"

cd "$(dirname "$0")/.."
"$PYTHON_BIN" -m quant_binance.runtime \
  --mode live-paper-daemon \
  --exchange "${EXCHANGE:-bitget}" \
  --output-base "$OUTPUT_BASE" \
  --max-retries 999999 \
  --insecure-ssl
