#!/bin/bash
# 코인 매매 프로그램 정기 전수조사 + 자동 수정
# crontab: 17 0,2,4,6,9,12,14,16,18 * * * ...

set -uo pipefail
REPO="/Users/tttksj/first_repo"
RUNTIME="$REPO/quant_runtime"
PYTHON="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
CLAUDE="/Users/tttksj/.local/bin/claude"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S %Z')

echo "============================================"
echo "[HEALTH_AUDIT] $TIMESTAMP"
echo "============================================"

WARNINGS=0
CRITICALS=0
ISSUES=""

warn() { echo "  WARNING: $1"; WARNINGS=$((WARNINGS+1)); ISSUES="$ISSUES [W] $1"; }
crit() { echo "  CRITICAL: $1"; CRITICALS=$((CRITICALS+1)); ISSUES="$ISSUES [C] $1"; }

# ============================================
# 1. 프로세스 상태
# ============================================
echo ""
echo "[1] 프로세스 상태"

PROCS=$(pgrep -f quant_binance 2>/dev/null | wc -l | tr -d ' ')
if [ "$PROCS" -ge 1 ]; then
    echo "  OK: quant_binance ${PROCS}개 실행 중"
else
    crit "quant_binance 프로세스 없음"
fi

# Watchdog 프로세스
WD=$(pgrep -f "quant_live_watchdog.py" 2>/dev/null | wc -l | tr -d ' ')
if [ "$WD" -ge 1 ]; then
    echo "  OK: watchdog ${WD}개 실행 중"
else
    warn "watchdog 프로세스 없음 — 자동 재시작 보호 없음"
fi

# Health file
if [ -f "$RUNTIME/live_supervisor_health.json" ]; then
    STATUS=$($PYTHON -c "import json; d=json.load(open('$RUNTIME/live_supervisor_health.json')); print(d.get('status','unknown'))" 2>/dev/null || echo "parse_error")
    echo "  Health status: $STATUS"
    if [ "$STATUS" != "healthy" ]; then
        warn "health status=$STATUS"
    fi
else
    warn "health file missing"
fi

# Health file 갱신 시간
if [ -f "$RUNTIME/live_supervisor_health.json" ]; then
    $PYTHON -c "
import json, sys
from datetime import datetime, timezone
d = json.load(open('$RUNTIME/live_supervisor_health.json'))
updated = d.get('updated_at','')
if updated:
    t = datetime.fromisoformat(updated)
    age_min = (datetime.now(tz=timezone.utc) - t).total_seconds() / 60
    print(f'  Health 갱신: {age_min:.0f}분 전')
    if age_min > 30:
        print(f'  WARNING: health 파일 {age_min:.0f}분 미갱신 — 데몬 stall 가능')
        sys.exit(1)
" 2>/dev/null
    if [ $? -ne 0 ]; then
        warn "health 파일 30분 이상 미갱신"
    fi
fi

# Recent errors in supervisor log
if [ -f "$RUNTIME/live_supervisor.log" ]; then
    ERROR_COUNT=$(tail -200 "$RUNTIME/live_supervisor.log" | grep -ci "error\|traceback\|exception" 2>/dev/null; true)
    ERROR_COUNT=${ERROR_COUNT:-0}
    echo "  Recent errors (last 200 lines): $ERROR_COUNT"
    if [ "$ERROR_COUNT" -gt 20 ]; then
        crit "에러 폭발 ($ERROR_COUNT건/200줄)"
    elif [ "$ERROR_COUNT" -gt 10 ]; then
        warn "에러 다수 ($ERROR_COUNT건/200줄)"
    fi
fi

# Heartbeat recency — 마지막 HEARTBEAT 시간
if [ -f "$RUNTIME/live_supervisor.log" ]; then
    LAST_HB=$(tail -100 "$RUNTIME/live_supervisor.log" | grep "HEARTBEAT" | tail -1 2>/dev/null || true)
    if [ -n "$LAST_HB" ]; then
        echo "  마지막 heartbeat: $(echo "$LAST_HB" | head -c 80)"
    else
        warn "최근 100줄에 HEARTBEAT 없음 — 데몬 stall 가능"
    fi
fi

# ============================================
# 2. 데이터 품질
# ============================================
echo ""
echo "[2] 데이터 품질"
$PYTHON -c "
import json, sys
from pathlib import Path
from datetime import datetime, timezone

summary_path = Path('$RUNTIME/output/paper-live-shell/latest/summary.json')
if not summary_path.exists():
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
" 2>/dev/null || { warn "data quality check failed"; }

# ============================================
# 3. 상태 파일 무결성
# ============================================
echo ""
echo "[3] 상태 파일 무결성"
$PYTHON -c "
import json, sys
from pathlib import Path
from datetime import datetime, timezone

# state file
state_path = Path('$RUNTIME/output/paper-live-shell/latest/summary.state.json')
if not state_path.exists():
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
" 2>/dev/null || { warn "state file check failed"; }

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
if [ -f "$RUNTIME/live_supervisor.log" ]; then
    LOG_MB=$(du -m "$RUNTIME/live_supervisor.log" | cut -f1)
    echo "  supervisor.log: ${LOG_MB}MB"
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
MEM_INFO=$(ps aux | grep "quant_binance" | grep -v grep | awk '{sum+=$6} END {printf "%.0f", sum/1024}' 2>/dev/null || echo "0")
echo "  quant_binance 메모리: ${MEM_INFO}MB"
if [ "$MEM_INFO" -gt 2000 ]; then
    crit "메모리 ${MEM_INFO}MB (>2GB) — 메모리 누수 가능"
