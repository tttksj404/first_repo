#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

OUTPUT_DIR="${1:-quant_runtime/artifacts/optimization}"
ITERATIONS="${2:-16}"
SLEEP_SECONDS="${3:-1800}"
EXCHANGE_ID="${EXCHANGE:-bitget}"

i=0
while [ "$i" -lt "$ITERATIONS" ]; do
  python3 - <<'PY' "$OUTPUT_DIR" "$EXCHANGE_ID"
from quant_binance.execution.client_factory import build_exchange_rest_client
from quant_binance.optimization import run_sandbox_optimization
import sys

client = build_exchange_rest_client(
    exchange=sys.argv[2],
    allow_insecure_ssl=True,
    allow_missing_credentials=False,
)
path = run_sandbox_optimization(
    config_path="quant_binance/config.example.json",
    client=client,
    output_dir=sys.argv[1],
)
print(path)
PY
  i=$((i + 1))
  if [ "$i" -lt "$ITERATIONS" ]; then
    sleep "$SLEEP_SECONDS"
  fi
done
