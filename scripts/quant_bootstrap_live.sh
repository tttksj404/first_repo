#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-live-auto-trade-daemon}"
OUTPUT_BASE="${2:-quant_runtime}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f ".env" ]]; then
  if [[ -f "env.example" ]]; then
    cp env.example .env
    echo "[BOOT] .env was missing, copied from env.example."
    echo "[BOOT] Fill real API keys in .env and run again."
    exit 1
  fi
  echo "[BOOT] .env is missing and env.example was not found."
  exit 1
fi

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "[BOOT] python is not installed."
  exit 1
fi

if [[ ! -d ".venv" ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
if [[ ! -x "$VENV_PYTHON" && -x "$ROOT_DIR/.venv/Scripts/python.exe" ]]; then
  VENV_PYTHON="$ROOT_DIR/.venv/Scripts/python.exe"
fi
if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "[BOOT] venv python not found at $VENV_PYTHON"
  exit 1
fi

"$VENV_PYTHON" -m pip install --upgrade pip >/dev/null
"$VENV_PYTHON" -m pip install -r requirements-live.txt >/dev/null

required_live_vars=("BITGET_API_KEY" "BITGET_API_SECRET" "BITGET_API_PASSPHRASE")
if [[ "$MODE" == "live-auto-trade-daemon" ]]; then
  for var_name in "${required_live_vars[@]}"; do
    if ! grep -Eq "^[[:space:]]*${var_name}[[:space:]]*=[[:space:]]*[^[:space:]#].*$" .env; then
      echo "[BOOT] Missing required ${var_name} in .env"
      exit 1
    fi
    raw_value="$(grep -E "^[[:space:]]*${var_name}[[:space:]]*=" .env | tail -n1 | sed -E "s/^[^=]+=//" | sed -E "s/^[[:space:]]*['\\\"]?|['\\\"]?[[:space:]]*$//g" | xargs)"
    lower_value="$(printf '%s' "$raw_value" | tr '[:upper:]' '[:lower:]')"
    if [[ "$lower_value" == your_* || "$lower_value" == *change_me* || "$lower_value" == *placeholder* ]]; then
      echo "[BOOT] ${var_name} still looks like a placeholder value."
      exit 1
    fi
  done
fi

if ! grep -Eq "^[[:space:]]*BITGET_MARGIN_MODE[[:space:]]*=[[:space:]]*(crossed|isolated)[[:space:]]*$" .env; then
  echo "[BOOT] BITGET_MARGIN_MODE not set, defaulting process env to isolated."
  export BITGET_MARGIN_MODE="isolated"
fi

export EXCHANGE="${EXCHANGE:-bitget}"
SYNC_INTERVAL_SECONDS="${SYNC_INTERVAL_SECONDS:-60}"
EQUITY_USD="${EQUITY_USD:-53}"
MAX_RETRIES="${MAX_RETRIES:-999999}"

"$VENV_PYTHON" -m quant_binance.runtime --mode env-check --exchange "${EXCHANGE}" || exit 1

if [[ "$MODE" == "env-check" ]]; then
  exit 0
fi

if [[ "$MODE" == "live-paper-daemon" ]]; then
  exec "$VENV_PYTHON" -m quant_binance.runtime \
    --mode live-paper-daemon \
    --exchange "${EXCHANGE}" \
    --output-base "${OUTPUT_BASE}" \
    --max-retries "${MAX_RETRIES}" \
    --sync-interval-seconds "${SYNC_INTERVAL_SECONDS}" \
    --insecure-ssl
fi

if [[ "$MODE" == "live-auto-trade-daemon" ]]; then
  exec "$VENV_PYTHON" -m quant_binance.runtime \
    --mode live-auto-trade-daemon \
    --exchange "${EXCHANGE}" \
    --output-base "${OUTPUT_BASE}" \
    --max-retries "${MAX_RETRIES}" \
    --sync-interval-seconds "${SYNC_INTERVAL_SECONDS}" \
    --equity-usd "${EQUITY_USD}" \
    --insecure-ssl \
    --ack-live-risk I_UNDERSTAND_LIVE_TRADING
fi

echo "[BOOT] Unsupported mode: ${MODE}"
echo "[BOOT] Supported: env-check | live-paper-daemon | live-auto-trade-daemon"
exit 1
