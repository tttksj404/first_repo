#!/bin/bash
# emergency_recover.sh - automated Oracle VM recovery pipeline
# flow: probe -> ensure running/start -> instance-agent sshd restart -> SOFTRESET -> RESET
set -u
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# First refresh stale instance OCID/IP when OCI Search is available. The command
# may fail if TCP is closed or key auth is not enrolled yet; that is fine as
# long as it had a chance to update config.env from OCI discovery.
if command -v python3 >/dev/null 2>&1 && [ -f "$SCRIPT_DIR/ensure_access.py" ]; then
  python3 "$SCRIPT_DIR/ensure_access.py" --repair >/tmp/g185_ensure_access.log 2>&1 || true
fi

source "$SCRIPT_DIR/config.env"
strip_cr() { printf '%s' "${1//$'\r'/}"; }
INST_ID="$(strip_cr "$INST_ID")"
COMP_ID="$(strip_cr "$COMP_ID")"
SSH_HOST="$(strip_cr "$SSH_HOST")"
SSH_USER="$(strip_cr "$SSH_USER")"
SSH_IP="$(strip_cr "$SSH_IP")"
SSH_PORT="$(strip_cr "$SSH_PORT")"
REGION="$(strip_cr "$REGION")"

LOG="${SCRIPT_DIR}/recover_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

echo "=== EMERGENCY RECOVER $(date) ==="
echo "INST_ID=$INST_ID"

probe() { bash "$SCRIPT_DIR/health_probe.sh"; return $?; }

# Step 0: probe first
probe; RC=$?
if [ "$RC" -eq 0 ]; then
  echo "[step0] healthy / no action"
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

# Step 1: ensure RUNNING
HYP_STATE=$(oci compute instance get --region "$REGION" --instance-id "$INST_ID" \
  --query 'data."lifecycle-state"' --raw-output)
HYP_RC=$?
if [ "$HYP_RC" -ne 0 ]; then
  echo "[step1] hypervisor state query failed (rc=$HYP_RC)"
  echo "[step1] Check Cloud Shell tenancy/region/permission or INST_ID in config.env"
  exit 10
fi
echo "[step1] hypervisor state=$HYP_STATE"

if [ "$HYP_STATE" = "STOPPED" ]; then
  echo "[step1] instance is STOPPED -> START"
  if oci compute instance action --region "$REGION" --action START --instance-id "$INST_ID" \
    --wait-for-state RUNNING --max-wait-seconds 600 >/dev/null 2>&1; then
    HYP_STATE="RUNNING"
    echo "[step1] START completed -> RUNNING"
    sleep 45
    probe && { echo "[step1] recovered after START"; exit 0; }
  else
    echo "[step1] START failed"
  fi
fi

if [ "$HYP_STATE" = "TERMINATED" ] || [ "$HYP_STATE" = "TERMINATING" ]; then
  echo "[step1] instance state=$HYP_STATE (cannot recover by reset/start)"
  echo "Need new instance provision or correct INST_ID in config.env"
  exit 2
fi

# Step 1b: restart sshd via instance agent command (only when RUNNING)
if [ "$HYP_STATE" = "RUNNING" ]; then
  echo "[step1b] sending sshd-restart via agent..."
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
  CMD_ID=$(oci instance-agent command create --region "$REGION" --from-json file:///tmp/recover_body.json \
    --timeout-in-seconds 60 --query 'data.id' --raw-output 2>/dev/null)
  if [ -n "$CMD_ID" ]; then
    echo "[step1b] CMD_ID=$CMD_ID / wait 90s for execution"
    for i in $(seq 1 18); do
      S=$(oci instance-agent command-execution get --region "$REGION" --instance-id "$INST_ID" \
        --command-id "$CMD_ID" --query 'data."lifecycle-state"' --raw-output 2>/dev/null)
      [ "$S" = "SUCCEEDED" ] && { echo "[step1b] agent-restart SUCCEEDED"; sleep 15; probe && exit 0; break; }
      [ "$S" = "FAILED" ] || [ "$S" = "TIMED_OUT" ] && { echo "[step1b] agent-restart $S"; break; }
      sleep 5
    done
  else
    echo "[step1b] agent command rejected (agent likely dead)"
  fi
fi

# Step 2: SOFTRESET
echo "[step2] SOFTRESET..."
oci compute instance action --region "$REGION" --action SOFTRESET --instance-id "$INST_ID" \
  --wait-for-state RUNNING --max-wait-seconds 300 >/dev/null 2>&1 && {
  sleep 90
  probe && { echo "[step2] recovered after SOFTRESET"; exit 0; }
}

# Step 3: RESET
echo "[step3] hard RESET..."
oci compute instance action --region "$REGION" --action RESET --instance-id "$INST_ID" \
  --wait-for-state RUNNING --max-wait-seconds 300 >/dev/null 2>&1 && {
  sleep 120
  probe && { echo "[step3] recovered after RESET"; exit 0; }
}

echo "=== FAILED / manual intervention required ==="
echo "Check OCI Console serial console: https://cloud.oracle.com/compute/instances/$INST_ID"
exit 1
