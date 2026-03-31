#!/bin/bash
# 코인 매매 프로그램 4시간 정기 전수조사 + 자동 수정
# crontab: 17 */4 * * * /Users/tttksj/first_repo/scripts/quant_health_audit.sh >> /Users/tttksj/first_repo/quant_runtime/health_audit.log 2>&1

set -euo pipefail
REPO="/Users/tttksj/first_repo"
RUNTIME="$REPO/quant_runtime"
PYTHON="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
CLAUDE="/Users/tttksj/.local/bin/claude"
AUDIT_RESULT_FILE="$RUNTIME/health_audit_latest.txt"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S %Z')

echo "============================================"
echo "[HEALTH_AUDIT] $TIMESTAMP"
echo "============================================"

WARNINGS=0
CRITICALS=0

# --- 1. 프로세스 상태 ---
echo ""
echo "[1] 프로세스 상태"
PROCS=$(pgrep -f quant_binance 2>/dev/null | wc -l | tr -d ' ')
if [ "$PROCS" -ge 1 ]; then
    echo "  OK: quant_binance 프로세스 ${PROCS}개 실행 중"
else
    echo "  CRITICAL: quant_binance 프로세스 없음!"
    CRITICALS=$((CRITICALS+1))
fi

# Health file
if [ -f "$RUNTIME/live_supervisor_health.json" ]; then
    STATUS=$($PYTHON -c "import json; d=json.load(open('$RUNTIME/live_supervisor_health.json')); print(d.get('status','unknown'))" 2>/dev/null || echo "parse_error")
    echo "  Health status: $STATUS"
    if [ "$STATUS" != "healthy" ]; then
        echo "  WARNING: health status is $STATUS"
        WARNINGS=$((WARNINGS+1))
    fi
else
    echo "  WARNING: health file missing"
    WARNINGS=$((WARNINGS+1))
fi

# Recent errors in supervisor log
if [ -f "$RUNTIME/live_supervisor.log" ]; then
    ERROR_COUNT=$(tail -200 "$RUNTIME/live_supervisor.log" | grep -ci "error\|traceback\|exception" 2>/dev/null; true)
    ERROR_COUNT=${ERROR_COUNT:-0}
    echo "  Recent errors in log (last 200 lines): $ERROR_COUNT"
    if [ "$ERROR_COUNT" -gt 10 ]; then
        echo "  WARNING: high error rate in supervisor log"
        WARNINGS=$((WARNINGS+1))
    fi
fi

# --- 2. 데이터 품질 ---
echo ""
echo "[2] 데이터 품질"
$PYTHON -c "
import json
from pathlib import Path
from collections import Counter

summary_path = Path('$RUNTIME/output/paper-live-shell/latest/summary.json')
if not summary_path.exists():
    print('  WARNING: summary.json not found')
    exit(1)

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
        print(f'  CRITICAL: 0bps 비율 {ratio:.0f}% — last_trade_price 갱신 버그 재발 가능!')
    elif ratio > 20:
        print(f'  WARNING: 0bps 비율 {ratio:.0f}% — 모니터링 필요')
    else:
        print(f'  OK: 0bps 비율 정상')

# Learning data
valid = [t for t in strat if (t.get('entry_predictability_score', 0) or 0) > 0]
print(f'  학습 가능 데이터: {len(valid)}건 / 50건 임계치 ({len(valid)/50*100:.0f}%)')
" 2>/dev/null || echo "  WARNING: data quality check failed"

# --- 3. 리소스 ---
echo ""
echo "[3] 리소스"

# Supervisor log size
if [ -f "$RUNTIME/live_supervisor.log" ]; then
    LOG_MB=$(du -m "$RUNTIME/live_supervisor.log" | cut -f1)
    echo "  supervisor.log: ${LOG_MB}MB"
    if [ "$LOG_MB" -gt 200 ]; then
        echo "  WARNING: supervisor.log > 200MB"
        WARNINGS=$((WARNINGS+1))
    fi
fi

# Output disk usage
OUTPUT_MB=$(du -sm "$RUNTIME/output" 2>/dev/null | cut -f1 || echo "0")
echo "  output 디렉토리: ${OUTPUT_MB}MB"
if [ "$OUTPUT_MB" -gt 5000 ]; then
    echo "  WARNING: output > 5GB"
    WARNINGS=$((WARNINGS+1))
fi

# Memory usage
MEM_INFO=$(ps aux | grep "quant_binance" | grep -v grep | awk '{sum+=$6} END {printf "%.0f", sum/1024}' 2>/dev/null || echo "0")
echo "  quant_binance 메모리: ${MEM_INFO}MB"
if [ "$MEM_INFO" -gt 1000 ]; then
    echo "  WARNING: 메모리 사용량 > 1GB"
    WARNINGS=$((WARNINGS+1))
