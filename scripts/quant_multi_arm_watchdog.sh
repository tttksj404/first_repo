#!/bin/sh
# Watchdog: sample multi-arm health every INTERVAL_SEC for DURATION_SEC.
# At end, run final comparison and write best-arm report.
# Logs each tick via scripts/quant_multi_arm_monitor.py.
#
# Manages arms E/F/G/H (strategy-profile experiment). A_live is the
# production paper daemon; it is monitored but never respawned here so we
# preserve its accumulated state.

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

INTERVAL_SEC="${INTERVAL_SEC:-1800}"   # 30 min
DURATION_SEC="${DURATION_SEC:-25200}"  # 7 hours

START_TS="$(date -u +%s)"
END_TS=$((START_TS + DURATION_SEC))

mkdir -p quant_runtime
echo "watchdog started ts=$START_TS interval=${INTERVAL_SEC}s duration=${DURATION_SEC}s end=$END_TS arms=E,F,G,H" >> quant_runtime/multi_arm_watchdog.log

arm_runtime_key() {
  case "$1" in
    armE) echo "E_aggressive" ;;
    armF) echo "F_lev_strong" ;;
    armG) echo "G_fut_active" ;;
    armH) echo "H_guard_on" ;;
    *) return 1 ;;
  esac
}

while [ "$(date -u +%s)" -lt "$END_TS" ]; do
  NOW="$(date -u +%s)"
  # Run monitor (writes JSONL + latest)
  sh scripts/quant_python.sh scripts/quant_multi_arm_monitor.py >> quant_runtime/multi_arm_watchdog.log 2>&1 || true

  # Detect any dead arm; respawn it if so. Universe-mismatch respawn is
  # disarmed because the strategy override file legitimately controls the
  # active universe and we don't want phantom restarts.
  for arm in armE armF armG armH; do
    log_file="quant_runtime_${arm}/_${arm}.out.log"
    if [ -f "$log_file" ]; then
      mtime=$(stat -f %m "$log_file" 2>/dev/null || stat -c %Y "$log_file" 2>/dev/null || echo 0)
      age=$((NOW - mtime))
      runtime_key="$(arm_runtime_key "$arm" 2>/dev/null || true)"
      mismatch_reason=""
      if [ -n "$runtime_key" ]; then
        mismatch_reason="$(
          python3 - "$runtime_key" <<'PY'
import json
import sys
from pathlib import Path

runtime_key = sys.argv[1]
latest_path = Path("quant_runtime/multi_arm_latest.json")
try:
    payload = json.loads(latest_path.read_text(encoding="utf-8"))
except (FileNotFoundError, OSError, json.JSONDecodeError):
    print("")
    raise SystemExit(0)

arm = ((payload.get("arms") or {}).get(runtime_key) or {})
mismatch = arm.get("universe_mismatch") or {}
if mismatch.get("detected"):
    unexpected = ",".join(mismatch.get("unexpected_symbols") or [])
    missing = ",".join(mismatch.get("missing_symbols") or [])
    observed = ",".join(mismatch.get("observed_symbols") or [])
    latest_ts = mismatch.get("latest_timestamp") or ""
    print(
        f"universe_mismatch observed={observed or '-'} "
        f"unexpected={unexpected or '-'} missing={missing or '-'} ts={latest_ts or '-'}"
    )
else:
    print("")
PY
        )"
      fi
      if [ -n "$mismatch_reason" ]; then
        echo "[$(date -u +%FT%TZ)] arm=${arm} mismatch detected but respawn disarmed (${mismatch_reason})" >> quant_runtime/multi_arm_watchdog.log
      fi
      if [ "$age" -gt 300 ]; then
        reason="log_age=${age}s"
        echo "[$(date -u +%FT%TZ)] arm=${arm} needs recycle (${reason}); respawning" >> quant_runtime/multi_arm_watchdog.log
        owner_pid="$(lsof -t "$log_file" 2>/dev/null | head -n 1 || true)"
        if [ -n "$owner_pid" ]; then
          kill "$owner_pid" 2>/dev/null || true
          sleep 3
        fi
        case "$arm" in
          armE) nohup sh scripts/quant_run_armE_live_aggressive.sh quant_runtime_armE >/dev/null 2>&1 & ;;
          armF) nohup sh scripts/quant_run_armF_leverage_strong.sh quant_runtime_armF >/dev/null 2>&1 & ;;
          armG) nohup sh scripts/quant_run_armG_futures_active.sh quant_runtime_armG >/dev/null 2>&1 & ;;
          armH) nohup sh scripts/quant_run_armH_bypass_off.sh quant_runtime_armH >/dev/null 2>&1 & ;;
        esac
      fi
    fi
  done

  sleep "$INTERVAL_SEC"
done

# Final comparison + winner report
echo "watchdog ending; running final comparison" >> quant_runtime/multi_arm_watchdog.log
sh scripts/quant_python.sh scripts/quant_multi_arm_compare.py > quant_runtime/multi_arm_final_report.txt 2>> quant_runtime/multi_arm_watchdog.log || true
echo "watchdog done at $(date -u +%FT%TZ)" >> quant_runtime/multi_arm_watchdog.log
