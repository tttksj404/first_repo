#!/bin/bash
# 코인 매매 프로그램 정기 전수조사 + 자동 수정
# crontab: 17 0,2,4,6,9,12,14,16,18 * * * ...

set -uo pipefail
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
REPO="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
RUNTIME="${QUANT_HEALTH_AUDIT_RUNTIME:-$REPO/quant_runtime}"
PYTHON="$SCRIPT_DIR/quant_python.sh"
CLAUDE="${CLAUDE_BIN:-$(command -v claude 2>/dev/null || true)}"
chmod +x "$PYTHON" 2>/dev/null || true
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S %Z')
DISABLE_AUTOFIX="${QUANT_HEALTH_AUDIT_DISABLE_AUTOFIX:-0}"
ALLOW_RESTART="${QUANT_HEALTH_AUDIT_ALLOW_RESTART:-0}"

RUNTIME_BASENAME="$(basename "$RUNTIME")"
SUPERVISOR_LOG="$RUNTIME/live_supervisor.log"
PAPER50_MODE=0
case "$RUNTIME_BASENAME" in
    quant_runtime_paper50*|*paper50*)
        PAPER50_MODE=1
        ;;
esac
if [ "$PAPER50_MODE" = "1" ] && [ -f "$RUNTIME/_paper50.out.log" ]; then
    SUPERVISOR_LOG="$RUNTIME/_paper50.out.log"
elif [ ! -f "$SUPERVISOR_LOG" ] && [ -f "$RUNTIME/_paper50.out.log" ]; then
    SUPERVISOR_LOG="$RUNTIME/_paper50.out.log"
    PAPER50_MODE=1
fi
OUTPUT_MODE_ROOT="$RUNTIME/output/paper-live-shell"
FORENSICS_ROOT="$OUTPUT_MODE_ROOT"
if [ -d "$RUNTIME/forensics" ]; then
    FORENSICS_ROOT="$RUNTIME/forensics"
fi
SUMMARY_ROOT="$OUTPUT_MODE_ROOT/latest"
HEALTH_STATE_PATH="$RUNTIME/live_supervisor_health.json"

read_health_state() {
    [ -f "$HEALTH_STATE_PATH" ] || return 1
    "$PYTHON" - "$HEALTH_STATE_PATH" <<'PY' 2>/dev/null
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
for key in ("status", "reason", "summary"):
    value = payload.get(key, "")
    print("" if value is None else str(value))
PY
}

file_age_seconds() {
    "$PYTHON" - "$1" <<'PY' 2>/dev/null
from datetime import datetime, timezone
from pathlib import Path
import sys

path = Path(sys.argv[1])
if not path.exists():
    raise SystemExit(1)
age = (datetime.now(tz=timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)).total_seconds()
print(f"{age:.0f}")
PY
}

fresh_heartbeat_log() {
    [ -f "$SUPERVISOR_LOG" ] || return 1
    age="$(file_age_seconds "$SUPERVISOR_LOG" || echo 999999)"
    [ "${age:-999999}" -le "${1:-900}" ] || return 1
    tail -500 "$SUPERVISOR_LOG" | grep "HEARTBEAT" >/dev/null
}

slot_pid() {
    if [ -f "$1" ]; then
        awk 'NR==1 {print $1}' "$1" 2>/dev/null || true
    fi
}

pid_is_visible() {
    pid="$1"
    case "$pid" in
        ''|*[!0-9]*) return 1 ;;
    esac
    if kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    if command -v lsof >/dev/null 2>&1 && lsof -a -p "$pid" -d cwd >/dev/null 2>&1; then
        return 0
    fi
    if ps -p "$pid" >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

pgrep_count() {
    pattern="$1"
    count="$(pgrep -f "$pattern" 2>/dev/null | wc -l | tr -d ' ')"
    printf '%s' "${count:-0}"
}

clear_live_stop_files() {
    if [ "$ALLOW_RESTART" = "1" ]; then
        rm -f "$REPO/scripts/_supervisor_stop" "$REPO/scripts/_safety_guardian_stop"
    fi
}

live_stop_requested() {
    for stop_file in "$REPO/scripts/_supervisor_stop" "$REPO/scripts/_safety_guardian_stop"; do
        [ -f "$stop_file" ] && grep -qi 'stop' "$stop_file" 2>/dev/null && return 0
    done
    return 1
}

health_state_indicates_intentional_stop() {
    [ "${HEALTH_STATUS:-}" = "stopped" ] || return 1
    case "${HEALTH_REASON:-}" in
        supervisor_stop_requested|stopped_by_quant_stop)
            return 0
            ;;
    esac
    return 1
}

live_stop_state_applies() {
    [ "$PAPER50_MODE" != "1" ]
}

describe_stop_requested() {
    case "${STOP_REQUESTED_SOURCE:-}" in
        stop_sentinel)
            printf '%s' "stop sentinel present"
            ;;
        health_state)
            printf '%s' "persisted stop health present"
            ;;
        *)
            printf '%s' "intentional stop detected"
            ;;
    esac
}

latest_child_pid_from_log() {
    if [ -f "$SUPERVISOR_LOG" ]; then
        grep -a "started child pid=" "$SUPERVISOR_LOG" \
            | sed -n 's/.*started child pid=\([0-9][0-9]*\).*/\1/p' \
            | tail -1
    fi
}

echo "============================================"
echo "[HEALTH_AUDIT] $TIMESTAMP"
echo "============================================"

