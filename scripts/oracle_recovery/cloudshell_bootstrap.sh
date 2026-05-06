#!/bin/bash
# Install a persistent Cloud Shell helper for g185 operations.
#
# Usage in Oracle Cloud Shell:
#   bash cloudshell_bootstrap.sh
#   g185ctl discover
#   g185ctl status
#   g185ctl prune
set -euo pipefail

BIN_DIR="${HOME}/bin"
CTL="${BIN_DIR}/g185ctl"

mkdir -p "$BIN_DIR"

cat > "$CTL" <<'G185CTL'
#!/bin/bash
set -euo pipefail

ENV_FILE="${HOME}/.g185ctl.env"
DEFAULT_REGION="ap-chuncheon-1"
DEFAULT_PATTERN="${G185_PATTERN:-g185}"

die() {
  echo "FATAL: $*" >&2
  exit 1
}

need_oci() {
  command -v oci >/dev/null 2>&1 || die "oci CLI not found. Run this in Oracle Cloud Shell."
}

load_env() {
  [ -f "$ENV_FILE" ] && . "$ENV_FILE"
  REGION="${REGION:-$DEFAULT_REGION}"
  SSH_USER="${SSH_USER:-opc}"
  SSH_PORT="${SSH_PORT:-443}"
}

save_env() {
  umask 077
  cat > "$ENV_FILE" <<EOF
INST_ID="${INST_ID}"
COMP_ID="${COMP_ID}"
REGION="${REGION}"
SSH_USER="${SSH_USER:-opc}"
SSH_IP="${SSH_IP:-}"
SSH_PORT="${SSH_PORT:-443}"
DISPLAY_NAME="${DISPLAY_NAME:-}"
EOF
  echo "[saved] $ENV_FILE"
}

show_env() {
  load_env
  echo "INST_ID=${INST_ID:-}"
  echo "COMP_ID=${COMP_ID:-}"
  echo "REGION=${REGION:-}"
  echo "SSH_USER=${SSH_USER:-}"
  echo "SSH_IP=${SSH_IP:-}"
  echo "SSH_PORT=${SSH_PORT:-}"
  echo "DISPLAY_NAME=${DISPLAY_NAME:-}"
}

discover() {
  need_oci
  local pattern="${1:-$DEFAULT_PATTERN}"
  REGION="${REGION:-$DEFAULT_REGION}"
  echo "[discover] region=$REGION pattern=$pattern"

  local tmp
  tmp="$(mktemp)"
  oci search resource structured-search \
    --region "$REGION" \
    --query-text "query instance resources where lifecycleState = 'RUNNING'" \
    --output json > "$tmp"

  local selected
  selected="$(python3 - "$tmp" "$pattern" <<'PY'
import json, re, sys
path, pattern = sys.argv[1], sys.argv[2]
data = json.load(open(path))
items = data.get("data", {}).get("items", [])
rx = re.compile(pattern, re.I)
matches = []
for item in items:
    name = item.get("display-name") or item.get("displayName") or ""
    if rx.search(name):
        matches.append(item)
if not matches:
    print("")
    print("No matching RUNNING instances found.", file=sys.stderr)
    print("Visible RUNNING instances:", file=sys.stderr)
    for item in items:
        print(f"- {item.get('display-name') or item.get('displayName')} {item.get('identifier')} {item.get('compartment-id')}", file=sys.stderr)
    sys.exit(2)
def score(item):
    name = (item.get("display-name") or item.get("displayName") or "").lower()
    return (
        0 if "g185-restored" in name else 1 if name == "g185" else 2 if "g185" in name else 3,
        name,
    )
matches.sort(key=score)
item = matches[0]
print("\t".join([
    item.get("identifier") or "",
    item.get("compartment-id") or "",
    item.get("display-name") or item.get("displayName") or "",
]))
PY
)"
  rm -f "$tmp"

  [ -n "$selected" ] || exit 2
  INST_ID="$(printf '%s' "$selected" | awk -F '\t' '{print $1}')"
  COMP_ID="$(printf '%s' "$selected" | awk -F '\t' '{print $2}')"
  DISPLAY_NAME="$(printf '%s' "$selected" | awk -F '\t' '{print $3}')"
  SSH_USER="${SSH_USER:-opc}"
  SSH_PORT="${SSH_PORT:-443}"

  SSH_IP="$(oci compute instance list-vnics \
    --region "$REGION" \
    --instance-id "$INST_ID" \
    --query 'data[0]."public-ip"' \
    --raw-output 2>/dev/null || true)"
  [ "$SSH_IP" = "null" ] && SSH_IP=""

  echo "[selected] $DISPLAY_NAME"
  echo "  instance=$INST_ID"
  echo "  compartment=$COMP_ID"
  echo "  public_ip=${SSH_IP:-unknown}"
  save_env
  write_ssh_config || true
}

