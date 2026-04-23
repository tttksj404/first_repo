#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
BASE_DIR="${1:-quant_runtime}"
PAPER_BASE="${2:-quant_runtime_paper50}"
EXCHANGE_ID="${EXCHANGE:-bitget}"

cd "$REPO_ROOT"

echo "[DOCTOR] repo_root=$REPO_ROOT"
echo "[DOCTOR] python=$(sh "$SCRIPT_DIR/quant_python.sh" --print)"

sh "$SCRIPT_DIR/quant_init_workspace.sh" "$BASE_DIR" >/dev/null
sh "$SCRIPT_DIR/quant_init_workspace.sh" "$PAPER_BASE" >/dev/null

echo "[DOCTOR] workspace initialized: $BASE_DIR, $PAPER_BASE"
echo "[DOCTOR] running env-check (exchange=$EXCHANGE_ID)"
sh "$SCRIPT_DIR/quant_env_check.sh"

FILTER_PATH="$PAPER_BASE/paper50_multi_symbol_filters.json"
if [ -f "$FILTER_PATH" ]; then
  sh "$SCRIPT_DIR/quant_python.sh" - <<'PY' "$FILTER_PATH"
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
profiles = data.get("symbol_filter_profiles") or {}
universe = data.get("universe") or []
print(f"[DOCTOR] paper50 filters ok: profiles={len(profiles)} universe={len(universe)}")
PY
else
  echo "[DOCTOR] warning: $FILTER_PATH is missing (paper50 will use runtime defaults until created)"
fi

echo "[DOCTOR] done"