WARNINGS=0
CRITICALS=0
ISSUES=""
HEALTH_STATE_OUTPUT="$(read_health_state || true)"
HEALTH_STATUS="$(printf '%s\n' "$HEALTH_STATE_OUTPUT" | sed -n '1p')"
HEALTH_REASON="$(printf '%s\n' "$HEALTH_STATE_OUTPUT" | sed -n '2p')"
HEALTH_SUMMARY="$(printf '%s\n' "$HEALTH_STATE_OUTPUT" | sed -n '3p')"
STOP_REQUESTED=0
STOP_REQUESTED_SOURCE=""
if live_stop_state_applies && live_stop_requested; then
    STOP_REQUESTED=1
    STOP_REQUESTED_SOURCE="stop_sentinel"
elif live_stop_state_applies && health_state_indicates_intentional_stop; then
    STOP_REQUESTED=1
    STOP_REQUESTED_SOURCE="health_state"
fi

warn() { echo "  WARNING: $1"; WARNINGS=$((WARNINGS+1)); ISSUES="$ISSUES [W] $1"; }
crit() { echo "  CRITICAL: $1"; CRITICALS=$((CRITICALS+1)); ISSUES="$ISSUES [C] $1"; }
warn_unless_stopped() {
    if [ "$STOP_REQUESTED" = "1" ]; then
        echo "  STOPPED: $1"
    else
        warn "$1"
    fi
}
crit_unless_stopped() {
    if [ "$STOP_REQUESTED" = "1" ]; then
        echo "  STOPPED: $1"
    else
        crit "$1"
    fi
}

record_report_line() {
    line="$1"
    case "$line" in
        "  WARNING: "*)
            WARNINGS=$((WARNINGS+1))
            ISSUES="$ISSUES [W] ${line#  WARNING: }"
            ;;
        "  CRITICAL: "*)
            CRITICALS=$((CRITICALS+1))
            ISSUES="$ISSUES [C] ${line#  CRITICAL: }"
            ;;
    esac
    printf '%s\n' "$line"
}

emit_counted_text() {
    text="${1-}"
    [ -n "$text" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        record_report_line "$line"
    done <<EOF
$text
EOF
}

# ============================================
# 1. 프로세스 상태
# ============================================
echo ""
echo "[1] 프로세스 상태"

if [ "$STOP_REQUESTED" = "1" ]; then
    if [ "$STOP_REQUESTED_SOURCE" = "health_state" ]; then
        echo "  STOPPED: persisted stop health detected — runtime intentionally stopped ($HEALTH_REASON)"
    else
        echo "  STOPPED: live stop sentinel present — runtime intentionally stopped"
    fi
fi

PROCS=$(pgrep_count "quant_binance")
if [ "$STOP_REQUESTED" = "1" ] && [ "$PROCS" -eq 0 ]; then
    echo "  OK: $(describe_stop_requested); quant_binance process absent as expected"
elif [ "$PROCS" -ge 1 ]; then
    echo "  OK: quant_binance ${PROCS}개 실행 중"
else
    CHILD_PID="$(latest_child_pid_from_log)"
    if pid_is_visible "$CHILD_PID"; then
        echo "  OK: quant_binance child pid=${CHILD_PID} 실행 중 (pid/lsof fallback)"
        PROCS=1
    elif fresh_heartbeat_log 900; then
        echo "  OK: process table unavailable, but runtime heartbeat log is fresh"
        PROCS=1
    else
        crit_unless_stopped "quant_binance 프로세스 없음"
    fi
fi

SUPERVISOR_PID="$(slot_pid "$RUNTIME/live_supervisor.pid")"
if [ "$STOP_REQUESTED" = "1" ]; then
    echo "  OK: $(describe_stop_requested); supervisor pid check skipped"
elif [ "$PAPER50_MODE" = "1" ]; then
    echo "  OK: paper50 read-only runtime detected; supervisor pid check skipped"
elif pid_is_visible "$SUPERVISOR_PID"; then
    echo "  OK: supervisor pid=${SUPERVISOR_PID} 실행 중"
else
    warn "supervisor pid 확인 불가"
fi

# Watchdog 프로세스
WD=$(pgrep_count "quant_live_watchdog.py")
if [ "$STOP_REQUESTED" = "1" ]; then
    echo "  OK: $(describe_stop_requested); watchdog check skipped"
elif [ "$PAPER50_MODE" = "1" ]; then
    echo "  OK: paper50 read-only runtime detected; watchdog check skipped"
elif [ "$WD" -ge 1 ]; then
    echo "  OK: watchdog ${WD}개 실행 중"
else
    WATCHDOG_PID="$(slot_pid "$RUNTIME/live_supervisor_watchdog.pid")"
    if pid_is_visible "$WATCHDOG_PID"; then
        echo "  OK: watchdog pid=${WATCHDOG_PID} 실행 중 (pid/lsof fallback)"
        WD=1
    else
        warn "watchdog 프로세스 없음 — 자동 재시작 보호 없음"
    fi
fi

# Health file
if [ -f "$RUNTIME/live_supervisor_health.json" ]; then
    STATUS="${HEALTH_STATUS:-$($PYTHON -c "import json; d=json.load(open('$RUNTIME/live_supervisor_health.json')); print(d.get('status','unknown'))" 2>/dev/null || echo "parse_error")}"
    echo "  Health status: $STATUS"
    if [ "$STATUS" != "healthy" ]; then
        warn_unless_stopped "health status=$STATUS"
    fi
elif [ "$PAPER50_MODE" = "1" ] && fresh_heartbeat_log 900; then
    echo "  Health status: inferred healthy from fresh paper50 heartbeat"
else
    warn "health file missing"
fi

# Health file 갱신 시간
if [ -f "$RUNTIME/live_supervisor_health.json" ]; then
    HEALTH_AGE_OUTPUT="$($PYTHON - "$RUNTIME/live_supervisor_health.json" "$STOP_REQUESTED" <<'PY' 2>/dev/null
import json
import sys
from datetime import datetime, timezone

path = sys.argv[1]
stopped = sys.argv[2] == "1"
d = json.load(open(path))
updated = d.get("updated_at", "")
if updated:
    t = datetime.fromisoformat(updated)
    age_min = (datetime.now(tz=timezone.utc) - t).total_seconds() / 60
    print(f"  Health 갱신: {age_min:.0f}분 전")
    if age_min > 30:
        if not stopped:
            print(f"  WARNING: health 파일 {age_min:.0f}분 미갱신 — 데몬 stall 가능")
        sys.exit(1)
PY
)"
    HEALTH_AGE_STATUS=$?
    if [ -n "$HEALTH_AGE_OUTPUT" ]; then
        printf '%s\n' "$HEALTH_AGE_OUTPUT"
    fi
    if [ "$HEALTH_AGE_STATUS" -ne 0 ] && [ "$STOP_REQUESTED" != "1" ]; then
        warn "health 파일 30분 이상 미갱신"
    elif [ "$HEALTH_AGE_STATUS" -ne 0 ] && [ "$STOP_REQUESTED" = "1" ]; then
        echo "  STOPPED: health stale while runtime is intentionally stopped"
    elif [ "$STOP_REQUESTED" = "1" ]; then
        echo "  OK: health file reflects intentional stop"
    fi
