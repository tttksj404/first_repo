#!/bin/sh
set -eu

TOKEN="${TELEGRAM_BOT_TOKEN:-}"

if [ -z "$TOKEN" ]; then
  TOKEN="$(
    python3 - <<'PY'
from pathlib import Path

for name in ['.env', '.env.local']:
    path = Path(name)
    if not path.exists():
        continue
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        if key.strip() == 'TELEGRAM_BOT_TOKEN':
            print(value.strip().strip('"').strip("'"))
            raise SystemExit
PY
  )"
fi

if [ -z "$TOKEN" ]; then
  echo "TELEGRAM_BOT_TOKEN is required" >&2
  exit 1
fi

openclaw channels add --channel telegram --token "$TOKEN"
openclaw channels list --json
