#!/bin/bash
# mac_setup.sh — Mac에서 g185 SSH 접속 원큐 셋업
# 사용법:
#   curl -fsSL <repo>/scripts/oracle_recovery/mac_setup.sh | bash
#   또는 파일을 Mac에 복사 후: bash mac_setup.sh
#
# 동작:
#   1. ~/.ssh 디렉토리/권한 확인 + 생성
#   2. ed25519 키 없으면 생성 (있으면 그대로 사용)
#   3. ~/.ssh/config 에 'Host g185' 블록 idempotent 삽입
#   4. 권한 정상화
#   5. 공개키 출력 + g185 authorized_keys 등록 명령 안내
#   6. SSH 시도 → 성공/실패 진단
#
# Idempotent — 여러 번 실행해도 안전.
set -uo pipefail

KEY_PATH="${HOME}/.ssh/id_ed25519"
PUB_PATH="${KEY_PATH}.pub"
CFG_PATH="${HOME}/.ssh/config"
HOST_BLOCK_TAG="# === g185 (Oracle paper trading VM) — managed by mac_setup.sh ==="
HOST_BLOCK_END="# === end g185 ==="

# ANSI colors
G='\033[1;32m'; Y='\033[1;33m'; R='\033[1;31m'; B='\033[1;34m'; N='\033[0m'

step() { printf "${B}[step %s]${N} %s\n" "$1" "$2"; }
ok()   { printf "${G}  ✓${N} %s\n" "$1"; }
warn() { printf "${Y}  ⚠${N} %s\n" "$1"; }
fail() { printf "${R}  ✗${N} %s\n" "$1"; }

# ─── 1. ~/.ssh dir ───
step 1 "~/.ssh 디렉토리 확인"
mkdir -p "${HOME}/.ssh"
chmod 700 "${HOME}/.ssh"
ok "$(ls -ld ${HOME}/.ssh | awk '{print $1, $9}')"

# ─── 2. ed25519 키 ───
step 2 "ed25519 키 확인/생성"
if [ -f "$KEY_PATH" ]; then
  ok "기존 키 사용: $KEY_PATH"
  KEY_AGE=$(stat -f "%Sm" -t "%Y-%m-%d" "$KEY_PATH" 2>/dev/null || stat -c "%y" "$KEY_PATH" 2>/dev/null | cut -d' ' -f1)
  ok "  생성일: $KEY_AGE"
else
  warn "키 없음 — 새로 생성"
  ssh-keygen -t ed25519 -f "$KEY_PATH" -N "" -C "g185-paper@$(hostname -s)-$(date +%Y%m%d)" \
    && ok "생성 완료" || { fail "키 생성 실패"; exit 1; }
fi

chmod 600 "$KEY_PATH"
chmod 644 "$PUB_PATH"

# ─── 3. ~/.ssh/config ───
step 3 "~/.ssh/config 에 Host g185 블록 추가"
touch "$CFG_PATH"
chmod 600 "$CFG_PATH"

if grep -qF "$HOST_BLOCK_TAG" "$CFG_PATH"; then
  warn "이미 등록됨 — 기존 블록 그대로 유지"
else
  # CONTROL master 디렉토리 사전 생성 (소켓 path)
  mkdir -p "${HOME}/.ssh"
  cat >> "$CFG_PATH" << CFGEOF

${HOST_BLOCK_TAG}
Host g185
    HostName 140.245.66.2
    Port 443
    User opc
    IdentityFile ${KEY_PATH}
    StrictHostKeyChecking accept-new
    ControlMaster auto
    ControlPath ${HOME}/.ssh/cm-%r@%h-%p
    ControlPersist 300
    ConnectTimeout 30
    ServerAliveInterval 30
    ServerAliveCountMax 3
${HOST_BLOCK_END}
CFGEOF
  ok "Host g185 블록 추가됨"
fi

# ─── 4. 공개키 출력 + 등록 안내 ───
step 4 "공개키 (이걸 g185 authorized_keys 에 등록)"
echo
printf "${Y}─── PUBLIC KEY (한 줄 복사) ───${N}\n"
cat "$PUB_PATH"
printf "${Y}────────────────────────────────${N}\n"
echo

# ─── 5. SSH 자동 시도 ───
step 5 "g185 접속 테스트"
if timeout 15 ssh -o BatchMode=yes -o ConnectTimeout=10 g185 'echo OK' 2>/dev/null | grep -q OK; then
  ok "SSH 접속 성공! 셋업 완료 ✅"
  echo
  echo "이제 어디서든:"
  echo "  ssh g185"
  echo "  ssh g185 'free -m'"
  echo
  exit 0
fi

# 실패 시 등록 안내
warn "SSH 실패 — public key가 g185에 아직 등록 안 됨 (정상)"
echo
echo "다음 두 가지 중 한 가지로 등록:"
echo
printf "${B}[A] 다른 PC (예: SSAFY PC) 에서 g185 접근 가능하면${N}\n"
echo "  1. SSAFY PC 에서 다음 명령 실행 (위 PUBLIC KEY 한 줄을 큰따옴표 안에 붙여넣기):"
echo
PUBKEY_ONELINE=$(cat "$PUB_PATH" | tr -d '\n')
cat << SNIPPET
     ssh g185 'echo "${PUBKEY_ONELINE}" >> ~/.ssh/authorized_keys'

SNIPPET
echo "  2. 그 다음 Mac 에서 다시:  ssh g185 'echo OK'"
echo
printf "${B}[B] OCI Cloud Shell 에서 등록 (다른 PC 없을 때)${N}\n"
echo "  1. https://cloud.oracle.com → 우상단 >_ 아이콘 → Cloud Shell 열기"
echo "  2. 거기서 ssh로 g185 접근 (이미 instance principal로 인증)"
echo "  3. 같은 명령 실행:"
cat << SNIPPET
     echo "${PUBKEY_ONELINE}" | ssh opc@140.245.66.2 -p 443 'cat >> ~/.ssh/authorized_keys'
SNIPPET
echo
printf "${B}[C] OCI run-command 로 등록 (Cloud Shell + OCI CLI)${N}\n"
echo "  Cloud Shell 에서 다음 paste:"
cat << 'SNIPPET'
     INST_ID="ocid1.instance.oc1.ap-chuncheon-1.an4w4ljraf77hmics3zmpkmy6uxcia43bvmdwsyi4zrxtyirkqgtlnjjndsq"
     COMP_ID="ocid1.tenancy.oc1..aaaaaaaaaoemxeia7ojxcn2wgd6puorbwvbw6qvcbronpadsxcidpqx4a7ga"
SNIPPET
cat << SNIPPET
     PUBKEY='${PUBKEY_ONELINE}'
     cat > /tmp/add_key.json << EOF
     {
       "compartmentId": "\$COMP_ID",
       "executionTimeOutInSeconds": 60,
       "displayName": "add-mac-key",
       "target": {"instanceId": "\$INST_ID"},
       "content": {
         "source": {"sourceType": "TEXT", "text": "echo '\$PUBKEY' >> /home/opc/.ssh/authorized_keys && echo OK"},
         "output": {"outputType": "TEXT"}
       }
     }
     EOF
     oci instance-agent command create --from-json file:///tmp/add_key.json --timeout-in-seconds 60
SNIPPET

echo
echo "등록 후 Mac 에서:  ssh g185 'echo ALIVE; free -m'"
exit 1