fi

# Recent errors in supervisor log
if [ -f "$SUPERVISOR_LOG" ]; then
    ERROR_COUNT=$(tail -200 "$SUPERVISOR_LOG" | grep -ci "error\|traceback\|exception" 2>/dev/null; true)
    ERROR_COUNT=${ERROR_COUNT:-0}
    echo "  Recent errors (last 200 lines): $ERROR_COUNT"
    if [ "$ERROR_COUNT" -gt 20 ]; then
        crit_unless_stopped "에러 폭발 (${ERROR_COUNT}건/200줄)"
    elif [ "$ERROR_COUNT" -gt 10 ]; then
        warn_unless_stopped "에러 다수 (${ERROR_COUNT}건/200줄)"
    fi
fi

# Heartbeat recency — 마지막 HEARTBEAT 시간
if [ -f "$SUPERVISOR_LOG" ]; then
    LAST_HB=$(tail -100 "$SUPERVISOR_LOG" | grep "HEARTBEAT" | tail -1 2>/dev/null || true)
    if [ -n "$LAST_HB" ]; then
        echo "  마지막 heartbeat: $(echo "$LAST_HB" | head -c 80)"
    else
        warn_unless_stopped "최근 100줄에 HEARTBEAT 없음 — 데몬 stall 가능"
    fi
fi

# ============================================
# 2. 데이터 품질
# ============================================
echo ""
echo "[2] 데이터 품질"
DATA_QUALITY_OUTPUT="$($PYTHON -c "
import json, sys
from pathlib import Path
from datetime import datetime, timezone

summary_path = Path('$SUMMARY_ROOT/summary.json')
if not summary_path.exists():
    decisions_path = Path('$FORENSICS_ROOT/decisions.jsonl')
    if decisions_path.exists():
        lines = sum(1 for _ in decisions_path.open())
        age_min = (datetime.now(tz=timezone.utc) - datetime.fromtimestamp(decisions_path.stat().st_mtime, tz=timezone.utc)).total_seconds() / 60
        print(f'  summary.json not present; using forensics decisions ({lines}건, {age_min:.0f}분 전)')
        sys.exit(0)
    print('  WARNING: summary.json not found')
    sys.exit(1)

# summary.json 갱신 시간
age_min = (datetime.now(tz=timezone.utc) - datetime.fromtimestamp(summary_path.stat().st_mtime, tz=timezone.utc)).total_seconds() / 60
print(f'  summary.json 갱신: {age_min:.0f}분 전')
if age_min > 60:
    print(f'  WARNING: summary.json {age_min:.0f}분 미갱신')

s = json.loads(summary_path.read_text())
closed = s.get('closed_trades', [])
strat = [t for t in closed if t.get('position_origin') == 'strategy']
adopted = [t for t in closed if t.get('position_origin') == 'adopted']

print(f'  총 청산: {len(closed)}건 (전략={len(strat)}, 채택={len(adopted)})')

# 0bps ratio check
if strat:
    zero_bps = [t for t in strat if abs(t.get('realized_return_bps_estimate', 0) or 0) < 0.01]
    ratio = len(zero_bps) / len(strat) * 100
    print(f'  전략 0bps 비율: {len(zero_bps)}/{len(strat)} ({ratio:.0f}%)')
    if ratio > 50:
        print(f'  CRITICAL: 0bps 비율 {ratio:.0f}% — last_trade_price 버그 재발!')
    elif ratio > 20:
        print(f'  WARNING: 0bps 비율 {ratio:.0f}%')
    else:
        print(f'  OK: 0bps 비율 정상')

# Learning data
valid = [t for t in strat if (t.get('entry_predictability_score', 0) or 0) > 0]
valid_with_pnl = [t for t in valid if abs(t.get('realized_return_bps_estimate', 0) or 0) >= 0.01]
print(f'  학습 가능 데이터: {len(valid)}건 / 50건 임계치 ({len(valid)/50*100:.0f}%)')
print(f'  유효 PnL 데이터(!=0bps): {len(valid_with_pnl)}/{max(len(valid),1)}건', end='')
if valid:
    eff = len(valid_with_pnl) / len(valid) * 100
    print(f' ({eff:.0f}%)')
    if eff < 50:
        print(f'  WARNING: 유효 PnL 비율 {eff:.0f}% — last_trade_price 갱신 확인 필요')
    else:
        print(f'  OK: 유효 데이터 정상 축적 중')
