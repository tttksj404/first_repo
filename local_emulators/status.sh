#!/bin/bash
# Show running local emulators (Windows-compatible)
ROOT="$(cd "$(dirname "$0")" && pwd)"
echo "=== local emulators @ $(date '+%H:%M:%S') ==="
echo ""

# Use powershell to list python processes with cmdline (cross-version)
PS_OUT=$(powershell -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" 2>\$null | Where-Object { \$_.CommandLine -like '*emulator*' } | ForEach-Object { '{0}|{1}|{2}' -f \$_.ProcessId, [math]::Round((Get-Process -Id \$_.ProcessId).WorkingSet64/1MB), \$_.CommandLine }" 2>/dev/null)

for S in g405 g406 g802 g902 g902_session g904; do
  PATTERN="${S}_emulator.py"
  [ "$S" = "g902_session" ] && PATTERN="g902_session_emulator.py"
  LINE=$(echo "$PS_OUT" | grep "$PATTERN" | head -1)
  if [ -n "$LINE" ]; then
    PID=$(echo "$LINE" | cut -d'|' -f1)
    MB=$(echo "$LINE" | cut -d'|' -f2)
    echo "[$S] PID=$PID  RUNNING  ${MB} MB"
  else
    echo "[$S] NOT RUNNING"
  fi
  if [ -f "$ROOT/$S/runtime/state.json" ]; then
    python -c "
import json
d = json.load(open(r'$ROOT/$S/runtime/state.json'))
op = d.get('open_positions', {})
print(f'   open: {len(op)}  closed: {d.get(\"closed_count\",0)}  W/L: {d.get(\"wins\",0)}/{d.get(\"losses\",0)}  cumPnL: \${d.get(\"cumulative_pnl_usd\",0):+.2f}')
print(f'   last cycle: {d.get(\"last_cycle\",\"?\")}')
" 2>/dev/null
  fi
  LOG="$ROOT/$S/runtime/emulator.log"
  if [ -f "$LOG" ]; then
    LAST=$(grep -E "HEARTBEAT|ENTER|EXIT" "$LOG" | tail -1)
    [ -n "$LAST" ] && echo "   $LAST"
  fi
  echo ""
done

echo "=== mem ==="
powershell -Command '$os = Get-CimInstance Win32_OperatingSystem; "Free: $([math]::Round($os.FreePhysicalMemory/1024)) MB / $([math]::Round($os.TotalVisibleMemorySize/1024)) MB"' 2>/dev/null
