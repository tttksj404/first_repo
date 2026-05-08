#!/usr/bin/env bash
# mac_setup.sh - portable g185 SSH setup for a new Mac.
#
# Usage from a cloned repo:
#   bash scripts/oracle_recovery/mac_setup.sh
#
# This delegates to ensure_access.py so the Mac does not depend on stale
# hard-coded IPs. If the Mac cannot register its key directly, the script prints
# the exact one-line Cloud Shell command to enroll the Mac public key.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "${SCRIPT_DIR}/../.."

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "Python is required. Install Python 3, then rerun this script." >&2
  exit 1
fi

"$PY" scripts/oracle_recovery/ensure_access.py --repair
