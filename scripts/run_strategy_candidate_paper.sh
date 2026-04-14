#!/bin/sh
set -eu

usage() {
  cat <<'EOF'
usage:
  sh scripts/run_strategy_candidate_paper.sh start  <candidate-json> [output-base]
  sh scripts/run_strategy_candidate_paper.sh status <candidate-json> [output-base]
  sh scripts/run_strategy_candidate_paper.sh report <candidate-json> [output-base]
  sh scripts/run_strategy_candidate_paper.sh stop   <candidate-json> [output-base]

candidate-json examples:
  quant_runtime/artifacts/candidate_overrides/strategy_override.carry_top1.json
  quant_runtime/artifacts/candidate_overrides/rotation_review_top1.json
EOF
}

cmd="${1:-}"
candidate_json="${2:-}"
output_base_arg="${3:-}"

if [ -z "$cmd" ] || [ -z "$candidate_json" ]; then
  usage >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CANDIDATE_PATH="$ROOT/$candidate_json"
if [ ! -f "$CANDIDATE_PATH" ]; then
  echo "candidate not found: $candidate_json" >&2
  exit 1
fi

resolve_meta() {
  python3 - <<'PY' "$CANDIDATE_PATH" "$output_base_arg"
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
requested_output = sys.argv[2].strip()
payload = json.loads(path.read_text(encoding='utf-8'))
stem = path.stem
family = str(payload.get('family') or payload.get('_candidate_meta', {}).get('family') or ('carry' if 'carry' in stem else 'rotation'))
rank = int(payload.get('rank') or payload.get('_candidate_meta', {}).get('rank') or 1)
default_output = f"quant_runtime_{family}_top{rank}"
output_base = requested_output or default_output
env = dict(payload.get('env') or {})
universe = env.get('UNIVERSE_SYMBOLS', '')
if not universe and isinstance(payload.get('universe'), list):
    universe = ",".join(str(x) for x in payload['universe'])
if family == 'carry' and not universe:
    cfg = dict(payload.get('funding_rate_strategy') or {})
    universe = ",".join(str(x) for x in cfg.get('symbols', []) if str(x))
print(json.dumps({
    "family": family,
    "rank": rank,
    "output_base": output_base,
    "universe": universe,
}))
PY
}

meta="$(resolve_meta)"
family="$(printf '%s' "$meta" | python3 -c 'import json,sys; print(json.load(sys.stdin)["family"])')"
output_base="$(printf '%s' "$meta" | python3 -c 'import json,sys; print(json.load(sys.stdin)["output_base"])')"
universe="$(printf '%s' "$meta" | python3 -c 'import json,sys; print(json.load(sys.stdin)["universe"])')"
pid_file="$ROOT/$output_base/paper_daemon.pid"
log_file="$ROOT/$output_base/paper_candidate.log"

is_running() {
  pid="$1"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

read_pid() {
  awk 'NR==1 { print $1; exit }' "$pid_file" 2>/dev/null || true
}

case "$cmd" in
  start)
    mkdir -p "$ROOT/$output_base"
    existing_pid="$(read_pid)"
    if is_running "$existing_pid"; then
      echo "[SKIP] already running pid=$existing_pid output_base=$output_base"
      exit 0
    fi
    (
      export STRATEGY_OVERRIDE_PATH="$candidate_json"
      if [ -n "$universe" ]; then
        export UNIVERSE_SYMBOLS="$universe"
      fi
      exec sh "$ROOT/scripts/quant_run_forever.sh" "$output_base"
    ) >>"$log_file" 2>&1 &
    pid="$!"
    printf '%s\n' "$pid" >"$pid_file"
    echo "[START] family=$family output_base=$output_base pid=$pid candidate=$candidate_json"
    ;;
  status)
    pid="$(read_pid)"
    if is_running "$pid"; then
      echo "[RUNNING] family=$family output_base=$output_base pid=$pid candidate=$candidate_json"
      sh "$ROOT/scripts/quant_status.sh" "$output_base"
    else
      echo "[STOPPED] family=$family output_base=$output_base candidate=$candidate_json"
    fi
    ;;
  report)
    sh "$ROOT/scripts/quant_report.sh" "$output_base"
    ;;
  stop)
    pid="$(read_pid)"
    if is_running "$pid"; then
      kill "$pid" 2>/dev/null || true
      sleep 1
      if is_running "$pid"; then
        kill -9 "$pid" 2>/dev/null || true
      fi
      echo "[STOP] family=$family output_base=$output_base pid=$pid candidate=$candidate_json"
    else
      echo "[STOP] not running output_base=$output_base candidate=$candidate_json"
    fi
    rm -f "$pid_file"
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac
