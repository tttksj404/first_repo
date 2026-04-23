#!/bin/sh
set -eu

OUTPUT_BASE="${1:-quant_runtime}"

mkdir -p "$(dirname "$0")"
printf 'stop\n' >"$(dirname "$0")/_supervisor_stop"
printf 'stop\n' >"$(dirname "$0")/_safety_guardian_stop"

slot_pid() {
  slot_path="$1"
  awk 'NR == 1 { print $1; exit }' "$slot_path" 2>/dev/null || true
}

for pid_path in \
  "$OUTPUT_BASE/live_supervisor.pid" \
  "$OUTPUT_BASE/live_supervisor_watchdog.pid" \
  "$OUTPUT_BASE/live_supervisor.lock/pid"
do
  pid="$(slot_pid "$pid_path")"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
  fi
done

pkill -f 'quant_binance.runtime --mode live-auto-trade-daemon' || true
pkill -f 'quant_binance.runtime --mode live-paper-daemon' || true
pkill -f 'scripts/quant_live_watchdog.py' || true
pkill -f 'scripts/quant_run_live_orders.sh' || true

sleep 2

pkill -9 -f 'quant_binance.runtime --mode live-auto-trade-daemon' || true
pkill -9 -f 'quant_binance.runtime --mode live-paper-daemon' || true
pkill -9 -f 'scripts/quant_live_watchdog.py' || true
pkill -9 -f 'scripts/quant_run_live_orders.sh' || true

rm -f "$OUTPUT_BASE/live_supervisor.pid" "$OUTPUT_BASE/live_supervisor_watchdog.pid"
rm -rf "$OUTPUT_BASE/live_supervisor.lock"

echo "stopped"