else:
    print()
    if len(strat) >= 5:
        print(f'  WARNING: 전략 진입 {len(strat)}건인데 학습 가능 0건 — score 기록 안됨')

# 전략 진입 속도 (최근 24시간)
if strat:
    from datetime import timedelta
    now = datetime.now(tz=timezone.utc)
    recent = [t for t in strat if t.get('entry_time') and (now - datetime.fromisoformat(t['entry_time'])).total_seconds() < 86400]
    print(f'  최근 24h 전략 진입: {len(recent)}건')
    if len(recent) == 0 and len(strat) > 0:
        print(f'  WARNING: 24시간 동안 전략 진입 0건 — 진입 조건 너무 엄격하거나 데몬 문제')
" 2>/dev/null)"
DATA_QUALITY_STATUS=$?
emit_counted_text "$DATA_QUALITY_OUTPUT"
if [ "$DATA_QUALITY_STATUS" -ne 0 ]; then
    warn "data quality check failed"
fi

# ============================================
# 3. 상태 파일 무결성
# ============================================
echo ""
echo "[3] 상태 파일 무결성"
STATE_FILE_OUTPUT="$($PYTHON -c "
import json, sys
from pathlib import Path
from datetime import datetime, timezone

# state file
state_path = Path('$SUMMARY_ROOT/summary.state.json')
if not state_path.exists():
    eq_path = Path('$RUNTIME/execution_quality_state.json')
    if eq_path.exists():
        age_min = (datetime.now(tz=timezone.utc) - datetime.fromtimestamp(eq_path.stat().st_mtime, tz=timezone.utc)).total_seconds() / 60
        print(f'  summary.state.json not present; execution_quality_state.json exists ({age_min:.0f}분 전)')
        sys.exit(0)
    print('  WARNING: state file missing')
    sys.exit(1)

size_mb = state_path.stat().st_size / 1024 / 1024
print(f'  state file: {size_mb:.1f}MB')
if size_mb > 50:
    print(f'  WARNING: state file {size_mb:.0f}MB — 비정상적으로 큼')

try:
    st = json.loads(state_path.read_text())
    pp = st.get('paper_positions', [])
    print(f'  활성 paper 포지션: {len(pp)}건')

    # Check for corrupt positions
    for p in pp:
        entry = p.get('entry_price', 0)
        qty = p.get('quantity_remaining', p.get('quantity_opened', 0))
        if entry <= 0:
            print(f'  CRITICAL: entry_price=0 포지션 발견: {p.get(\"symbol\")}')
        if qty <= 0:
            print(f'  WARNING: quantity=0 포지션 발견: {p.get(\"symbol\")}')
except json.JSONDecodeError:
    print('  CRITICAL: state file JSON 파싱 실패 — 파일 손상!')
" 2>/dev/null)"
STATE_FILE_STATUS=$?
emit_counted_text "$STATE_FILE_OUTPUT"
if [ "$STATE_FILE_STATUS" -ne 0 ]; then
    warn "state file check failed"
fi

# cost calibration freshness
if [ -f "$RUNTIME/artifacts/cost_calibration.json" ]; then
    CAL_AGE_HR=$($PYTHON -c "
from pathlib import Path
from datetime import datetime, timezone
p = Path('$RUNTIME/artifacts/cost_calibration.json')
age = (datetime.now(tz=timezone.utc) - datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)).total_seconds() / 3600
print(f'{age:.0f}')
" 2>/dev/null || echo "999")
    echo "  cost_calibration.json: ${CAL_AGE_HR}시간 전"
    if [ "$CAL_AGE_HR" -gt 48 ]; then
        warn "cost calibration ${CAL_AGE_HR}시간 미갱신"
    fi
else
    warn "cost_calibration.json 없음"
fi

# ============================================
# 4. 리소스
# ============================================
echo ""
echo "[4] 리소스"

# Supervisor log size
if [ -f "$SUPERVISOR_LOG" ]; then
    LOG_MB=$(du -m "$SUPERVISOR_LOG" | cut -f1)
    echo "  runtime log: ${LOG_MB}MB ($(basename "$SUPERVISOR_LOG"))"
    if [ "$LOG_MB" -gt 200 ]; then
        warn "supervisor.log ${LOG_MB}MB (>200MB)"
    fi
fi

# Output disk usage
OUTPUT_MB=$(du -sm "$RUNTIME/output" 2>/dev/null | cut -f1 || echo "0")
echo "  output 디렉토리: ${OUTPUT_MB}MB"
if [ "$OUTPUT_MB" -gt 5000 ]; then
    warn "output ${OUTPUT_MB}MB (>5GB)"
fi

# Health audit log rotation
if [ -f "$RUNTIME/health_audit.log" ]; then
    AUDIT_LOG_MB=$(du -m "$RUNTIME/health_audit.log" | cut -f1)
    echo "  health_audit.log: ${AUDIT_LOG_MB}MB"
    if [ "$AUDIT_LOG_MB" -gt 50 ]; then
        warn "health_audit.log ${AUDIT_LOG_MB}MB (>50MB)"
    fi
fi

# Memory usage
MEM_INFO=$(ps aux 2>/dev/null | grep "quant_binance" | grep -v grep | awk '{sum+=$6} END {if (sum > 0) printf "%.0f", sum/1024}' 2>/dev/null || true)
if [ -n "$MEM_INFO" ]; then
    echo "  quant_binance 메모리: ${MEM_INFO}MB"
    if [ "$MEM_INFO" -gt 2000 ]; then
        crit "메모리 ${MEM_INFO}MB (>2GB) — 메모리 누수 가능"
    elif [ "$MEM_INFO" -gt 1000 ]; then
        warn "메모리 ${MEM_INFO}MB (>1GB)"
    fi
