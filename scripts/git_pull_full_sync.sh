#!/bin/sh
set -eu

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

CURRENT_BRANCH="$(git branch --show-current)"
if [ -z "$CURRENT_BRANCH" ]; then
  echo "Detached HEAD is not supported for full sync." >&2
  exit 1
fi

echo "[1/4] Fetching all remotes..."
git fetch --all --prune

echo "[2/4] Fast-forwarding every local branch with an upstream..."
BRANCHES="$(git for-each-ref --format='%(refname:short) %(upstream:short)' refs/heads | awk '$2 != \"\" {print $1}')"
for BRANCH in $BRANCHES; do
  echo " - sync $BRANCH"
  git checkout "$BRANCH" >/dev/null 2>&1
  git pull --ff-only
done

echo "[3/4] Returning to $CURRENT_BRANCH..."
git checkout "$CURRENT_BRANCH" >/dev/null 2>&1

echo "[4/4] Merging origin/main into $CURRENT_BRANCH..."
if git show-ref --verify --quiet refs/remotes/origin/main; then
  if [ "$CURRENT_BRANCH" = "main" ]; then
    echo "Current branch is main; merge step skipped."
  else
    git merge origin/main
  fi
else
  echo "origin/main not found; merge step skipped."
fi

echo "Full sync completed."
