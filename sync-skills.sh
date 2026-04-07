#!/bin/bash
# Claude Skills Auto-Sync
# GitHub repo → ~/.claude/commands/
# 1시간에 한 번만 실행 (불필요한 네트워크 요청 방지)

REPO_URL="https://github.com/tttksj404/first_repo.git"
REPO_DIR="$HOME/.claude/skills-repo"
COMMANDS_DIR="$HOME/.claude/commands"
TIMESTAMP_FILE="$HOME/.claude/.last-sync"
SYNC_INTERVAL=3600  # 1시간 (초)

# 마지막 동기화 시간 확인
if [ -f "$TIMESTAMP_FILE" ]; then
    last_sync=$(cat "$TIMESTAMP_FILE")
    now=$(date +%s)
    elapsed=$((now - last_sync))
    if [ $elapsed -lt $SYNC_INTERVAL ]; then
        exit 0  # 아직 1시간 안 됨 → 조용히 종료
    fi
fi

# 동기화 실행
mkdir -p "$COMMANDS_DIR"

if [ -d "$REPO_DIR/.git" ]; then
    # 이미 클론됨 → pull
    git -C "$REPO_DIR" pull --quiet origin main 2>/dev/null
else
    # 처음 → clone
    git clone --quiet "$REPO_URL" "$REPO_DIR" 2>/dev/null
fi

# repo의 commands/ 폴더가 있으면 ~/.claude/commands/로 복사
if [ -d "$REPO_DIR/commands" ]; then
    cp -f "$REPO_DIR/commands/"*.md "$COMMANDS_DIR/" 2>/dev/null
fi

# 타임스탬프 갱신
date +%s > "$TIMESTAMP_FILE"
