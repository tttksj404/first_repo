#!/usr/bin/env bash
# Paper bot watchdog: PID 죽으면 자동 재시작
# 사용: nohup bash scripts/quant_phase23_watchdog.sh > quant_runtime/watchdog.log 2>&1 &
# 정지: kill $(cat quant_runtime/watchdog.pid)

set -u
ROOT="/Users/tttksj/first_repo"
PID_FILE="$ROOT/quant_runtime/paper_bot.pid"
WATCHDOG_PID_FILE="$ROOT/quant_runtime/watchdog.pid"
BOT_SCRIPT="$ROOT/scripts/quant_phase23_paper_bot.py"
STDOUT_LOG="$ROOT/quant_runtime/paper_bot_stdout.log"
WD_LOG="$ROOT/quant_runtime/watchdog.log"
CHECK_INTERVAL=30   # seconds between checks
MAX_RESTARTS=20     # safety: cap restarts in single watchdog session
RESTART_BACKOFF=10  # wait this long after a crash before restarting

# record watchdog pid
echo "$$" > "$WATCHDOG_PID_FILE"

log() {
  echo "[$(date -u '+%F %T')] $*" >> "$WD_LOG"
}

trap 'log "watchdog received signal, exiting"; exit 0' INT TERM

restart_bot() {
  log "starting paper bot..."
  cd "$ROOT" || exit 1
  nohup python3 "$BOT_SCRIPT" >> "$STDOUT_LOG" 2>&1 &
  local new_pid=$!
  echo "$new_pid" > "$PID_FILE"
  log "started paper bot pid=$new_pid"
}

restarts=0
log "watchdog start (pid=$$, check every ${CHECK_INTERVAL}s)"

while true; do
  alive=0
  if [ -f "$PID_FILE" ]; then
    bot_pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
    if [ -n "$bot_pid" ] && kill -0 "$bot_pid" 2>/dev/null; then
      alive=1
    fi
  fi

  if [ "$alive" = "0" ]; then
    if [ "$restarts" -ge "$MAX_RESTARTS" ]; then
      log "max restarts ($MAX_RESTARTS) hit — watchdog quitting (manual intervention needed)"
      exit 1
    fi
    log "bot DEAD (restart #$((restarts+1))), backing off ${RESTART_BACKOFF}s"
    sleep "$RESTART_BACKOFF"
    restart_bot
    restarts=$((restarts+1))
  fi

  sleep "$CHECK_INTERVAL"
done
