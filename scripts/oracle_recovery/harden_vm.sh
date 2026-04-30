#!/bin/bash
# harden_vm.sh - g185 VM 측 영구 방지 설정
# 실행: SSH 복구된 직후 1회 (이후 자동 유지)
# 효과:
#   1) sshd MaxStartups 100:30:200 (기본 10:30:60 → 약 3배)
#   2) sshd MaxSessions 10 → 25
#   3) systemd watchdog: sshd 죽으면 5초 안에 자동 재시작
#   4) Cloud Agent watchdog: agent 죽으면 자동 재시작
#   5) /etc/security/limits.d/90-quant.conf: nofile 65535
#   6) journald: persist + size cap 500M (디스크 폭주 방지)
#   7) cron health-check: 5분마다 sshd 응답 체크 → 죽었으면 restart
set -euo pipefail

echo "[harden] $(date) — applying"

# 1. sshd config
sudo tee /etc/ssh/sshd_config.d/99-quant-hardening.conf > /dev/null << 'SSHEOF'
MaxStartups 100:30:200
MaxSessions 25
ClientAliveInterval 60
ClientAliveCountMax 3
LoginGraceTime 30
SSHEOF
echo "[harden] sshd config installed"

# 2. systemd: sshd auto-restart on crash (override unit)
sudo mkdir -p /etc/systemd/system/sshd.service.d
sudo tee /etc/systemd/system/sshd.service.d/99-restart.conf > /dev/null << 'UNITEOF'
[Service]
Restart=always
RestartSec=5
StartLimitInterval=0
UNITEOF
echo "[harden] sshd systemd auto-restart enabled"

# 3. Cloud Agent auto-restart
if systemctl list-unit-files | grep -q oracle-cloud-agent; then
  sudo mkdir -p /etc/systemd/system/oracle-cloud-agent.service.d
  sudo tee /etc/systemd/system/oracle-cloud-agent.service.d/99-restart.conf > /dev/null << 'UNITEOF2'
[Service]
Restart=always
RestartSec=10
UNITEOF2
  echo "[harden] cloud-agent auto-restart enabled"
fi

# 4. ulimits (avoid nofile exhaustion)
sudo tee /etc/security/limits.d/90-quant.conf > /dev/null << 'LIMEOF'
* soft nofile 65535
* hard nofile 65535
* soft nproc 32768
* hard nproc 32768
LIMEOF
echo "[harden] ulimits raised"

# 5. journald cap
sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/99-cap.conf > /dev/null << 'JEOF'
[Journal]
Storage=persistent
SystemMaxUse=500M
SystemKeepFree=2G
LIEOF
JEOF
echo "[harden] journald capped 500M"

# 6. local sshd healthcheck cron (5분 간격)
sudo tee /usr/local/bin/sshd-selfheal.sh > /dev/null << 'HEAL'
#!/bin/bash
# 자기 자신에게 SSH 못하면 sshd restart
LOG=/var/log/sshd-selfheal.log
TS=$(date '+%Y-%m-%d %H:%M:%S')
if ! timeout 8 ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no \
     -i /home/opc/.ssh/id_ed25519 opc@localhost -p 22 'echo OK' 2>/dev/null | grep -q OK; then
  echo "[$TS] SSH selfprobe FAIL — restarting sshd" >> "$LOG"
  systemctl restart sshd
  sleep 3
  systemctl is-active sshd >> "$LOG"
fi
HEAL
sudo chmod +x /usr/local/bin/sshd-selfheal.sh

sudo tee /etc/cron.d/sshd-selfheal > /dev/null << 'CRONEOF'
*/5 * * * * root /usr/local/bin/sshd-selfheal.sh
CRONEOF
echo "[harden] cron self-heal installed (every 5 min)"

# 7. apply
sudo systemctl daemon-reload
sudo systemctl restart systemd-journald
sudo sshd -t && sudo systemctl reload sshd
echo "[harden] reload OK"

# 8. summary
echo ""
echo "=== applied configuration ==="
sudo sshd -T 2>/dev/null | grep -iE "maxstartups|maxsessions|clientalive"
echo ""
ulimit -n
echo "=== DONE ==="
