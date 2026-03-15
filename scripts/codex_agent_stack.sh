#!/bin/zsh
set -euo pipefail

ROOT="/Users/tttksj/first_repo"
MANIFEST="$ROOT/04. Tools/agent-stack/repos.json"

if [[ $# -lt 2 ]]; then
  cat >&2 <<'EOF'
Usage:
  scripts/codex_agent_stack.sh <repo-id> <prompt...>

Example:
  scripts/codex_agent_stack.sh agency-agents "Summarize how task handoff works and how to adapt it for OpenClaw."
EOF
  exit 1
fi

REPO_ID="$1"
shift
PROMPT="$*"

REPO_PATH=$(python3 - "$MANIFEST" "$REPO_ID" <<'PY'
import json, sys
manifest_path, repo_id = sys.argv[1], sys.argv[2]
with open(manifest_path, 'r', encoding='utf-8') as f:
    items = json.load(f)
for item in items:
    if item.get('id') == repo_id:
        if item.get('type') != 'github' or not item.get('local_path'):
            raise SystemExit(f"Repo '{repo_id}' is not a local git repo target.")
        print(item['local_path'])
        raise SystemExit(0)
raise SystemExit(f"Unknown repo id: {repo_id}")
PY
)

exec "$ROOT/scripts/delegate_to_codex.sh" --cwd "$ROOT/$REPO_PATH" -- "$PROMPT"
