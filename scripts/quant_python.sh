#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
PRINT_ONLY=0

if [ "${1:-}" = "--print" ]; then
  PRINT_ONLY=1
  shift
fi

resolve_command() {
  candidate="$1"
  [ -n "$candidate" ] || return 1
  case "$candidate" in
    */*|*\\*)
      if [ -x "$candidate" ]; then
        printf '%s\n' "$candidate"
        return 0
      fi
      ;;
    *)
      resolved="$(command -v "$candidate" 2>/dev/null || true)"
      if [ -n "$resolved" ] && [ -x "$resolved" ]; then
        printf '%s\n' "$resolved"
        return 0
      fi
      ;;
  esac
  return 1
}

if RESOLVED="$(resolve_command "${QUANT_PYTHON_BIN:-}")"; then
  if [ "$PRINT_ONLY" = "1" ]; then
    printf '%s\n' "$RESOLVED"
    exit 0
  fi
  exec "$RESOLVED" "$@"
fi

if RESOLVED="$(resolve_command "${PYTHON_BIN:-}")"; then
  if [ "$PRINT_ONLY" = "1" ]; then
    printf '%s\n' "$RESOLVED"
    exit 0
  fi
  exec "$RESOLVED" "$@"
fi

for candidate in \
  "$REPO_ROOT/.venv/bin/python" \
  "$REPO_ROOT/venv/bin/python" \
  "$REPO_ROOT/.venv/Scripts/python.exe" \
  "$REPO_ROOT/venv/Scripts/python.exe" \
  python3 \
  python
do
  if RESOLVED="$(resolve_command "$candidate")"; then
    if [ "$PRINT_ONLY" = "1" ]; then
      printf '%s\n' "$RESOLVED"
      exit 0
    fi
    exec "$RESOLVED" "$@"
  fi
done

if command -v py >/dev/null 2>&1; then
  PY_LAUNCHER="$(command -v py)"
  if [ "$PRINT_ONLY" = "1" ]; then
    printf '%s -3\n' "$PY_LAUNCHER"
    exit 0
  fi
  exec "$PY_LAUNCHER" -3 "$@"
fi

printf '[BOOT] python interpreter not found. Set QUANT_PYTHON_BIN or install python3/python.\n' >&2
exit 1
