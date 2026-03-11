#!/bin/zsh
set -euo pipefail

TARGET_PATH="${1:-/Users/tttksj/first_repo}"

open -a /Applications/Cursor.app "$TARGET_PATH"
echo "CURSOR_OPENED $TARGET_PATH"
