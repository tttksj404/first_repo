#!/bin/sh
set -eu

BASE_DIR="${1:-quant_runtime}"
CONFIG_PATH="${2:-quant_binance/config.example.json}"
EXCHANGE_ID="${EXCHANGE:-bitget}"

cd "$(dirname "$0")/.."

python3 -m quant_binance.report_performance --base-dir "$BASE_DIR"
python3 -m quant_binance.report_validation --base-dir "$BASE_DIR"
python3 -m quant_binance.report_execution_quality --base-dir "$BASE_DIR"
python3 -m quant_binance.compare_recent --config "$CONFIG_PATH" --base-dir "$BASE_DIR"
python3 - <<'PY' "$BASE_DIR/artifacts/optimization" "$EXCHANGE_ID" "$CONFIG_PATH"
from quant_binance.execution.client_factory import build_exchange_rest_client
from quant_binance.optimization import run_sandbox_optimization
import sys

client = build_exchange_rest_client(
    exchange=sys.argv[2],
    allow_insecure_ssl=True,
    allow_missing_credentials=False,
)
path = run_sandbox_optimization(
    config_path=sys.argv[3],
    client=client,
    output_dir=sys.argv[1],
)
print(path)
PY
python3 -c "from quant_binance.promotion import build_strategy_proposal; import json; print(json.dumps(build_strategy_proposal(base_dir='$BASE_DIR'), indent=2, sort_keys=True))"
