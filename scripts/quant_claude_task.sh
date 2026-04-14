#!/bin/sh
set -eu

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <status-check|capital-report|latest-run-review|strategy-review> [model]" >&2
  exit 1
fi

TASK="$1"
MODEL="${2:-}"

exec sh "$(dirname "$0")/quant_model_task.sh" claude "$TASK" "$MODEL"
