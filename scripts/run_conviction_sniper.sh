#!/usr/bin/env bash
# run_conviction_sniper.sh — Auto-restart wrapper for conviction-sniper paper daemon
# Restarts on crash with exponential backoff (max 60s)

set -euo pipefail

REPO_DIR="/Users/tttksj/first_repo"
LOG_DIR="$REPO_DIR/quant_runtime/output/conviction-sniper-v3"
PIDFILE="$LOG_DIR/daemon.pid"
MAX_BACKOFF=60
backoff=2

mkdir -p "$LOG_DIR"
echo $$ > "$PIDFILE"

cleanup() {
    rm -f "$PIDFILE"
    exit 0
}
trap cleanup SIGTERM SIGINT

while true; do
    echo "[WRAPPER] $(date -u +%Y-%m-%dT%H:%M:%SZ) Starting conviction-sniper daemon (backoff=${backoff}s)" >> "$LOG_DIR/daemon.log"

    cd "$REPO_DIR"
    env STRATEGY_PROFILE=conviction-sniper \
        UNIVERSE_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT \
        python3 -m quant_binance.runtime \
            --mode live-paper-daemon \
            --config quant_binance/config.example.json \
            --output-base "$LOG_DIR" \
            --exchange bitget \
            --insecure-ssl \
            --sync-interval-seconds 60 \
        >> "$LOG_DIR/daemon.log" 2>&1

    exit_code=$?
    echo "[WRAPPER] $(date -u +%Y-%m-%dT%H:%M:%SZ) Daemon exited with code $exit_code, restarting in ${backoff}s..." >> "$LOG_DIR/daemon.log"

    sleep "$backoff"
    # Exponential backoff, cap at MAX_BACKOFF
    backoff=$(( backoff * 2 ))
    if [ "$backoff" -gt "$MAX_BACKOFF" ]; then
        backoff=$MAX_BACKOFF
    fi

    # Reset backoff if daemon ran for more than 5 minutes (was healthy)
    # (checked by comparing log timestamps - simplified: always reset after max)
    if [ "$backoff" -ge "$MAX_BACKOFF" ]; then
        backoff=2
    fi
done
