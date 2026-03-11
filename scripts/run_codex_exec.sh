#!/bin/zsh
set -euo pipefail

if [[ $# -eq 0 ]]; then
  echo "Usage: $0 <prompt>" >&2
  exit 1
fi

codex exec \
  --cd /Users/tttksj/first_repo \
  --sandbox workspace-write \
  -c approval_policy='"never"' \
  "$*"