elif [ "$MEM_INFO" -gt 1000 ]; then
    warn "메모리 ${MEM_INFO}MB (>1GB)"
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
if [ -f "$RUNTIME/live_supervisor.log" ]; then
    LOG_SZ=$(du -m "$RUNTIME/live_supervisor.log" | cut -f1)
    if [ "$LOG_SZ" -gt 200 ]; then
        mv "$RUNTIME/live_supervisor.log" "$RUNTIME/live_supervisor.log.old" 2>/dev/null
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
base = Path('$RUNTIME/output/paper-live-shell')
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
print(f'{total:.0f}')
" 2>/dev/null || echo "0")
echo "  quant_binance CPU: ${CPU}%"
if [ "$CPU" -gt 90 ]; then
    warn "CPU ${CPU}% (>90%) — 과부하"
fi

# ============================================
# 5. self_healing 이벤트
# ============================================
echo ""
echo "[5] Self-healing"
$PYTHON -c "
import json, sys
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone, timedelta

events = []
for f in Path('$RUNTIME/output/paper-live-shell').rglob('self_healing.jsonl'):
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
" 2>/dev/null || echo "  self_healing check skipped"

# ============================================
# 6. Bitget API 상태
# ============================================
echo ""
echo "[6] Bitget API"
$PYTHON -c "
import json
from pathlib import Path

for log_name in ['live_orders', 'tested_orders']:
    total = 0
    for f in Path('$RUNTIME/output/paper-live-shell').rglob(f'{log_name}.jsonl'):
        total += sum(1 for _ in f.open())
    print(f'  {log_name}: {total}건')
" 2>/dev/null || echo "  API check skipped"

# 429/5xx in supervisor log
if [ -f "$RUNTIME/live_supervisor.log" ]; then
    RATE_LIMIT=$(tail -500 "$RUNTIME/live_supervisor.log" | grep -ci "429\|rate.limit" 2>/dev/null; true)
    RATE_LIMIT=${RATE_LIMIT:-0}
    SERVER_ERR=$(tail -500 "$RUNTIME/live_supervisor.log" | grep -ci "HTTP 50[0-9]" 2>/dev/null; true)
    SERVER_ERR=${SERVER_ERR:-0}
    TRANSPORT_ERR=$(tail -500 "$RUNTIME/live_supervisor.log" | grep -ci "transport error\|DNS resolution\|connection reset" 2>/dev/null; true)
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
$PYTHON -c "
import ssl
from urllib.request import urlopen, Request
try:
    ctx = ssl._create_unverified_context()
    r = urlopen('https://api.bitget.com/api/v2/public/time', timeout=10, context=ctx)
    print(f'  Bitget API: OK (HTTP {r.status})')
except Exception as e:
    print(f'  WARNING: Bitget API 연결 실패 — {e}')
" 2>/dev/null || warn "Bitget API 연결 실패"

# ============================================
# 7. 의사결정 흐름
# ============================================
echo ""
echo "[7] 의사결정 흐름"
$PYTHON -c "
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import Counter

decs = []
for f in Path('$RUNTIME/output/paper-live-shell').rglob('decisions.jsonl'):
    for line in f.open():
        try: decs.append(json.loads(line))
        except: pass

print(f'  총 의사결정: {len(decs)}건')
if decs:
    modes = Counter(d.get('final_mode', d.get('mode','?')) for d in decs)
    print(f'  모드: {dict(modes)}')

    # Recent decisions (last 6 hours)
    now = datetime.now(tz=timezone.utc)
    recent = [d for d in decs if d.get('timestamp') and (now - datetime.fromisoformat(d['timestamp'])).total_seconds() < 21600]
    print(f'  최근 6h 의사결정: {len(recent)}건')
    if len(recent) == 0:
        print(f'  WARNING: 6시간 동안 의사결정 0건 — 데몬 stall 또는 데이터 부재')

    # cash ratio (전체 대비)
    cash_count = modes.get('cash', 0)
    if len(decs) > 20:
        cash_pct = cash_count / len(decs) * 100
        print(f'  cash(미진입) 비율: {cash_pct:.0f}%')
        if cash_pct > 95:
            print(f'  WARNING: 95%+ cash — 진입 조건 너무 엄격하거나 시장 상황 극단적')
" 2>/dev/null || echo "  decision flow check skipped"

# ============================================
# 8. 포지션 sync 상태
# ============================================
echo ""
echo "[8] 포지션 sync"
$PYTHON -c "
import json
from pathlib import Path

syncs = []
for f in Path('$RUNTIME/output/paper-live-shell').rglob('account_sync.jsonl'):
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
" 2>/dev/null || echo "  sync check skipped"

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
if [ "$CRITICALS" -gt 0 ]; then
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
if [ "$CRITICALS" -gt 0 ] || [ "$WARNINGS" -ge 1 ]; then
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

## 규칙
- 불필요한 변경 금지. 확실한 버그만 수정
- 데몬 재시작은 반드시 watchdog 포함 (quant_run_live_orders.sh 사용)
- 재검증에서 WARNING 남으면 그것도 고치기"

    if [ -x "$CLAUDE" ]; then
        echo "$CLAUDE_PROMPT" | timeout 600 "$CLAUDE" --dangerously-skip-permissions -p - --output-format text \
            >> "$RUNTIME/health_audit_claude.log" 2>&1 &
        CLAUDE_PID=$!
        echo "[CLAUDE] PID=$CLAUDE_PID 백그라운드 실행"
    else
        echo "[CLAUDE] claude CLI not found at $CLAUDE — 수동 확인 필요"
    fi
else
    echo "[SKIP] 정상 — Claude Code 실행 불필요"
fi
