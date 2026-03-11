#!/bin/sh
set -eu

BASE_DIR="${2:-quant_runtime}"
ACTION="${1:-report}"

cd "$(dirname "$0")/.."
case "$ACTION" in
  report)
    python3 -c "from quant_binance.promotion import build_strategy_proposal; import json; print(json.dumps(build_strategy_proposal(base_dir='$BASE_DIR'), indent=2, sort_keys=True))"
    ;;
  approve)
    python3 -c "from quant_binance.promotion import apply_strategy_proposal; import json; print(json.dumps(apply_strategy_proposal(base_dir='$BASE_DIR'), indent=2, sort_keys=True))"
    python3 -c "from quant_binance.promotion import cleanup_runtime_artifacts; import json; print(json.dumps(cleanup_runtime_artifacts(base_dir='$BASE_DIR'), indent=2, sort_keys=True))"
    ;;
  reject)
    python3 -c "from quant_binance.promotion import reject_strategy_proposal; import json; print(json.dumps(reject_strategy_proposal(base_dir='$BASE_DIR'), indent=2, sort_keys=True))"
    ;;
  *)
    echo "usage: sh scripts/quant_strategy_promotion.sh [report|approve|reject] [base_dir]" >&2
    exit 1
    ;;
esac
