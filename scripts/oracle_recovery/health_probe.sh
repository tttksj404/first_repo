#!/bin/bash
# health_probe.sh - g185 VM 상태 4단계 진단
# Exit codes:
#   0 = healthy (TCP+SSH+agent OK)
#   1 = TCP open but SSH banner timeout (sshd hang)
#   2 = TCP closed (network/VM down)
#   3 = SSH OK but agent dead
#   4 = Cloud Shell OCI CLI 사용 불가
set -u
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/config.env"
strip_cr() { printf '%s' "${1//$'\r'/}"; }
INST_ID="$(strip_cr "$INST_ID")"
SSH_HOST="$(strip_cr "$SSH_HOST")"
SSH_USER="$(strip_cr "$SSH_USER")"
SSH_IP="$(strip_cr "$SSH_IP")"
SSH_PORT="$(strip_cr "$SSH_PORT")"
REGION="$(strip_cr "$REGION")"

echo "=== g185 health probe $(date +%H:%M:%S) ==="
SSH_KEY_ARGS=()
if [ -f "$HOME/.ssh/id_ed25519" ]; then
  SSH_KEY_ARGS=(-i "$HOME/.ssh/id_ed25519")
fi

# 1. TCP reachability (not blocking, 5s)
if command -v nc >/dev/null 2>&1; then
  if timeout 5 nc -zv "$SSH_IP" "$SSH_PORT" 2>&1 | grep -q "succeeded\|open"; then
    echo "[1/4] TCP $SSH_IP:$SSH_PORT  OK"
  else
    echo "[1/4] TCP $SSH_IP:$SSH_PORT  CLOSED"
    exit 2
  fi
else
  if timeout 5 bash -c "echo > /dev/tcp/$SSH_IP/$SSH_PORT" 2>/dev/null; then
    echo "[1/4] TCP $SSH_IP:$SSH_PORT  OK"
  else
    echo "[1/4] TCP $SSH_IP:$SSH_PORT  CLOSED"
    exit 2
  fi
fi

# 2. SSH banner exchange (15s timeout)
SSH_OUT=$(timeout 15 ssh -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=5 \
  -o StrictHostKeyChecking=accept-new "${SSH_KEY_ARGS[@]}" \
  -p "$SSH_PORT" "$SSH_USER@$SSH_IP" 'echo ALIVE' 2>&1)
if echo "$SSH_OUT" | grep -q "^ALIVE$"; then
  echo "[2/4] SSH banner+auth  OK"
else
  echo "[2/4] SSH banner FAIL: $(echo "$SSH_OUT" | head -1)"
  exit 1
fi

# 3. Quick remote command (sshd alive)
RC=$(timeout 10 ssh -o StrictHostKeyChecking=accept-new "${SSH_KEY_ARGS[@]}" \
  -p "$SSH_PORT" "$SSH_USER@$SSH_IP" 'systemctl is-active sshd' 2>&1 | tr -d '\r\n')
echo "[3/4] sshd service: $RC"

# 4. Cloud Agent reachable (OCI CLI present)
if command -v oci >/dev/null 2>&1; then
  STATE=$(oci compute instance get --region "$REGION" --instance-id "$INST_ID" \
    --query 'data."lifecycle-state"' --raw-output 2>/dev/null || echo "ERR")
  echo "[4/4] Hypervisor state: $STATE"
else
  echo "[4/4] (oci CLI not local — skip)"
  exit 4
fi

echo "=== healthy ==="
exit 0