fi

# --- 4. self_healing ---
echo ""
echo "[4] Self-healing"
$PYTHON -c "
import json
from pathlib import Path
from collections import Counter

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
else:
    print('  이벤트 없음')
" 2>/dev/null || echo "  self_healing check skipped"

# --- 5. API 에러 ---
echo ""
echo "[5] Bitget API"
$PYTHON -c "
import json
from pathlib import Path

for log_name in ['live_orders', 'tested_orders']:
    total = 0
    for f in Path('$RUNTIME/output/paper-live-shell').rglob(f'{log_name}.jsonl'):
        total += sum(1 for _ in f.open())
    print(f'  {log_name}: {total}건')
" 2>/dev/null || echo "  API check skipped"

# Check for 429/5xx in supervisor log
if [ -f "$RUNTIME/live_supervisor.log" ]; then
    RATE_LIMIT=$(tail -500 "$RUNTIME/live_supervisor.log" | grep -ci "429\|rate.limit" 2>/dev/null; true)
    RATE_LIMIT=${RATE_LIMIT:-0}
    SERVER_ERR=$(tail -500 "$RUNTIME/live_supervisor.log" | grep -ci "HTTP 50[0-9]" 2>/dev/null; true)
    SERVER_ERR=${SERVER_ERR:-0}
    echo "  최근 429 에러: ${RATE_LIMIT}건"
    echo "  최근 5xx 에러: ${SERVER_ERR}건"
    if [ "$RATE_LIMIT" -gt 5 ]; then
        echo "  WARNING: rate limit 빈발"
        WARNINGS=$((WARNINGS+1))
    fi
fi

# --- 결과 ---
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

# --- 6. Claude Code 자동 수정 ---
if [ "$CRITICALS" -gt 0 ] || [ "$WARNINGS" -ge 1 ]; then
    # audit 결과를 파일로 저장 (Claude에 전달용)
    AUDIT_SUMMARY="health audit at $TIMESTAMP found CRITICAL=$CRITICALS WARNING=$WARNINGS."

    # 프로세스 없으면 재시작 프롬프트
    if [ "$PROCS" -lt 1 ]; then
        AUDIT_SUMMARY="$AUDIT_SUMMARY Process dead: restart needed."
    fi

    # 로그 크기 문제
    if [ -f "$RUNTIME/live_supervisor.log" ]; then
        LOG_MB_CHECK=$(du -m "$RUNTIME/live_supervisor.log" | cut -f1)
        if [ "$LOG_MB_CHECK" -gt 200 ]; then
            AUDIT_SUMMARY="$AUDIT_SUMMARY supervisor.log=${LOG_MB_CHECK}MB (>200MB, needs rotation)."
        fi
    fi

    echo "[CLAUDE] 자동 수정 시작: $AUDIT_SUMMARY"

    # Claude Code 비대화형 실행 — 진단 + 수정 + 재검증
    CLAUDE_PROMPT="코인 매매 프로그램 정기 health audit 결과:

${AUDIT_SUMMARY}

다음을 수행해줘:
1. 위 문제의 근본 원인을 코드에서 찾아서 수정
2. 프로세스가 죽었으면 재시작 (bash scripts/quant_run_live_orders.sh quant_runtime)
3. supervisor.log 200MB 넘으면 수동 로테이션 (mv → .bak, 새 로그 시작)
4. 수정 후 테스트 실행 (python3 -m unittest tests.test_quant_binance_learning tests.test_quant_binance_overlays -v)
5. 문제 없으면 커밋
6. 수정 결과를 $RUNTIME/health_audit_fix_result.txt 에 기록

주의: 불필요한 변경 금지. 확실한 버그만 수정. 데몬은 watchdog이 관리하므로 kill 후 watchdog에 맡기거나 직접 재시작."

    if [ -x "$CLAUDE" ]; then
        echo "$CLAUDE_PROMPT" | timeout 600 "$CLAUDE" --dangerously-skip-permissions -p - --output-format text \
            >> "$RUNTIME/health_audit_claude.log" 2>&1 &
        CLAUDE_PID=$!
        echo "[CLAUDE] PID=$CLAUDE_PID 로 백그라운드 실행 시작"
    else
        echo "[CLAUDE] claude CLI not found at $CLAUDE — 수동 확인 필요"
    fi

    # 재검증은 Claude가 완료 후 자체적으로 수행
else
    echo "[SKIP] 정상 상태 — Claude Code 실행 불필요"
fi
