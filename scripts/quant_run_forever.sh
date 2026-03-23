#!/bin/sh
set -eu

HOST_PYTHON_DEFAULT="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
PATH="/Library/Frameworks/Python.framework/Versions/3.14/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
export PATH
if [ -z "${PYTHON_BIN:-}" ] && [ -x "$HOST_PYTHON_DEFAULT" ]; then
  PYTHON_BIN="$HOST_PYTHON_DEFAULT"
  export PYTHON_BIN
fi

resolve_python_bin() {
  if [ -n "${PYTHON_BIN:-}" ] && [ -x "${PYTHON_BIN}" ]; then
    printf '%s\n' "$PYTHON_BIN"
    return 0
  fi

  for candidate in /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3
  do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  printf '[BOOT] python resolver failed in %s at %s env_PYTHON_BIN=%s PATH=%s\n' "$0" "$(date '+%Y-%m-%d %H:%M:%S %Z')" "${PYTHON_BIN:-}" "$PATH" >&2
  exit 1
}

PYTHON_BIN="$(resolve_python_bin)"

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
