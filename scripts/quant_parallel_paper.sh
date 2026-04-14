#!/bin/sh
set -eu

usage() {
  cat <<'EOF'
usage:
  sh scripts/quant_parallel_paper.sh start  <profiles-file>
  sh scripts/quant_parallel_paper.sh status <profiles-file>
  sh scripts/quant_parallel_paper.sh judge  <profiles-file>
  sh scripts/quant_parallel_paper.sh stop   <profiles-file>

profiles-file format (pipe-delimited):
  name|output_base|strategy_profile|universe_symbols|strategy_override_path

example:
  core-majors|quant_runtime_a|active|BTCUSDT,ETHUSDT,SOLUSDT|
  alt-fast|quant_runtime_b|live-ultra-aggressive|DOGEUSDT,TRXUSDT|quant_runtime_b/artifacts/strategy_override.approved.json

notes:
  - Lines starting with # are ignored.
  - Empty strategy_override_path defaults to <output_base>/artifacts/strategy_override.approved.json

judge thresholds (env overrides):
  QUANT_JUDGE_MIN_DECISIONS=60
  QUANT_JUDGE_REQUIRE_LIVE_ORDERS=1
  QUANT_JUDGE_MIN_LIVE_ORDERS=1
  QUANT_JUDGE_MAX_STALE_SECONDS=1800
  QUANT_JUDGE_MAX_TOP_REJECTION_SHARE=0.90
EOF
}

