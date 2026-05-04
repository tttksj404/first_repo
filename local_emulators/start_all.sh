#!/bin/bash
# Start all local emulators (idempotent — won't double-start)
ROOT="$(cd "$(dirname "$0")" && pwd)"
for S in g405 g406 g802 g902 g902_session g904; do
  SCRIPT="${S}_emulator.py"
  [ "$S" = "g902_session" ] && SCRIPT="g902_session_emulator.py"
  if pgrep -f "$SCRIPT" > /dev/null; then
    echo "[$S] already running"
    continue
  fi
  cd "$ROOT/$S"
  nohup python "$SCRIPT" > runtime/stdout.log 2> runtime/stderr.log &
  echo "[$S] started PID=$!"
  cd "$ROOT"
done
sleep 3
echo ""
bash "$ROOT/status.sh"
