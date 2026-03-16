#!/bin/sh
set -eu

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <start|start-live|status|report|stop|smoke|extract>" >&2
  exit 1
fi

CMD="$1"
ROOT="$(dirname "$0")/.."

cd "$ROOT"

case "$CMD" in
  start)
    exec sh scripts/quant_run_live_orders.sh quant_runtime
    ;;
  start-live)
    exec sh scripts/quant_run_live_orders.sh quant_runtime
    ;;
  status)
    exec sh scripts/quant_status.sh quant_runtime
    ;;
  report)
    exec sh scripts/quant_report.sh quant_runtime
    ;;
  stop)
    exec sh scripts/quant_stop.sh
    ;;
  smoke)
    exec sh scripts/quant_smoke_all.sh quant_runtime
    ;;
  extract)
    exec sh scripts/quant_extract_naver_openclaw.sh 'https://naver.me/IxKJQmc9' quant_runtime/artifacts/openclaw_naver_strategy.md
    ;;
  *)
    echo "unknown remote command: $CMD" >&2
    exit 1
    ;;
esac
