#!/bin/zsh
set -euo pipefail

ROOT="/Users/tttksj/first_repo/04. Tools/agent-stack"
MANIFEST="$ROOT/repos.json"
REPOS_DIR="$ROOT/repos"

if [[ ! -f "$MANIFEST" ]]; then
  echo "Manifest not found: $MANIFEST" >&2
  exit 1
fi

mkdir -p "$REPOS_DIR"

python3 - <<'PY' "$MANIFEST" "$REPOS_DIR"
import json
import subprocess
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
items = json.loads(manifest.read_text())

for item in items:
    if item.get("type") != "github":
        continue

    repo_id = item["id"]
    url = item["url"]
    target = Path(item["local_path"]).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n==> {repo_id}")
    if (target / ".git").exists():
        cmd = ["git", "-C", str(target), "pull", "--ff-only"]
    else:
        cmd = ["git", "clone", "--depth", "1", url, str(target)]
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)
PY
