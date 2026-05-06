#!/bin/bash
# Permanently stop low-priority paper emulators on the Oracle g185 VM.
#
# Safe to run more than once. It stops, disables, and masks the selected
# user-level systemd services so they do not come back after reboot.
set -euo pipefail

DEFAULT_SERVICES=(
  "g1165-emulator.service"
  "g129183-emulator.service"
  "g922_meme-emulator.service"
)

if [ "$#" -gt 0 ]; then
  SERVICES=("$@")
else
  SERVICES=("${DEFAULT_SERVICES[@]}")
fi

as_root_prepare_and_reexec() {
  local uid
  if ! id opc >/dev/null 2>&1; then
    echo "FATAL: user 'opc' not found. Run this on the Oracle VM." >&2
    exit 2
  fi

  uid="$(id -u opc)"
  loginctl enable-linger opc >/dev/null 2>&1 || true
  systemctl start "user@${uid}.service" >/dev/null 2>&1 || true

  if command -v runuser >/dev/null 2>&1; then
    exec runuser -u opc -- env \
      XDG_RUNTIME_DIR="/run/user/${uid}" \
      DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${uid}/bus" \
      bash "$0" "$@"
  fi

  if command -v su >/dev/null 2>&1; then
    exec su - opc -c "XDG_RUNTIME_DIR=/run/user/${uid} DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${uid}/bus bash '$0' $*"
  fi

  echo "FATAL: neither runuser nor su is available." >&2
  exit 3
}

if [ "$(id -u)" -eq 0 ]; then
  as_root_prepare_and_reexec "$@"
fi

uid="$(id -u)"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/${uid}}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

if ! command -v systemctl >/dev/null 2>&1; then
  echo "FATAL: systemctl not found." >&2
  exit 4
fi

echo "=== prune low-value emulators ==="
echo "user=$(id -un) uid=${uid}"
echo "runtime=${XDG_RUNTIME_DIR}"
echo

systemctl --user daemon-reload >/dev/null 2>&1 || true

for svc in "${SERVICES[@]}"; do
  echo "[prune] ${svc}"
  systemctl --user stop "$svc" >/dev/null 2>&1 || true
  systemctl --user disable "$svc" >/dev/null 2>&1 || true
  systemctl --user mask "$svc" >/dev/null 2>&1 || true

  active="$(systemctl --user is-active "$svc" 2>/dev/null || true)"
  enabled="$(systemctl --user is-enabled "$svc" 2>/dev/null || true)"
  printf '  active=%s enabled=%s\n' "${active:-unknown}" "${enabled:-unknown}"
done

echo
echo "=== remaining watched emulator services ==="
systemctl --user --no-pager --type=service --state=running \
  | grep -E 'g1165|g129183|g4692|g920_top7|g921_alts|g922_meme' || true

echo
echo "=== host pressure ==="
free -h || true
uptime || true

echo
echo "done"