else
    echo "  quant_binance 메모리: unavailable (process visibility restricted)"
fi

# Disk space
DISK_AVAIL=$(df -g "$REPO" | tail -1 | awk '{print $4}')
echo "  디스크 여유: ${DISK_AVAIL}GB"
if [ "$DISK_AVAIL" -lt 5 ]; then
    crit "디스크 여유 ${DISK_AVAIL}GB (<5GB)"
elif [ "$DISK_AVAIL" -lt 20 ]; then
    warn "디스크 여유 ${DISK_AVAIL}GB (<20GB)"
fi

# ---- Auto disk cleanup ----
echo ""
echo "[4b] 자동 디스크 정리"
CLEANED=0

# 1. supervisor.log 200MB 넘으면 로테이션
if [ "$PAPER50_MODE" != "1" ] && [ -f "$SUPERVISOR_LOG" ]; then
    LOG_SZ=$(du -m "$SUPERVISOR_LOG" | cut -f1)
    if [ "$LOG_SZ" -gt 200 ]; then
        mv "$SUPERVISOR_LOG" "$SUPERVISOR_LOG.old" 2>/dev/null
        echo "  supervisor.log ${LOG_SZ}MB → rotated"
        CLEANED=$((CLEANED+1))
    fi
fi

# 2. 이전 로테이션 .old/.1 파일 삭제 (7일 이상)
find "$RUNTIME" -maxdepth 1 -name "live_supervisor.log.*" -mtime +7 -delete 2>/dev/null
OLD_DELETED=$(find "$RUNTIME" -maxdepth 1 -name "live_supervisor.log.*" -mtime +7 2>/dev/null | wc -l | tr -d ' ')

# 3. health_audit.log / autotuner.log 50MB 넘으면 truncate
for LOGFILE in "$RUNTIME/health_audit.log" "$RUNTIME/autotuner.log" "$RUNTIME/health_audit_claude.log"; do
    if [ -f "$LOGFILE" ]; then
        LSZMB=$(du -m "$LOGFILE" | cut -f1)
        if [ "$LSZMB" -gt 50 ]; then
            tail -10000 "$LOGFILE" > "$LOGFILE.tmp" && mv "$LOGFILE.tmp" "$LOGFILE"
            echo "  $(basename $LOGFILE) ${LSZMB}MB → truncated to last 10k lines"
            CLEANED=$((CLEANED+1))
        fi
    fi
done

# 4. 7일 이상 된 이전 세션 run 디렉토리 삭제 (latest 제외)
$PYTHON -c "
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

cutoff = datetime.now(tz=timezone.utc) - timedelta(days=7)
base = Path('$OUTPUT_MODE_ROOT')
if not base.exists():
    raise SystemExit(0)
