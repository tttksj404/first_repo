#!/bin/bash
# G185 deploy megablob — paste in Cloud Shell. SSH alias 'g185' must work first (set up earlier).
set -e

EM64='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'
G264='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'

echo "=== preparing remote dirs ==="
ssh g185 "mkdir -p ~/g185 ~/g185/runtime"

echo "=== uploading emulator + dependency ==="
echo "$EM64" | ssh g185 "base64 -d | gunzip > ~/g185/g185_emulator.py"
echo "$G264" | ssh g185 "base64 -d | gunzip > ~/g185/g002_mingogogo_ch1_backtest.py"
ssh g185 "ls -la ~/g185/"

echo "=== running remote setup (emulator + ssh port 443) ==="
ssh g185 bash << 'REMOTE_END'
set -e
echo "=== installing python deps ==="
command -v python3 >/dev/null || sudo dnf install -y python3
python3 -m pip install --user --quiet pandas numpy 2>/dev/null || { python3 -m ensurepip --user; python3 -m pip install --user --quiet pandas numpy; }

echo "=== creating systemd user service ==="
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/g185-emulator.service << UNIT
[Unit]
Description=G185 paper-live emulator
After=network-online.target

[Service]
Type=simple
WorkingDirectory=%h/g185
ExecStart=/usr/bin/python3 %h/g185/g185_emulator.py
Restart=always
RestartSec=30
StandardOutput=append:%h/g185/runtime/stdout.log
StandardError=append:%h/g185/runtime/stderr.log

[Install]
WantedBy=default.target
UNIT
echo "=== enable lingering ==="
sudo loginctl enable-linger "$USER"
echo "=== start emulator service ==="
systemctl --user daemon-reload
systemctl --user enable --now g185-emulator.service
sleep 5

echo "=== adding SSH Port 443 for outside-firewall access ==="
if ! sudo grep -q "^Port 443" /etc/ssh/sshd_config; then
    sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak
    if grep -q "^Port " /etc/ssh/sshd_config; then
        echo "Port 22 already explicit"
    else
        echo "Port 22" | sudo tee -a /etc/ssh/sshd_config >/dev/null
    fi
    echo "Port 443" | sudo tee -a /etc/ssh/sshd_config >/dev/null
fi

echo "=== firewalld open 443 ==="
sudo firewall-cmd --permanent --add-port=443/tcp || true
sudo firewall-cmd --reload || true

echo "=== SELinux allow ssh on 443 ==="
sudo semanage port -a -t ssh_port_t -p tcp 443 2>/dev/null || sudo semanage port -m -t ssh_port_t -p tcp 443 2>/dev/null || true

echo "=== iptables allow 443 (in case firewalld inactive) ==="
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || true

echo "=== restart sshd ==="
sudo systemctl restart sshd

echo "=== verify sshd listens on 443 ==="
sleep 2
sudo ss -tlnp | grep -E ":(22|443)" || true

echo "=== STATUS emulator ==="
systemctl --user status g185-emulator.service --no-pager | head -15
echo "=== LOG ==="
tail -20 ~/g185/runtime/emulator.log 2>/dev/null || echo "(log not yet written)"
REMOTE_END

echo "=== adding Security List ingress rule for TCP 443 (via OCI CLI) ==="
TENANCY=$(oci iam compartment list --query 'data[0]."compartment-id"' --raw-output 2>/dev/null)
[ -z "$TENANCY" ] && TENANCY=$OCI_CLI_TENANCY
echo "tenancy: $TENANCY"
VCN_ID=$(oci network vcn list --compartment-id "$TENANCY" --query 'data[?"display-name"==`g185-vcn`].id | [0]' --raw-output 2>/dev/null)
echo "vcn-id: $VCN_ID"
SL_ID=$(oci network security-list list --vcn-id "$VCN_ID" --compartment-id "$TENANCY" --query 'data[0].id' --raw-output 2>/dev/null)
echo "seclist-id: $SL_ID"
if [ -n "$SL_ID" ]; then
    CURRENT=$(oci network security-list get --security-list-id "$SL_ID" --query 'data."ingress-security-rules"' 2>/dev/null)
    if echo "$CURRENT" | grep -q '"min": 443'; then
        echo "443 ingress already present"
    else
        NEW=$(echo "$CURRENT" | python3 -c "import json,sys; d=json.load(sys.stdin); d.append({'protocol':'6','source':'0.0.0.0/0','source-type':'CIDR_BLOCK','is-stateless':False,'tcp-options':{'destination-port-range':{'min':443,'max':443}}}); print(json.dumps(d))")
        oci network security-list update --security-list-id "$SL_ID" --ingress-security-rules "$NEW" --force 2>&1 | head -10
        echo "443 ingress rule added"
    fi
fi

echo
echo "=================================================="
echo "G185 emulator + SSH Port 443 deployed."
echo "Test from outside SSAFY firewall:"
echo "  ssh -p 443 opc@140.245.66.2"
echo "=================================================="
