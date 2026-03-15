#!/bin/zsh
set -euo pipefail

ROOT="/Users/tttksj/first_repo"
MANIFEST="$ROOT/04. Tools/agent-stack/repos.json"
BASE="$ROOT/04. Tools/agent-stack/repos"

if [[ ! -f "$MANIFEST" ]]; then
  echo "Missing manifest: $MANIFEST" >&2
  exit 1
fi

mkdir -p "$BASE"

python3 - "$MANIFEST" <<'PY' | while IFS=$'\t' read -r repo_type repo_url repo_path; do
import json, sys
manifest_path = sys.argv[1]
with open(manifest_path, 'r', encoding='utf-8') as f:
    entries = json.load(f)
for item in entries:
    if item.get('type') == 'github' and item.get('local_path'):
        print(f"{item['type']}\t{item['url']}\t{item['local_path']}")
PY
  abs_path="$ROOT/${repo_path}"
  if [[ -d "$abs_path/.git" ]]; then
    echo "[update] $repo_url"
    git -C "$abs_path" pull --ff-only
  else
    echo "[clone]  $repo_url"
    git clone "$repo_url" "$abs_path"
  fi
done

echo
echo "Agent stack repos are ready under: $BASE"
