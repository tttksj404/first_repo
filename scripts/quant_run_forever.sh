#!/bin/sh
set -eu

resolve_python_bin() {
  if [ -n "${PYTHON_BIN:-}" ] && [ -x "${PYTHON_BIN}" ]; then
    printf '%s\n' "$PYTHON_BIN"
    return 0
  fi

  c1="$(command -v python3 2>/dev/null || true)"
  c2="$(command -v python 2>/dev/null || true)"
  for candidate in "$c1" "$c2" /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3
  do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  printf '[BOOT] python resolver failed in %s at %s\n' "$0" "$(date '+%Y-%m-%d %H:%M:%S %Z')" >&2
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
