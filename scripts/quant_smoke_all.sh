#!/bin/sh
set -eu

BASE_DIR="${1:-quant_runtime}"
ROOT="$(dirname "$0")/.."
EXCHANGE_ID="${EXCHANGE:-bitget}"

cd "$ROOT"

sh scripts/quant_init_workspace.sh "$BASE_DIR" >/dev/null
python3 -m quant_binance.runtime --mode env-check --exchange "$EXCHANGE_ID"
python3 -m quant_binance.runtime \
  --mode replay \
  --fixture quant_binance/examples/replay_fixture.sample.json \
  --output "$BASE_DIR/output/replay/latest/summary.json"
python3 -m quant_binance.runtime \
  --mode paper-live \
  --fixture quant_binance/examples/paper_live_fixture.sample.json \
  --output "$BASE_DIR/output/paper-live/latest/summary.json"
python3 -m quant_binance.runtime \
  --mode paper-live-shell \
  --fixture quant_binance/examples/paper_live_fixture.sample.json \
  --output "$BASE_DIR/output/paper-live-shell/latest/summary.json"

if [ "$EXCHANGE_ID" = "bitget" ]; then
  python3 -m quant_binance.runtime \
    --mode paper-live-test-order \
    --exchange "$EXCHANGE_ID" \
    --fixture quant_binance/examples/paper_live_fixture.sample.json \
    --output "$BASE_DIR/output/paper-live-test-order/latest/summary.json"
elif [ "${BINANCE_API_KEY:-}" != "" ] && [ "${BINANCE_API_SECRET:-}" != "" ]; then
  python3 -m quant_binance.runtime \
    --mode paper-live-test-order \
    --exchange "$EXCHANGE_ID" \
    --fixture quant_binance/examples/paper_live_fixture.sample.json \
    --output "$BASE_DIR/output/paper-live-test-order/latest/summary.json"
fi