write_ssh_config() {
  load_env
  [ -n "${SSH_IP:-}" ] || return 0
  mkdir -p "${HOME}/.ssh"
  chmod 700 "${HOME}/.ssh"
  touch "${HOME}/.ssh/config"
  chmod 600 "${HOME}/.ssh/config"

  local tmp start end
  tmp="$(mktemp)"
  start="# === g185ctl managed start ==="
  end="# === g185ctl managed end ==="
  awk -v start="$start" -v end="$end" '
    $0 == start {skip=1; next}
    $0 == end {skip=0; next}
    !skip {print}
  ' "${HOME}/.ssh/config" > "$tmp"
  cat >> "$tmp" <<EOF

$start
Host g185
    HostName ${SSH_IP}
    Port ${SSH_PORT}
    User ${SSH_USER}
    IdentityFile ~/.ssh/id_ed25519
    StrictHostKeyChecking accept-new
    ControlMaster auto
    ControlPath ~/.ssh/cm-%r@%h-%p
    ControlPersist 300
    ConnectTimeout 30
    ServerAliveInterval 30
    ServerAliveCountMax 3
$end
EOF
  mv "$tmp" "${HOME}/.ssh/config"
  chmod 600 "${HOME}/.ssh/config"
  echo "[ssh-config] Host g185 -> ${SSH_IP}:${SSH_PORT}"
}

require_target() {
  load_env
  [ -n "${INST_ID:-}" ] && [ -n "${COMP_ID:-}" ] || die "No target saved. Run: g185ctl discover"
}

agent_run_text() {
  need_oci
  require_target
  local name="$1"
  local text="$2"
  local timeout="${3:-180}"
  local body cmd_id state
  body="$(mktemp)"
  python3 - "$body" "$COMP_ID" "$INST_ID" "$name" "$timeout" "$text" <<'PY'
import json, sys
path, comp, inst, name, timeout, text = sys.argv[1:]
body = {
    "compartmentId": comp,
    "executionTimeOutInSeconds": int(timeout),
    "displayName": name,
    "target": {"instanceId": inst},
    "content": {
        "source": {"sourceType": "TEXT", "text": text},
        "output": {"outputType": "TEXT"},
    },
}
with open(path, "w") as f:
    json.dump(body, f)
PY

  set +e
  cmd_id="$(oci instance-agent command create \
    --region "$REGION" \
    --from-json "file://${body}" \
    --timeout-in-seconds 60 \
    --query 'data.id' \
    --raw-output 2>&1)"
  local rc=$?
  set -e
  rm -f "$body"
  if [ "$rc" -ne 0 ]; then
    echo "$cmd_id" >&2
    die "Instance Agent command create failed. Check target with: g185ctl discover"
  fi
  [ -n "$cmd_id" ] && [ "$cmd_id" != "null" ] || die "empty command id"
  echo "[agent] command=$cmd_id"

  for _ in $(seq 1 36); do
    state="$(oci instance-agent command-execution get \
      --region "$REGION" \
      --instance-id "$INST_ID" \
      --instance-agent-command-id "$cmd_id" \
      --query 'data."lifecycle-state"' \
      --raw-output 2>/dev/null || true)"
    echo "[agent] state=${state:-pending}"
    case "$state" in
      SUCCEEDED|FAILED|TIMED_OUT|CANCELED) break ;;
    esac
    sleep 5
  done

  echo
  echo "=== output ==="
  oci instance-agent command-execution get \
    --region "$REGION" \
    --instance-id "$INST_ID" \
    --instance-agent-command-id "$cmd_id" \
    --query 'data."content"."output"."text"' \
    --raw-output 2>/dev/null || true
}

status_cmd() {
  cat <<'SH'
set -u
echo "=== host ==="
hostname
date -Is
uptime || true
free -h || true
df -h / /home /tmp 2>/dev/null || true
echo
echo "=== watched user services ==="
UID_OPC="$(id -u opc 2>/dev/null || echo 1000)"
systemctl start "user@${UID_OPC}.service" >/dev/null 2>&1 || true
runuser -u opc -- env XDG_RUNTIME_DIR="/run/user/${UID_OPC}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${UID_OPC}/bus" bash -lc '
systemctl --user --no-pager --type=service --state=running | grep -E "g1165|g129183|g4692|g920_top7|g921_alts|g922_meme" || true
echo
for d in ~/g1165 ~/g129183 ~/g4692 ~/g920_top7 ~/g921_alts ~/g922_meme; do
  [ -f "$d/runtime/state.json" ] || continue
  echo "## $d/runtime/state.json"
  python3 - "$d/runtime/state.json" <<PY
import json, sys
s=json.load(open(sys.argv[1]))
positions=s.get("positions") or s.get("open_positions") or {}
open_n=len(positions) if hasattr(positions, "__len__") else 0
print("updated=", s.get("updated_at") or s.get("last_cycle") or s.get("last_signal_check"))
print("last_error=", s.get("last_error"))
print("open=", open_n, "pnl=", s.get("cumulative_pnl_usd"), "closed=", s.get("closed_count", len(s.get("closed_trades", []))))
PY
done
'
SH
}

