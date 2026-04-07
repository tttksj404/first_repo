#!/usr/bin/env bash
# dream_check.sh — SessionStart hook for auto-dream trigger
# Checks if memory consolidation should run based on time and session count.

MEMORY_DIR="$HOME/.claude/projects/-Users-tttksj-first-repo/memory"
DREAM_FILE="$MEMORY_DIR/last_dream.json"

# Ensure memory directory exists
mkdir -p "$MEMORY_DIR"

# If last_dream.json doesn't exist, create it and exit
if [ ! -f "$DREAM_FILE" ]; then
  cat > "$DREAM_FILE" << 'INIT'
{
  "last_dream_timestamp": "'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'",
  "sessions_since_dream": 1
}
INIT
  exit 0
fi

# Read current values
LAST_TS=$(python3 -c "
import json, sys
with open('$DREAM_FILE') as f:
    d = json.load(f)
print(d.get('last_dream_timestamp', ''))
" 2>/dev/null)

SESSIONS=$(python3 -c "
import json
with open('$DREAM_FILE') as f:
    d = json.load(f)
print(d.get('sessions_since_dream', 0))
" 2>/dev/null)

# Calculate hours since last dream
HOURS_ELAPSED=$(python3 -c "
from datetime import datetime, timezone
import sys
ts = '$LAST_TS'
if not ts:
    print(999)
    sys.exit(0)
try:
    # Handle both Z and +00:00 formats
    ts = ts.replace('Z', '+00:00')
    last = datetime.fromisoformat(ts)
    now = datetime.now(timezone.utc)
    diff = (now - last).total_seconds() / 3600
    print(f'{diff:.1f}')
except Exception:
    print(999)
" 2>/dev/null)

# Check if both conditions are met: 24h elapsed AND 5+ sessions
SHOULD_DREAM=$(python3 -c "
hours = float('$HOURS_ELAPSED')
sessions = int('$SESSIONS')
if hours >= 24 and sessions >= 5:
    print('yes')
else:
    print('no')
" 2>/dev/null)

if [ "$SHOULD_DREAM" = "yes" ]; then
  # Output JSON systemMessage to trigger auto-dream
  echo '{"systemMessage":"Auto-dream conditions met (24h+ elapsed, 5+ sessions). Please run the auto-dream skill now to consolidate memory files."}'
else
  # Increment session counter silently
  python3 -c "
import json
with open('$DREAM_FILE', 'r') as f:
    d = json.load(f)
d['sessions_since_dream'] = d.get('sessions_since_dream', 0) + 1
with open('$DREAM_FILE', 'w') as f:
    json.dump(d, f, indent=2)
" 2>/dev/null
fi
