#!/bin/bash
# Auto-commit + push for quant_binance strategy work.
# Triggered by Claude Code Stop hook (.claude/settings.json).
# SILENT FAIL — never block conversation.

set +e  # don't exit on any error
REPO_DIR="C:/Users/SSAFY/Desktop/first_repo"

cd "$REPO_DIR" || exit 0

# Check if any changes in tracked strategy paths
CHANGES=$(git status -s -- quant_binance/strategies/ .gitignore 2>/dev/null)
if [ -z "$CHANGES" ]; then
    exit 0  # nothing to commit, silent
fi

# Stage strategy work only (whitelist — avoids sensitive files)
git add \
    quant_binance/strategies/REGISTRY.md \
    quant_binance/strategies/G* \
    quant_binance/strategies/S001_baseline \
    quant_binance/strategies/_playbook \
    quant_binance/strategies/_scripts \
    .gitignore 2>/dev/null

# Confirm something actually staged
STAGED=$(git diff --cached --name-only 2>/dev/null)
if [ -z "$STAGED" ]; then
    exit 0
fi

# Build commit message from changed files
N_FILES=$(echo "$STAGED" | wc -l)
SAMPLE=$(echo "$STAGED" | head -3 | sed 's|quant_binance/strategies/||g' | tr '\n' ',' | sed 's/,$//')
TIMESTAMP=$(date -u "+%Y-%m-%d %H:%M UTC")

git -c "user.name=lumenseo" -c "user.email=leslumiere1@gmail.com" \
    commit -m "auto(quant): ${SAMPLE} (+ ${N_FILES} files) [${TIMESTAMP}]

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>" >/dev/null 2>&1

# Push to origin (silent fail OK — next turn will retry)
BRANCH=$(git branch --show-current 2>/dev/null)
if [ -n "$BRANCH" ]; then
    git push origin "$BRANCH" >/dev/null 2>&1 &
    # background push, don't block hook
    disown 2>/dev/null
fi

exit 0
