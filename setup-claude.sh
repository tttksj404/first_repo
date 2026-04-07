#!/bin/bash
# 새 PC에서 Claude 스킬 환경 설정 (한 번만 실행)
# 사용법: bash <(curl -s https://raw.githubusercontent.com/tttksj404/first_repo/main/setup-claude.sh)

set -e

REPO_URL="https://github.com/tttksj404/first_repo.git"
REPO_DIR="$HOME/.claude/skills-repo"
COMMANDS_DIR="$HOME/.claude/commands"
SETTINGS_FILE="$HOME/.claude/settings.json"
SYNC_SCRIPT="$HOME/.claude/sync-skills.sh"

echo "=== Claude Skills 환경 설정 ==="

# 디렉토리 생성
mkdir -p "$COMMANDS_DIR"
mkdir -p "$HOME/.claude"

# 레포 클론
if [ -d "$REPO_DIR/.git" ]; then
    echo "레포 업데이트 중..."
    git -C "$REPO_DIR" pull --quiet origin main
else
    echo "레포 클론 중..."
    git clone --quiet "$REPO_URL" "$REPO_DIR"
fi

# 스킬 복사
if [ -d "$REPO_DIR/commands" ]; then
    cp -f "$REPO_DIR/commands/"*.md "$COMMANDS_DIR/"
    echo "✅ 스킬 $(ls $COMMANDS_DIR/*.md | wc -l)개 설치 완료"
else
    echo "⚠️  레포에 commands/ 폴더 없음 — 먼저 스킬 업로드 필요"
fi

# sync 스크립트 설치
if [ -f "$REPO_DIR/sync-skills.sh" ]; then
    cp "$REPO_DIR/sync-skills.sh" "$SYNC_SCRIPT"
    chmod +x "$SYNC_SCRIPT"
fi

# settings.json 설치 (없을 때만)
if [ ! -f "$SETTINGS_FILE" ]; then
    cat > "$SETTINGS_FILE" << 'EOF'
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/sync-skills.sh"
          }
        ]
      }
    ]
  }
}
EOF
    echo "✅ Claude hooks 설정 완료"
else
    echo "⚠️  settings.json 이미 존재 — 수동으로 hook 추가 필요"
fi

echo ""
echo "=== 설치 완료 ==="
echo "Claude Code를 실행하면 자동으로 스킬이 동기화됩니다."
echo "사용 가능한 스킬:"
ls "$COMMANDS_DIR"/*.md 2>/dev/null | xargs -I{} basename {} .md | sed 's/^/  \//g'