removed = 0
for d in sorted(base.iterdir()):
    if not d.is_dir() or d.name == 'latest':
        continue
    try:
        mtime = datetime.fromtimestamp(d.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            shutil.rmtree(d)
            removed += 1
    except: pass
if removed:
    print(f'  오래된 run 디렉토리 {removed}개 삭제')
" 2>/dev/null

# 5. git worktree 정리 (30일 이상)
$PYTHON -c "
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

cutoff = datetime.now(tz=timezone.utc) - timedelta(days=30)
wt_base = Path('$REPO/.claude/worktrees')
if wt_base.exists():
    removed = 0
    for d in sorted(wt_base.iterdir()):
        if not d.is_dir():
            continue
        try:
            mtime = datetime.fromtimestamp(d.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                shutil.rmtree(d)
                removed += 1
        except: pass
    if removed:
        print(f'  오래된 worktree {removed}개 삭제')
" 2>/dev/null

# 6. 디스크 위험 수준이면 추가 정리
if [ "$DISK_AVAIL" -lt 10 ]; then
    echo "  디스크 위험! 추가 정리 실행..."
    # 오래된 .old 로그 전부 삭제
    find "$RUNTIME" -name "*.old" -delete 2>/dev/null
    find "$RUNTIME" -name "*.bak" -delete 2>/dev/null
    # edge_table.json 중 오래된 것 삭제
    find "$RUNTIME/output" -name "edge_table.json" -mtime +7 -delete 2>/dev/null
    echo "  추가 정리 완료"
    CLEANED=$((CLEANED+1))
fi

if [ "$CLEANED" -eq 0 ]; then
    echo "  정리 불필요"
fi

# CPU usage
CPU=$($PYTHON -c "
import subprocess
out = subprocess.check_output(['ps', 'aux']).decode()
total = sum(float(line.split()[2]) for line in out.strip().split('\n')[1:] if 'quant_binance' in line)
if total > 0:
    print(f'{total:.0f}')
" 2>/dev/null || true)
if [ -n "$CPU" ]; then
    echo "  quant_binance CPU: ${CPU}%"
    if [ "$CPU" -gt 90 ]; then
        warn "CPU ${CPU}% (>90%) — 과부하"
    fi
else
    echo "  quant_binance CPU: unavailable (process visibility restricted)"
fi

# ============================================
# 5. self_healing 이벤트
# ============================================
echo ""
echo "[5] Self-healing"
SELF_HEALING_OUTPUT="$($PYTHON -c "
import json, sys
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone, timedelta

events = []
roots = [Path('$OUTPUT_MODE_ROOT'), Path('$FORENSICS_ROOT')]
for root in roots:
  if not root.exists():
    continue
  for f in root.rglob('self_healing.jsonl'):
    for line in f.open():
        try: events.append(json.loads(line))
        except: pass

if events:
    recent = events[-20:]
    cats = Counter(e.get('category','?') for e in recent)
    print(f'  총 이벤트: {len(events)}건, 최근 20건:')
    for c, n in cats.most_common(5):
        print(f'    {c}: {n}건')

    # 반복 에러 패턴 감지
    unknown = [e for e in recent if e.get('category') == 'unknown_runtime_error']
    if len(unknown) >= 15:
        print(f'  CRITICAL: unknown_runtime_error 폭발 ({len(unknown)}/20건)')
    elif len(unknown) >= 5:
        print(f'  WARNING: unknown_runtime_error 반복 ({len(unknown)}/20건)')
    stalled = [e for e in recent if e.get('category') == 'daemon_stalled']
    if len(stalled) >= 3:
        print(f'  WARNING: daemon_stalled 반복 ({len(stalled)}/20건)')
    mismatch = [e for e in recent if e.get('category') == 'persistent_futures_mismatch']
    if len(mismatch) >= 10:
        print(f'  WARNING: futures mismatch 반복 ({len(mismatch)}/20건)')
else:
    print('  이벤트 없음')
" 2>/dev/null)"
SELF_HEALING_STATUS=$?
emit_counted_text "$SELF_HEALING_OUTPUT"
if [ "$SELF_HEALING_STATUS" -ne 0 ]; then
    echo "  self_healing check skipped"
fi

# ============================================
# 6. Bitget API 상태
# ============================================
echo ""
echo "[6] Bitget API"
$PYTHON -c "
import json
from pathlib import Path

summary_path = Path('$SUMMARY_ROOT/summary.json')
summary = {}
summary_mtime = 0.0
if summary_path.exists():
    try:
        summary = json.loads(summary_path.read_text())
        summary_mtime = summary_path.stat().st_mtime
    except Exception:
        summary = {}
        summary_mtime = 0.0

summary_count_keys = {
    'live_orders': 'live_order_count',
    'tested_orders': 'tested_order_count',
}

for log_name in ['live_orders', 'tested_orders']:
    total = 0
    paths = []
    flat = Path('$FORENSICS_ROOT') / f'{log_name}.jsonl'
    if flat.exists():
        paths.append(flat)
    out_root = Path('$OUTPUT_MODE_ROOT')
    if out_root.exists():
        paths.extend(out_root.rglob(f'{log_name}.jsonl'))
    seen = set()
    freshest_log_mtime = 0.0
    for f in paths:
        if f in seen:
            continue
        seen.add(f)
        try:
            freshest_log_mtime = max(freshest_log_mtime, f.stat().st_mtime)
        except OSError:
            pass
        total += sum(1 for _ in f.open())
    summary_count = summary.get(summary_count_keys[log_name])
    try:
        summary_count = int(summary_count or 0)
    except (TypeError, ValueError):
        summary_count = 0
    if summary_mtime > freshest_log_mtime:
        total = summary_count
    elif total == 0 and summary_count:
        total = summary_count
    print(f'  {log_name}: {total}건')
" 2>/dev/null || echo "  API check skipped"

# 429/5xx in supervisor log
if [ -f "$SUPERVISOR_LOG" ]; then
    RATE_LIMIT=$(tail -500 "$SUPERVISOR_LOG" | grep -Eci "HTTP[[:space:]/_-]*429|status[=: ][[:space:]]*429|code[=: ][[:space:]]*429|rate[._ -]?limit|too many requests" 2>/dev/null; true)
    RATE_LIMIT=${RATE_LIMIT:-0}
    SERVER_ERR=$(tail -500 "$SUPERVISOR_LOG" | grep -ci "HTTP 50[0-9]" 2>/dev/null; true)
    SERVER_ERR=${SERVER_ERR:-0}
    TRANSPORT_ERR=$(tail -500 "$SUPERVISOR_LOG" | grep -ci "transport error\|DNS resolution\|connection reset" 2>/dev/null; true)
    TRANSPORT_ERR=${TRANSPORT_ERR:-0}
    echo "  최근 429 에러: ${RATE_LIMIT}건"
    echo "  최근 5xx 에러: ${SERVER_ERR}건"
    echo "  최근 transport 에러: ${TRANSPORT_ERR}건"
    if [ "$RATE_LIMIT" -gt 5 ]; then
        warn "rate limit 빈발 (${RATE_LIMIT}건)"
    fi
    if [ "$SERVER_ERR" -gt 10 ]; then
        warn "서버 에러 빈발 (${SERVER_ERR}건)"
    fi
    if [ "$TRANSPORT_ERR" -gt 10 ]; then
        warn "네트워크 에러 빈발 (${TRANSPORT_ERR}건)"
    fi
fi

# API connectivity quick check
BITGET_API_OUTPUT="$($PYTHON -c "
import ssl
from urllib.request import urlopen, Request
try:
    ctx = ssl._create_unverified_context()
    r = urlopen('https://api.bitget.com/api/v2/public/time', timeout=10, context=ctx)
    print(f'  Bitget API: OK (HTTP {r.status})')
except Exception as e:
    print(f'  WARNING: Bitget API 연결 실패 — {e}')
" 2>/dev/null)"
BITGET_API_STATUS=$?
emit_counted_text "$BITGET_API_OUTPUT"
if [ "$BITGET_API_STATUS" -ne 0 ]; then
    warn "Bitget API 연결 실패"
fi

# ============================================
# 7. 의사결정 흐름
# ============================================
echo ""
echo "[7] 의사결정 흐름"
DECISION_FLOW_OUTPUT="$($PYTHON -c "
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import Counter

overview_path = Path('$SUMMARY_ROOT/overview.json')
overview = {}
overview_mtime = 0.0
if overview_path.exists():
    try:
        overview = json.loads(overview_path.read_text())
        overview_mtime = overview_path.stat().st_mtime
    except Exception:
        overview = {}
        overview_mtime = 0.0

decs = []
flat = Path('$FORENSICS_ROOT') / 'decisions.jsonl'
if flat.exists():
    paths = [flat]
else:
    paths = list(Path('$OUTPUT_MODE_ROOT').rglob('decisions.jsonl')) if Path('$OUTPUT_MODE_ROOT').exists() else []
freshest_log_mtime = 0.0
for f in paths:
    try:
        freshest_log_mtime = max(freshest_log_mtime, f.stat().st_mtime)
    except OSError:
        pass
    for line in f.open():
        try: decs.append(json.loads(line))
        except: pass

recent_decisions_fallback = overview.get('recent_decisions') if isinstance(overview.get('recent_decisions'), list) else []
overview_decision_count = overview.get('decision_count')
try:
    overview_decision_count = int(overview_decision_count or 0)
except (TypeError, ValueError):
    overview_decision_count = 0
use_overview_fallback = overview_mtime > freshest_log_mtime and overview_decision_count > 0
decision_total = overview_decision_count if use_overview_fallback else len(decs)

print(f'  총 의사결정: {decision_total}건')
if decs or use_overview_fallback:
    modes = Counter(d.get('final_mode', d.get('mode','?')) for d in decs)
    if use_overview_fallback and recent_decisions_fallback:
        recent_modes = Counter(d.get('final_mode', d.get('mode','?')) for d in recent_decisions_fallback)
        print(f'  최근 모드 샘플: {dict(recent_modes)}')
    elif modes:
        print(f'  모드: {dict(modes)}')

    # Recent decisions (last 6 hours)
    now = datetime.now(tz=timezone.utc)
    recent = [d for d in decs if d.get('timestamp') and (now - datetime.fromisoformat(d['timestamp'])).total_seconds() < 21600]
    if use_overview_fallback:
        last_decision_timestamp = overview.get('last_decision_timestamp')
        try:
            last_decision_at = datetime.fromisoformat(last_decision_timestamp) if last_decision_timestamp else None
        except ValueError:
            last_decision_at = None
        if last_decision_at is not None and (now - last_decision_at).total_seconds() < 21600:
            recent = recent_decisions_fallback or [{}]
    print(f'  최근 6h 의사결정: {len(recent)}건')
    if len(recent) == 0:
        print(f'  WARNING: 6시간 동안 의사결정 0건 — 데몬 stall 또는 데이터 부재')

    # cash ratio (전체 대비)
    cash_count = modes.get('cash', 0)
    if use_overview_fallback and recent_decisions_fallback:
        cash_count = sum(1 for d in recent_decisions_fallback if d.get('final_mode', d.get('mode','?')) == 'cash')
        cash_denominator = len(recent_decisions_fallback)
    else:
        cash_denominator = len(decs)
    if cash_denominator > 20:
        cash_pct = cash_count / cash_denominator * 100
        print(f'  cash(미진입) 비율: {cash_pct:.0f}%')
        if cash_pct > 95:
            print(f'  WARNING: 95%+ cash — 진입 조건 너무 엄격하거나 시장 상황 극단적')
" 2>/dev/null)"
DECISION_FLOW_STATUS=$?
emit_counted_text "$DECISION_FLOW_OUTPUT"
if [ "$DECISION_FLOW_STATUS" -ne 0 ]; then
    echo "  decision flow check skipped"
fi

# ============================================
# 8. 포지션 sync 상태
# ============================================
echo ""
echo "[8] 포지션 sync"
SYNC_OUTPUT="$($PYTHON -c "
import json
from pathlib import Path

syncs = []
flat = Path('$FORENSICS_ROOT') / 'account_sync.jsonl'
if flat.exists():
    paths = [flat]
else:
    paths = list(Path('$OUTPUT_MODE_ROOT').rglob('account_sync.jsonl')) if Path('$OUTPUT_MODE_ROOT').exists() else []
for f in paths:
    for line in f.open():
        try: syncs.append(json.loads(line))
        except: pass

print(f'  account_sync 이벤트: {len(syncs)}건')
if syncs:
    recent = syncs[-10:]
    mismatches = [s for s in recent if s.get('missing_in_paper') or s.get('missing_on_exchange')]
    if mismatches:
        print(f'  WARNING: 최근 10건 중 {len(mismatches)}건 포지션 불일치')
    else:
        print(f'  OK: 최근 sync 정상')
" 2>/dev/null)"
SYNC_STATUS=$?
emit_counted_text "$SYNC_OUTPUT"
if [ "$SYNC_STATUS" -ne 0 ]; then
    echo "  sync check skipped"
fi

# ============================================
# 9. git 상태
# ============================================
echo ""
echo "[9] Git 상태"
cd "$REPO"
BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
DIRTY=$(git status --porcelain -- quant_binance/ scripts/ tests/ 2>/dev/null | wc -l | tr -d ' ')
echo "  브랜치: $BRANCH"
echo "  소스코드 uncommitted 변경: ${DIRTY}건"
if [ "$DIRTY" -gt 10 ]; then
    warn "소스코드 uncommitted 변경 ${DIRTY}건 — 커밋 필요"
fi

# ============================================
# 결과
# ============================================
echo ""
echo "============================================"
echo "[RESULT] CRITICAL=$CRITICALS WARNING=$WARNINGS"
if [ "$STOP_REQUESTED" = "1" ]; then
    echo "[STATUS] intentionally stopped — autofix suppressed"
elif [ "$DISABLE_AUTOFIX" = "1" ] && { [ "$CRITICALS" -gt 0 ] || [ "$WARNINGS" -ge 1 ]; }; then
    echo "[ACTION] issues found — autofix disabled"
elif [ "$CRITICALS" -gt 0 ]; then
    echo "[ACTION] CRITICAL 발견 — Claude Code 자동 수정 실행"
elif [ "$WARNINGS" -ge 1 ]; then
    echo "[ACTION] WARNING 발견 — Claude Code 자동 수정 실행"
else
    echo "[STATUS] 정상 — 수정 불필요"
fi
echo "============================================"
echo ""

# ============================================
# 10. Claude Code 자동 수정
# ============================================
if [ "$STOP_REQUESTED" = "1" ]; then
    echo "[SKIP] runtime intentionally stopped — autofix suppressed"
elif [ "$DISABLE_AUTOFIX" != "1" ] && { [ "$CRITICALS" -gt 0 ] || [ "$WARNINGS" -ge 1 ]; }; then
    AUDIT_SUMMARY="health audit at $TIMESTAMP: CRITICAL=$CRITICALS WARNING=$WARNINGS.$ISSUES"

    echo "[CLAUDE] 자동 수정 시작: CRITICAL=$CRITICALS WARNING=$WARNINGS"

    CLAUDE_PROMPT="코인 매매 프로그램 정기 health audit 결과:

${AUDIT_SUMMARY}

다음을 순서대로 수행해줘:

## 1단계: 진단
- 위 WARNING/CRITICAL의 근본 원인을 코드에서 찾기
- 프로세스 죽었으면: pgrep -f quant_binance 확인

## 2단계: 수정
- 코드 버그면: 최소한의 수정만 (확실한 것만)
- 프로세스 죽었으면: kill 후 nohup bash scripts/quant_run_live_orders.sh quant_runtime > /dev/null 2>&1 &
- supervisor.log 200MB 넘으면: mv quant_runtime/live_supervisor.log quant_runtime/live_supervisor.log.old
- 메모리 2GB 넘으면: 프로세스 kill → 재시작
- watchdog 없으면: supervisor가 자동 재시작하므로 전체 재시작

## 3단계: 검증
- 코드 수정했으면: python3 -m unittest tests.test_quant_binance_learning tests.test_quant_binance_overlays tests.test_quant_binance_news_macro_signal -v
- 테스트 통과하면 git commit
- 코드 수정 + 커밋했으면: 데몬 재시작 (기존 kill → nohup bash scripts/quant_run_live_orders.sh quant_runtime)

## 4단계: 재검증
- bash scripts/quant_health_audit.sh 2>&1 | grep RESULT 실행
- WARNING=0 확인될 때까지 반복 (최대 2회)
- 결과를 $RUNTIME/health_audit_fix_result.txt 에 기록

## 규칙 (절대 위반 금지)
- 불필요한 변경 금지. 확실한 버그만 수정
- 데몬 재시작은 반드시 watchdog 포함 (quant_run_live_orders.sh 사용)
- 재검증에서 WARNING 남으면 그것도 고치기

## 수정 금지 영역 (변경통제)
- strategy/ 디렉토리: 전략 로직 절대 수정 금지
- settings.py: 설정 구조체 수정 금지
- strategy_override.approved.json: 절대 수정 금지. _lock 필드 확인. data_collection_mode=true 동안 어떤 파라미터도 변경 불가
- risk/ 디렉토리: 리스크 한도/사이징 로직 수정 금지
- overlays.py: 시그널 가중치/오버레이 로직 수정 금지
- autotuner/: 자동 튜닝 로직 수정 금지
- 수정 허용: 인프라 버그(프로세스, 로그, 네트워크, 메모리), 데이터 파이프라인 버그만"

    # ── 한탕 모드 자동 health check + 수정 ──
    echo ""
    echo "[YOLO] 한탕 모드 자동 점검"
    $PYTHON "$REPO/scripts/yolo_health_check.py" 2>&1
    YOLO_EXIT=$?
    if [ "$YOLO_EXIT" -eq 1 ]; then
        if [ "$ALLOW_RESTART" = "1" ]; then
            echo "[YOLO] 자동 수정 완료 — 봇 재시작 허용됨"
            pkill -f 'quant_binance.runtime --mode live-auto-trade-daemon' 2>/dev/null || true
            sleep 3
            clear_live_stop_files
            echo "[YOLO] stop sentinels cleared before restart"
            nohup bash "$REPO/scripts/quant_run_live_orders.sh" > /dev/null 2>&1 &
            echo "[YOLO] 봇 재시작됨 (PID: $!)"
        else
            warn "한탕 모드 자동 수정 완료 — 재시작은 QUANT_HEALTH_AUDIT_ALLOW_RESTART=1 없어서 차단"
        fi
    elif [ "$YOLO_EXIT" -eq 2 ]; then
        crit "한탕 모드 수동 개입 필요"
    else
        echo "[YOLO] 정상 — 수정 불필요"
    fi

    if [ -x "$CLAUDE" ]; then
        echo "$CLAUDE_PROMPT" | "$CLAUDE" --dangerously-skip-permissions -p - --output-format text \
            >> "$RUNTIME/health_audit_claude.log" 2>&1 &
        CLAUDE_PID=$!
        # macOS에는 timeout 명령 없음 — 백그라운드 kill timer로 대체
        ( sleep 600 && kill "$CLAUDE_PID" 2>/dev/null ) &
        echo "[CLAUDE] PID=$CLAUDE_PID 백그라운드 실행"
    else
        echo "[CLAUDE] claude CLI not found at $CLAUDE — 수동 확인 필요"
    fi
else
    if [ "$DISABLE_AUTOFIX" = "1" ]; then
        echo "[SKIP] autofix disabled"
    else
        echo "[SKIP] 정상 — Claude Code 실행 불필요"
    fi
fi
