#!/bin/sh
set -eu

BASE_DIR="${2:-quant_runtime}"
ACTION="${1:-report}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"
case "$ACTION" in
  report)
    sh "$SCRIPT_DIR/quant_python.sh" -c "from quant_binance.promotion import build_strategy_proposal; import json; print(json.dumps(build_strategy_proposal(base_dir='$BASE_DIR'), indent=2, sort_keys=True))"
    ;;
  approve)
    sh "$SCRIPT_DIR/quant_python.sh" -c "from quant_binance.promotion import apply_strategy_proposal; import json; print(json.dumps(apply_strategy_proposal(base_dir='$BASE_DIR'), indent=2, sort_keys=True))"
    sh "$SCRIPT_DIR/quant_python.sh" -c "from quant_binance.promotion import cleanup_runtime_artifacts; import json; print(json.dumps(cleanup_runtime_artifacts(base_dir='$BASE_DIR'), indent=2, sort_keys=True))"
    ;;
  reject)
    sh "$SCRIPT_DIR/quant_python.sh" -c "from quant_binance.promotion import reject_strategy_proposal; import json; print(json.dumps(reject_strategy_proposal(base_dir='$BASE_DIR'), indent=2, sort_keys=True))"
    ;;
  *)
    echo "usage: sh scripts/quant_strategy_promotion.sh [report|approve|reject] [base_dir]" >&2
    exit 1
    ;;
esac
