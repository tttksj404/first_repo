#!/usr/bin/env bash
# harden_vm.sh - one-time durability settings for the Oracle g185 VM.
#
# Run after SSH is available:
#   scp scripts/oracle_recovery/harden_vm.sh g185:~/
#   ssh g185 'bash ~/harden_vm.sh'
set -euo pipefail

echo "[harden] $(date -u) applying"

sudo mkdir -p /etc/ssh/sshd_config.d
sudo tee /etc/ssh/sshd_config.d/99-quant-hardening.conf > /dev/null << 'SSHEOF'
Port 22
Port 443
MaxStartups 100:30:200
MaxSessions 25
ClientAliveInterval 60
ClientAliveCountMax 3
LoginGraceTime 30
SSHEOF
echo "[harden] sshd config installed"

sudo mkdir -p /etc/systemd/system/sshd.service.d
sudo tee /etc/systemd/system/sshd.service.d/99-restart.conf > /dev/null << 'UNITEOF'
[Service]
Restart=always
RestartSec=5
StartLimitInterval=0
UNITEOF
echo "[harden] sshd auto-restart enabled"

if systemctl list-unit-files | grep -q oracle-cloud-agent; then
  sudo mkdir -p /etc/systemd/system/oracle-cloud-agent.service.d
  sudo tee /etc/systemd/system/oracle-cloud-agent.service.d/99-restart.conf > /dev/null << 'UNITEOF2'
[Service]
Restart=always
RestartSec=10
UNITEOF2
  echo "[harden] oracle-cloud-agent auto-restart enabled"
fi

sudo tee /etc/security/limits.d/90-quant.conf > /dev/null << 'LIMEOF'
* soft nofile 65535
* hard nofile 65535
* soft nproc 32768
* hard nproc 32768
LIMEOF
echo "[harden] ulimits raised"

sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/99-cap.conf > /dev/null << 'JEOF'
[Journal]
Storage=persistent
SystemMaxUse=500M
SystemKeepFree=2G
JEOF
echo "[harden] journald capped"

sudo tee /usr/local/bin/sshd-selfheal.sh > /dev/null << 'HEAL'
#!/usr/bin/env bash
set -u
LOG=/var/log/sshd-selfheal.log
TS=$(date '+%Y-%m-%d %H:%M:%S')
if ! systemctl is-active --quiet sshd; then
  echo "[$TS] sshd inactive - restarting" >> "$LOG"
  systemctl restart sshd
  sleep 3
  systemctl is-active sshd >> "$LOG" 2>&1 || true
fi
HEAL
sudo chmod +x /usr/local/bin/sshd-selfheal.sh

sudo tee /etc/cron.d/sshd-selfheal > /dev/null << 'CRONEOF'
*/5 * * * * root /usr/local/bin/sshd-selfheal.sh
CRONEOF
echo "[harden] cron self-heal installed"

sudo systemctl daemon-reload
sudo systemctl restart systemd-journald
sudo sshd -t
sudo systemctl reload sshd

echo "=== applied sshd settings ==="
sudo sshd -T 2>/dev/null | grep -iE "^(port|maxstartups|maxsessions|clientalive|logingrace)"
echo "=== done ==="
