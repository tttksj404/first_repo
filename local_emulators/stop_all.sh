#!/bin/bash
# Stop all local emulators
for S in g405 g406 g802 g902 g902_session g904; do
  PATTERN="${S}_emulator.py"
  [ "$S" = "g902_session" ] && PATTERN="g902_session_emulator.py"
  PIDS=$(pgrep -f "$PATTERN")
  if [ -n "$PIDS" ]; then
    echo "[$S] killing PIDs: $PIDS"
    kill $PIDS 2>/dev/null
  else
    echo "[$S] not running"
  fi
done
sleep 2
echo ""
echo "=== verify ==="
pgrep -af "g(405|406|802)_emulator.py" || echo "(none)"
