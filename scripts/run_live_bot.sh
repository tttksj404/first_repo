#!/bin/bash
# Phase 29 live bot runner.
#
# Usage:
#   ./scripts/run_live_bot.sh dry          # DRY-run (no real orders)
#   ./scripts/run_live_bot.sh live5        # LIVE micro: margin $5 (notional $50)
#   ./scripts/run_live_bot.sh live50       # LIVE full: margin $50 (notional $500)
#
# 안전장치:
#   - SIGINT/SIGTERM → 봇이 자동으로 포지션 시장가 청산 + 모든 conditional order 취소
#   - SL=-30% / TP=+500%은 진입 즉시 거래소에 등록 → 봇이 죽어도 자동 처리
#
# 긴급 정지:
#   kill -TERM $(cat quant_runtime/live_bot.pid)
#

set -e
cd "$(dirname "$0")/.."

mode="${1:-dry}"
pidfile="quant_runtime/live_bot.pid"
mkdir -p quant_runtime

# load only BITGET_* and LIVE_BOT_* from .env (skip messy lines)
if [ -f .env ]; then
    while IFS= read -r line; do
        case "$line" in
            BITGET_*=*|LIVE_BOT_*=*)
                export "$line"
                ;;
        esac
    done < .env
fi

case "$mode" in
    dry)
        echo "=== DRY-RUN mode (no real orders) ==="
        unset BITGET_LIVE
        export LIVE_BOT_MARGIN=50
        ;;
    live5)
        echo "=== LIVE MICRO mode: margin \$5 (notional \$50) ==="
        if [ -z "$BITGET_API_KEY" ]; then
            echo "ERROR: BITGET_API_KEY not set in .env"
            exit 1
        fi
        export BITGET_LIVE=1
        export LIVE_BOT_MARGIN=5
        echo "  ⚠️  실거래 모드. Ctrl+C 또는 'kill -TERM \$(cat $pidfile)' 로 안전 종료."
        echo
        read -p "  계속하려면 Enter, 취소는 Ctrl+C: "
        ;;
    live50)
        echo "=== LIVE FULL mode: margin \$50 (notional \$500) ==="
        if [ -z "$BITGET_API_KEY" ]; then
            echo "ERROR: BITGET_API_KEY not set in .env"
            exit 1
        fi
        export BITGET_LIVE=1
        export LIVE_BOT_MARGIN=50
        echo "  ⚠️  실거래 풀모드. Ctrl+C 또는 'kill -TERM \$(cat $pidfile)' 로 안전 종료."
        echo "  ⚠️  최대 손실/trade: \$15 (SL=-30% × margin \$50)"
        echo
        read -p "  계속하려면 'YES' 입력 후 Enter (그 외엔 취소): " confirm
        if [ "$confirm" != "YES" ]; then
            echo "취소됨."
            exit 0
        fi
        ;;
    *)
        echo "Usage: $0 {dry|live5|live50}"
        exit 1
        ;;
esac

# already running?
if [ -f "$pidfile" ]; then
    oldpid=$(cat "$pidfile")
    if kill -0 "$oldpid" 2>/dev/null; then
        echo "ERROR: live bot already running (PID $oldpid). Stop it first:"
        echo "  kill -TERM $oldpid"
        exit 1
    fi
fi

# launch
nohup python3 scripts/quant_phase29_live_bot.py \
    > quant_runtime/live_bot.out 2>&1 &
echo $! > "$pidfile"
sleep 2

if kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "✅ 봇 시작됨 PID=$(cat "$pidfile")"
    echo "  로그: tail -f quant_runtime/live_bot.out"
    echo "  이벤트: tail -f quant_runtime/live_bot_log.jsonl"
    echo "  상태: cat quant_runtime/live_bot_state.json | jq"
    echo "  안전 종료: kill -TERM \$(cat $pidfile)"
else
    echo "❌ 봇 시작 실패. 로그 확인:"
    tail -20 quant_runtime/live_bot.out
    rm -f "$pidfile"
    exit 1
fi
