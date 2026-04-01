#!/bin/bash
# 전략 자동 개선 루프 — 6시간마다 실행
# crontab: 47 1,7,13,19 * * * /Users/tttksj/first_repo/scripts/quant_autotuner_cycle.sh >> quant_runtime/autotuner.log 2>&1

set -uo pipefail
REPO="/Users/tttksj/first_repo"
RUNTIME="$REPO/quant_runtime"
PYTHON="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S %Z')

echo "============================================"
echo "[AUTOTUNER] $TIMESTAMP"
echo "============================================"

# Pre-check: daemon must be healthy
STATUS=$($PYTHON -c "import json; d=json.load(open('$RUNTIME/live_supervisor_health.json')); print(d.get('status','unknown'))" 2>/dev/null || echo "unknown")
if [ "$STATUS" != "healthy" ]; then
    echo "[AUTOTUNER] Skipped: daemon not healthy (status=$STATUS)"
    exit 0
fi

cd "$REPO"

# Auto-detect: dry-run until 50+ valid trades accumulated
VALID_TRADES=$($PYTHON -c "
import json
from pathlib import Path
trades = []
for f in Path('$RUNTIME/output/paper-live-shell').rglob('logs/closed_trades.jsonl'):
    for line in f.open():
        try:
            t = json.loads(line)
            score = float(t.get('entry_predictability_score',0) or t.get('latest_predictability_score',0) or 0)
            ret = abs(float(t.get('realized_return_bps_estimate',0) or 0))
            if score > 0 and ret >= 0.01:
                trades.append(1)
        except: pass
print(len(trades))
" 2>/dev/null || echo "0")

if [ "$VALID_TRADES" -ge 50 ]; then
    echo "[AUTOTUNER] valid_trades=$VALID_TRADES >= 50: LIVE mode"
    $PYTHON -m quant_binance.autotuner.analyzer \
        --base-dir "$RUNTIME" \
        2>&1
else
    echo "[AUTOTUNER] valid_trades=$VALID_TRADES < 50: dry-run mode (waiting for data)"
    $PYTHON -m quant_binance.autotuner.analyzer \
        --base-dir "$RUNTIME" \
        --dry-run \
        2>&1
fi

echo "[AUTOTUNER] Cycle complete"
echo ""