trim() {
  printf '%s' "$1" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

is_running() {
  pid="$1"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

read_pid() {
  pid_file="$1"
  awk 'NR==1 { print $1; exit }' "$pid_file" 2>/dev/null || true
}

run_status_snapshot() {
  output_base="$1"
  python3 - <<'PY' "$output_base"
import json
import sys
from pathlib import Path

base = Path(sys.argv[1])
state = base / "output" / "paper-live-shell" / "latest" / "summary.state.json"
if not state.exists():
    print("updated_at=- decision_count=- live_order_count=- tested_order_count=-")
    raise SystemExit(0)
try:
    payload = json.loads(state.read_text(encoding="utf-8"))
except Exception:
    print("updated_at=ERR decision_count=ERR live_order_count=ERR tested_order_count=ERR")
    raise SystemExit(0)
print(
    "updated_at={updated} decision_count={dec} live_order_count={live} tested_order_count={tested}".format(
        updated=payload.get("updated_at", "-"),
        dec=payload.get("decision_count", "-"),
        live=payload.get("live_order_count", "-"),
        tested=payload.get("tested_order_count", "-"),
    )
)
PY
}

start_one() {
  name="$1"
  output_base="$2"
  strategy_profile="$3"
  universe_symbols="$4"
  override_path="$5"

  mkdir -p "$output_base"
  pid_file="$output_base/paper_daemon.pid"
  log_file="$output_base/paper_parallel.log"

  existing_pid="$(read_pid "$pid_file")"
  if is_running "$existing_pid"; then
    printf '[SKIP] %s already running pid=%s output_base=%s\n' "$name" "$existing_pid" "$output_base"
    return 0
  fi

  if [ -z "$override_path" ]; then
    override_path="$output_base/artifacts/strategy_override.approved.json"
  fi
  macro_inputs_path="$output_base/artifacts/news_macro_inputs.json"
  if [ ! -f "$macro_inputs_path" ]; then
    mkdir -p "$output_base/artifacts"
    cp quant_binance/examples/macro_inputs.sample.json "$macro_inputs_path"
  fi

  printf '[START] %s output_base=%s profile=%s symbols=%s\n' "$name" "$output_base" "$strategy_profile" "$universe_symbols"
  (
    export STRATEGY_PROFILE="$strategy_profile"
    export UNIVERSE_SYMBOLS="$universe_symbols"
    export STRATEGY_OVERRIDE_PATH="$override_path"
    export MACRO_INPUTS_PATH="$macro_inputs_path"
    exec sh scripts/quant_run_forever.sh "$output_base"
  ) >>"$log_file" 2>&1 &
  pid="$!"
  printf '%s\n' "$pid" >"$pid_file"
  printf '[OK] %s pid=%s log=%s\n' "$name" "$pid" "$log_file"
}

status_one() {
  name="$1"
  output_base="$2"
  strategy_profile="$3"
  universe_symbols="$4"

  pid_file="$output_base/paper_daemon.pid"
  pid="$(read_pid "$pid_file")"
  if is_running "$pid"; then
    state="running"
  else
    state="stopped"
  fi
  snapshot="$(run_status_snapshot "$output_base")"
  printf '[%s] %s pid=%s output_base=%s profile=%s symbols=%s %s\n' \
    "$state" "$name" "${pid:--}" "$output_base" "$strategy_profile" "$universe_symbols" "$snapshot"
}

stop_one() {
  name="$1"
  output_base="$2"

  pid_file="$output_base/paper_daemon.pid"
  pid="$(read_pid "$pid_file")"
  if is_running "$pid"; then
    kill "$pid" 2>/dev/null || true
    sleep 1
    if is_running "$pid"; then
      kill -9 "$pid" 2>/dev/null || true
    fi
    printf '[STOP] %s pid=%s output_base=%s\n' "$name" "$pid" "$output_base"
  else
    printf '[STOP] %s not running output_base=%s\n' "$name" "$output_base"
  fi
  rm -f "$pid_file"
}

judge_one() {
  name="$1"
  output_base="$2"
  strategy_profile="$3"
  universe_symbols="$4"

  min_decisions="${QUANT_JUDGE_MIN_DECISIONS:-60}"
  require_live_orders="${QUANT_JUDGE_REQUIRE_LIVE_ORDERS:-1}"
  min_live_orders="${QUANT_JUDGE_MIN_LIVE_ORDERS:-1}"
  max_stale_seconds="${QUANT_JUDGE_MAX_STALE_SECONDS:-1800}"
  max_top_rejection_share="${QUANT_JUDGE_MAX_TOP_REJECTION_SHARE:-0.90}"

  if python3 - <<'PY' \
    "$name" \
    "$output_base" \
    "$strategy_profile" \
    "$universe_symbols" \
    "$min_decisions" \
    "$require_live_orders" \
    "$min_live_orders" \
    "$max_stale_seconds" \
    "$max_top_rejection_share"
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

name = sys.argv[1]
output_base = Path(sys.argv[2])
profile = sys.argv[3]
symbols = sys.argv[4]
min_decisions = int(sys.argv[5])
require_live_orders = int(sys.argv[6]) == 1
min_live_orders = int(sys.argv[7])
max_stale_seconds = int(sys.argv[8])
max_top_rejection_share = float(sys.argv[9])

state_path = output_base / "output" / "paper-live-shell" / "latest" / "summary.state.json"
summary_path = output_base / "output" / "paper-live-shell" / "latest" / "summary.json"

if not state_path.exists() or not summary_path.exists():
    print(
        f"[FAIL] {name} output_base={output_base} profile={profile} symbols={symbols} "
        f"reason=missing_latest_artifacts"
    )
    raise SystemExit(1)

try:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
except Exception as exc:
    print(
        f"[FAIL] {name} output_base={output_base} profile={profile} symbols={symbols} "
        f"reason=invalid_json error={exc}"
    )
    raise SystemExit(1)

def as_int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(value)
    except Exception:
        return default

decision_count = as_int(state.get("decision_count", summary.get("decision_count", 0)), 0)
live_order_count = as_int(state.get("live_order_count", summary.get("live_order_count", 0)), 0)
tested_order_count = as_int(state.get("tested_order_count", summary.get("tested_order_count", 0)), 0)
closed_trade_count = as_int(state.get("closed_trade_count", summary.get("closed_trade_count", 0)), 0)
updated_at_raw = state.get("updated_at") or summary.get("updated_at")
kill_switch = state.get("kill_switch") or summary.get("kill_switch") or {}
kill_armed = bool(dict(kill_switch).get("armed", False))

top_rejections = dict(summary.get("top_rejection_reasons", {}) or {})
top_reason = "-"
top_reason_count = 0
top_reason_share = 0.0
if decision_count > 0 and top_rejections:
    top_reason, top_reason_count = max(
        top_rejections.items(),
        key=lambda kv: int(kv[1] or 0),
    )
    top_reason_count = as_int(top_reason_count, 0)
    top_reason_share = top_reason_count / max(decision_count, 1)

now = datetime.now(tz=timezone.utc)
age_seconds = None
if isinstance(updated_at_raw, str) and updated_at_raw:
    text = updated_at_raw.replace("Z", "+00:00")
    try:
        updated = datetime.fromisoformat(text)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        age_seconds = max((now - updated).total_seconds(), 0.0)
    except Exception:
        age_seconds = None

fail_reasons = []
if kill_armed:
    fail_reasons.append("kill_switch_armed")
if age_seconds is None:
    fail_reasons.append("missing_updated_at")
elif age_seconds > max_stale_seconds:
    fail_reasons.append(f"stale_state({int(age_seconds)}s)")
if decision_count < min_decisions:
    fail_reasons.append(f"decision_count<{min_decisions}")
if require_live_orders and live_order_count < min_live_orders:
    fail_reasons.append(f"live_order_count<{min_live_orders}")
if decision_count >= min_decisions and top_reason_share > max_top_rejection_share:
    fail_reasons.append(
        f"rejection_concentration>{max_top_rejection_share:.2f}"
    )

status = "PASS" if not fail_reasons else "FAIL"
print(
    f"[{status}] {name} output_base={output_base} profile={profile} symbols={symbols} "
    f"decision_count={decision_count} live_order_count={live_order_count} "
    f"tested_order_count={tested_order_count} closed_trade_count={closed_trade_count} "
    f"top_rejection={top_reason}:{top_reason_count} ({top_reason_share:.2%}) "
    f"updated_age_seconds={('-' if age_seconds is None else int(age_seconds))} "
    f"kill_switch_armed={kill_armed} "
    f"reasons={','.join(fail_reasons) if fail_reasons else 'ok'}"
)

raise SystemExit(0 if status == "PASS" else 1)
PY
  then
    return 0
  else
    return 1
  fi
}

run_for_profiles() {
  action="$1"
  profiles_file="$2"
  has_fail="0"

  if [ ! -f "$profiles_file" ]; then
    echo "profiles file not found: $profiles_file" >&2
    exit 1
  fi

  while IFS='|' read -r raw_name raw_output raw_profile raw_symbols raw_override _rest; do
    line="$(trim "${raw_name}${raw_output}${raw_profile}${raw_symbols}${raw_override}")"
    if [ -z "$line" ]; then
      continue
    fi
    first_char="$(printf '%s' "$(trim "$raw_name")" | cut -c1)"
    if [ "$first_char" = "#" ]; then
      continue
    fi

    name="$(trim "$raw_name")"
    output_base="$(trim "$raw_output")"
    strategy_profile="$(trim "$raw_profile")"
    universe_symbols="$(trim "$raw_symbols")"
    override_path="$(trim "$raw_override")"

    if [ -z "$name" ] || [ -z "$output_base" ] || [ -z "$strategy_profile" ] || [ -z "$universe_symbols" ]; then
      echo "invalid profile row: $raw_name|$raw_output|$raw_profile|$raw_symbols|$raw_override" >&2
      exit 1
    fi

    case "$action" in
      start)  start_one "$name" "$output_base" "$strategy_profile" "$universe_symbols" "$override_path" ;;
      status) status_one "$name" "$output_base" "$strategy_profile" "$universe_symbols" ;;
      judge)
        if ! judge_one "$name" "$output_base" "$strategy_profile" "$universe_symbols"; then
          has_fail="1"
        fi
        ;;
      stop)   stop_one "$name" "$output_base" ;;
      *) echo "unsupported action: $action" >&2; exit 1 ;;
    esac
  done <"$profiles_file"
  if [ "$action" = "judge" ] && [ "$has_fail" = "1" ]; then
    exit 1
  fi
}

ACTION="${1:-}"
PROFILES_FILE="${2:-scripts/quant_parallel_profiles.example.txt}"

case "$ACTION" in
  start|status|judge|stop) run_for_profiles "$ACTION" "$PROFILES_FILE" ;;
  *) usage; exit 1 ;;
esac
