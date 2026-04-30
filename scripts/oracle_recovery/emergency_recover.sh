#!/bin/bash
# emergency_recover.sh - 자동 복구 파이프라인 (Cloud Shell 또는 oci CLI 가능 환경 전제)
# 단계: probe -> command via agent -> SOFTRESET -> RESET -> alert
set -u
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/config.env"

LOG="${SCRIPT_DIR}/recover_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

echo "=== EMERGENCY RECOVER $(date) ==="
echo "INST_ID=$INST_ID"

probe() { bash "$SCRIPT_DIR/health_probe.sh"; return $?; }

# Step 0: probe — already healthy?
probe; RC=$?
if [ "$RC" -eq 0 ]; then
  echo "[step0] healthy — no action"
  exit 0
fi
echo "[step0] unhealthy code=$RC"

require_oci() {
  if ! command -v oci >/dev/null 2>&1; then
    echo "FATAL: oci CLI not available. Run from Cloud Shell or install OCI CLI."
    exit 99
  fi
}
require_oci

# Step 1: try cloud agent command (only if hypervisor RUNNING)
HYP_STATE=$(oci compute instance get --instance-id "$INST_ID" \
  --query 'data."lifecycle-state"' --raw-output 2>/dev/null || echo ERR)
echo "[step1] hypervisor state=$HYP_STATE"

if [ "$HYP_STATE" = "RUNNING" ]; then
  echo "[step1] sending sshd-restart via agent..."
  cat > /tmp/recover_body.json << JEOF
{
  "compartmentId": "$COMP_ID",
  "executionTimeOutInSeconds": 60,
  "displayName": "auto-sshd-restart",
  "target": {"instanceId": "$INST_ID"},
  "content": {
    "source": {"sourceType": "TEXT", "text": "sudo systemctl restart sshd; systemctl is-active sshd"},
    "output": {"outputType": "TEXT"}
  }
}
JEOF
  CMD_ID=$(oci instance-agent command create --from-json file:///tmp/recover_body.json \
    --timeout-in-seconds 60 --query 'data.id' --raw-output 2>/dev/null)
  if [ -n "$CMD_ID" ]; then
    echo "[step1] CMD_ID=$CMD_ID — wait 90s for execution"
    for i in $(seq 1 18); do
      S=$(oci instance-agent command-execution get --instance-id "$INST_ID" \
        --command-id "$CMD_ID" --query 'data."lifecycle-state"' --raw-output 2>/dev/null)
      [ "$S" = "SUCCEEDED" ] && { echo "[step1] agent-restart SUCCEEDED"; sleep 15; probe && exit 0; break; }
      [ "$S" = "FAILED" ] || [ "$S" = "TIMED_OUT" ] && { echo "[step1] agent-restart $S"; break; }
      sleep 5
    done
  else
    echo "[step1] agent command rejected (agent likely dead)"
  fi
fi

# Step 2: SOFTRESET
echo "[step2] SOFTRESET..."
oci compute instance action --action SOFTRESET --instance-id "$INST_ID" \
  --wait-for-state RUNNING --max-wait-seconds 300 >/dev/null 2>&1 && {
  sleep 90
  probe && { echo "[step2] recovered after SOFTRESET"; exit 0; }
}

# Step 3: hard RESET
echo "[step3] hard RESET..."
oci compute instance action --action RESET --instance-id "$INST_ID" \
  --wait-for-state RUNNING --max-wait-seconds 300 >/dev/null 2>&1 && {
  sleep 120
  probe && { echo "[step3] recovered after RESET"; exit 0; }
}

echo "=== FAILED — manual intervention required ==="
echo "Check OCI Console serial console: https://cloud.oracle.com/compute/instances/$INST_ID"
exit 1
