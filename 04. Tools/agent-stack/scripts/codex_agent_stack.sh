#!/bin/zsh
set -euo pipefail

ROOT="/Users/tttksj/first_repo/04. Tools/agent-stack"
MANIFEST="$ROOT/repos.json"
DELEGATE="/Users/tttksj/first_repo/scripts/delegate_to_codex.sh"

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <repo-id> <prompt>" >&2
  exit 1
fi

REPO_ID="$1"
shift
PROMPT="$*"

if [[ ! -x "$DELEGATE" ]]; then
  echo "Codex delegate script not executable: $DELEGATE" >&2
  exit 1
fi

REPO_PATH="$(python3 - <<'PY' "$MANIFEST" "$REPO_ID"
import json, sys
manifest_path, repo_id = sys.argv[1], sys.argv[2]
items = json.load(open(manifest_path))
for item in items:
    if item.get('id') == repo_id:
        print(item.get('local_path') or '')
        break
else:
    sys.exit(2)
PY
)" || {
  echo "Unknown repo id: $REPO_ID" >&2
  exit 1
}

if [[ -z "$REPO_PATH" ]]; then
  echo "Repo id '$REPO_ID' does not point to a local git checkout." >&2
  exit 1
fi

if [[ ! -d "$REPO_PATH" ]]; then
  echo "Repo path not found: $REPO_PATH" >&2
  exit 1
fi

"$DELEGATE" --cwd "$REPO_PATH" -- "$PROMPT"
