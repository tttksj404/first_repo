#!/bin/sh
set -eu

BASE_DIR="${1:-quant_runtime}"
STATE_FILE="$(python3 - <<'PY' "$BASE_DIR"
from pathlib import Path
import sys
base = Path(sys.argv[1])
latest = base / 'output' / 'paper-live-shell' / 'latest' / 'summary.state.json'
paths = [p for p in base.rglob('summary.state.json') if p.exists()]
if latest.exists() and latest not in paths:
    paths.append(latest)
paths = sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)
print(paths[0] if paths else '')
PY
)"
SUMMARY_FILE=""

if [ -n "$STATE_FILE" ]; then
  RUN_DIR="$(dirname "$STATE_FILE")"
  if [ -f "$RUN_DIR/summary.json" ]; then
    SUMMARY_FILE="$RUN_DIR/summary.json"
  fi
fi

if [ -z "$SUMMARY_FILE" ]; then
  SUMMARY_FILE="$(python3 - <<'PY' "$BASE_DIR"
from pathlib import Path
import sys
base = Path(sys.argv[1])
latest = base / 'output' / 'paper-live-shell' / 'latest' / 'summary.json'
paths = [p for p in base.rglob('summary.json') if p.exists()]
if latest.exists() and latest not in paths:
    paths.append(latest)
paths = sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)
print(paths[0] if paths else '')
PY
)"
fi

if [ -z "$SUMMARY_FILE" ] || [ -z "$STATE_FILE" ]; then
  echo "no summary/state files found under $BASE_DIR"
  exit 1
fi

python3 - <<'PY' "$SUMMARY_FILE" "$STATE_FILE"
import json, sys
summary = json.load(open(sys.argv[1], encoding='utf-8'))
state = json.load(open(sys.argv[2], encoding='utf-8'))
print("summary_file:", sys.argv[1])
print("state_file:", sys.argv[2])
print("decision_count:", summary.get("decision_count"))
print("live_order_count:", summary.get("live_order_count"))
print("tested_order_count:", summary.get("tested_order_count"))
print("symbols:", summary.get("symbols"))
print("modes:", summary.get("modes"))
print("observe_only_symbols:", summary.get("observe_only_symbols"))
print("realized_pnl_usd_estimate:", summary.get("realized_pnl_usd_estimate"))
print("unrealized_pnl_usd_estimate:", summary.get("unrealized_pnl_usd_estimate"))
print("exit_reason_counts:", summary.get("exit_reason_counts"))
print("symbol_performance:", summary.get("symbol_performance"))
print("kill_switch:", summary.get("kill_switch"))
print("updated_at:", state.get("updated_at"))
print("heartbeat_count:", state.get("heartbeat_count"))
print("last_event_timestamp:", state.get("last_event_timestamp"))
print("last_decision_timestamp:", state.get("last_decision_timestamp"))
print("recent_decisions:", summary.get("recent_decisions"))
print("top_rejection_reasons:", summary.get("top_rejection_reasons"))
capital = summary.get("capital_report") or {}
if capital:
    print("spot_available_balance_usd:", capital.get("spot_available_balance_usd"))
    print("futures_available_balance_usd:", capital.get("futures_available_balance_usd"))
    print("can_trade_spot_any:", capital.get("can_trade_spot_any"))
    print("can_trade_futures_any:", capital.get("can_trade_futures_any"))
spot_positions = summary.get("open_spot_positions") or []
paper_futures_positions = summary.get("paper_open_futures_positions") or summary.get("open_futures_positions") or []
exchange_futures_positions = summary.get("exchange_live_futures_positions") or []
print("open_spot_positions:", spot_positions)
print("paper_open_futures_position_count:", summary.get("paper_open_futures_position_count", len(paper_futures_positions)))
print("paper_open_futures_positions:", paper_futures_positions)
print("exchange_live_futures_position_count:", summary.get("exchange_live_futures_position_count", len(exchange_futures_positions)))
print("exchange_live_futures_positions:", exchange_futures_positions)
print("futures_position_mismatch:", summary.get("futures_position_mismatch"))
print("futures_position_mismatch_details:", summary.get("futures_position_mismatch_details"))
print("open_futures_positions:", summary.get("open_futures_positions"))
print("live_positions:", summary.get("live_positions"))
if exchange_futures_positions:
    print("exchange_live_futures_positions_brief:")
    for item in exchange_futures_positions[:5]:
        margin = float(item.get("marginSize") or 0.0)
        unrealized = float(item.get("unrealizedPL") or 0.0)
        roe = (unrealized / margin * 100.0) if margin > 0 else 0.0
        print(
            {
                "symbol": item.get("symbol"),
                "holdSide": item.get("holdSide"),
                "unrealizedPL": unrealized,
                "roe_percent": round(roe, 2),
                "marginRatio": item.get("marginRatio"),
                "total": item.get("total"),
            }
        )
PY
