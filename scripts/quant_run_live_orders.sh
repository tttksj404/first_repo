#!/bin/sh
set -eu

OUTPUT_BASE="${1:-quant_runtime}"
export STRATEGY_PROFILE="${STRATEGY_PROFILE:-active}"
export STRATEGY_OVERRIDE_PATH="${STRATEGY_OVERRIDE_PATH:-$OUTPUT_BASE/artifacts/strategy_override.approved.json}"

cd "$(dirname "$0")/.."
PY_BIN="${PY_BIN:-python3}"
if ! command -v "$PY_BIN" >/dev/null 2>&1 || ! "$PY_BIN" -V >/dev/null 2>&1; then
  if command -v python >/dev/null 2>&1 && python -V >/dev/null 2>&1; then
    PY_BIN="python"
  elif [ -x "/c/Python314/python.exe" ] && /c/Python314/python.exe -V >/dev/null 2>&1; then
    PY_BIN="/c/Python314/python.exe"
  else
    echo "Python runtime not found or not executable (python3/python)." >&2
    exit 1
  fi
fi

"$PY_BIN" -m quant_binance.runtime \
  --mode live-auto-trade-daemon \
  --exchange "${EXCHANGE:-bitget}" \
  --output-base "$OUTPUT_BASE" \
  --max-retries 999999 \
  --insecure-ssl \
  --ack-live-risk I_UNDERSTAND_LIVE_TRADING
