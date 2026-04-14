#!/bin/sh
set -eu

if [ "$#" -lt 2 ]; then
  echo "usage: $0 <provider> <status-check|capital-report|latest-run-review|strategy-review> [model]" >&2
  exit 1
fi

PROVIDER="$1"
TASK="$2"
MODEL="${3:-}"
ROOT="$(dirname "$0")/.."

cd "$ROOT"

if [ -n "$MODEL" ]; then
  python3 -m quant_binance.ai_task_runner --provider "$PROVIDER" --task "$TASK" --root "$ROOT" --model "$MODEL"
else
  python3 -m quant_binance.ai_task_runner --provider "$PROVIDER" --task "$TASK" --root "$ROOT"
fi
