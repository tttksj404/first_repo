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

# Run analysis — dry-run for safety (remove --dry-run after 1 week validation)
$PYTHON -m quant_binance.autotuner.analyzer \
    --base-dir "$RUNTIME" \
    --dry-run \
    2>&1

echo "[AUTOTUNER] Cycle complete"
echo ""