prune_cmd() {
  cat <<'SH'
set -e
UID_OPC="$(id -u opc)"
loginctl enable-linger opc >/dev/null 2>&1 || true
systemctl start "user@${UID_OPC}.service" >/dev/null 2>&1 || true
runuser -u opc -- env XDG_RUNTIME_DIR="/run/user/${UID_OPC}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${UID_OPC}/bus" bash -lc '
set -e
SERVICES="g1165-emulator.service g129183-emulator.service g922_meme-emulator.service"
systemctl --user daemon-reload >/dev/null 2>&1 || true
for svc in $SERVICES; do
  echo "[prune] $svc"
  systemctl --user stop "$svc" >/dev/null 2>&1 || true
  systemctl --user disable "$svc" >/dev/null 2>&1 || true
  systemctl --user mask "$svc" >/dev/null 2>&1 || true
  echo "  active=$(systemctl --user is-active "$svc" 2>/dev/null || true) enabled=$(systemctl --user is-enabled "$svc" 2>/dev/null || true)"
done
echo
echo "=== remaining ==="
systemctl --user --no-pager --type=service --state=running | grep -E "g1165|g129183|g4692|g920_top7|g921_alts|g922_meme" || true
echo
free -h || true
uptime || true
'
SH
}

recover_cmd() {
  cat <<'SH'
set -u
echo "=== restart ssh services ==="
systemctl restart sshd 2>/dev/null || systemctl restart ssh 2>/dev/null || true
systemctl is-active sshd 2>/dev/null || systemctl is-active ssh 2>/dev/null || true
echo
echo "=== pressure ==="
free -h || true
uptime || true
SH
}

ssh_cmd() {
  load_env
  [ -n "${SSH_IP:-}" ] || die "No SSH_IP saved. Run: g185ctl discover"
  exec ssh -p "${SSH_PORT:-443}" "${SSH_USER:-opc}@${SSH_IP}" "$@"
}

usage() {
  cat <<'EOF'
g185ctl - persistent Cloud Shell helper for Oracle g185

Commands:
  g185ctl discover [pattern]  Find RUNNING instance, save ~/.g185ctl.env, update SSH alias.
  g185ctl env                 Show saved target.
  g185ctl status              Run status through OCI Instance Agent.
  g185ctl prune               Stop+disable+mask low-value emulators through OCI Instance Agent.
  g185ctl recover             Restart sshd through OCI Instance Agent.
  g185ctl ssh [cmd...]        SSH to saved public IP on port 443.
  g185ctl ssh-config          Rewrite ~/.ssh/config Host g185 from saved env.
EOF
}

cmd="${1:-help}"
shift || true

case "$cmd" in
  discover) discover "${1:-$DEFAULT_PATTERN}" ;;
  env) show_env ;;
  status) agent_run_text "g185-status" "$(status_cmd)" 180 ;;
  prune) agent_run_text "g185-prune-low-value-emulators" "$(prune_cmd)" 180 ;;
  recover) agent_run_text "g185-restart-sshd" "$(recover_cmd)" 120 ;;
  ssh) ssh_cmd "$@" ;;
  ssh-config) write_ssh_config ;;
  help|-h|--help) usage ;;
  *) usage; exit 2 ;;
esac
G185CTL

chmod 700 "$CTL"

case ":${PATH}:" in
  *":${BIN_DIR}:"*) ;;
  *)
    if [ -f "${HOME}/.bashrc" ]; then
      grep -q 'export PATH="$HOME/bin:$PATH"' "${HOME}/.bashrc" 2>/dev/null || \
        echo 'export PATH="$HOME/bin:$PATH"' >> "${HOME}/.bashrc"
    fi
    export PATH="$BIN_DIR:$PATH"
    ;;
esac

echo "[installed] $CTL"
echo
"$CTL" help
echo
echo "Next:"
echo "  g185ctl discover"
echo "  g185ctl status"
echo "  g185ctl prune"
