#!/bin/zsh
set -euo pipefail

TARGET_PATH="${1:-/Users/tttksj/first_repo}"

open -a /Applications/PyCharm.app "$TARGET_PATH"
echo "PYCHARM_OPENED $TARGET_PATH"
