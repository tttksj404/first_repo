#!/bin/bash
# ============================================================
# B3 MSB 자동 재최적화 파이프라인
# ============================================================
# 월 1회 cron으로 실행.
# 1) freqtrade 데이터 다운로드 (최근 7개월)
# 2) Hyperopt 실행 (train: 최근6개월~최근1개월)
# 3) OOS 백테스트 (최근1개월)
# 4) 안전성 검증 (min trades, WR, DD, PnL)
# 5) PASS → strategy_override.approved.json 자동 업데이트
# 6) FAIL → 기존 파라미터 유지
# 7) 텔레그램 알림
#
# crontab: 0 3 1 * * /Users/tttksj/first_repo/scripts/b3_msb_auto_reoptimize.sh >> /Users/tttksj/first_repo/quant_runtime/b3_reoptimize.log 2>&1
# ============================================================

set -uo pipefail

REPO="/Users/tttksj/first_repo"
FT_DIR="$REPO/freqtrade_opt"
RUNTIME="$REPO/quant_runtime"
OVERRIDE="$RUNTIME/artifacts/strategy_override.approved.json"
PYTHON="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
FREQTRADE="/Library/Frameworks/Python.framework/Versions/3.14/bin/freqtrade"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S %Z')
LOG_DIR="$RUNTIME/artifacts/b3_reoptimize"

mkdir -p "$LOG_DIR"

echo "============================================"
echo "[B3-REOPT] $TIMESTAMP"
echo "============================================"

# ── 날짜 계산 ──
# Train: 7개월 전 ~ 1개월 전
# OOS:   1개월 전 ~ 오늘
TODAY=$(date '+%Y%m%d')
if [[ "$(uname)" == "Darwin" ]]; then
    TRAIN_START=$(date -v-7m '+%Y%m%d')
    OOS_START=$(date -v-1m '+%Y%m%d')
else
    TRAIN_START=$(date -d '-7 months' '+%Y%m%d')
    OOS_START=$(date -d '-1 month' '+%Y%m%d')
fi

# freqtrade 날짜 포맷: YYYYMMDD
echo "[B3-REOPT] Train: $TRAIN_START ~ $OOS_START"
echo "[B3-REOPT] OOS:   $OOS_START ~ $TODAY"

# ── Step 1: 데이터 다운로드 ──
echo "[B3-REOPT] Step 1: Downloading data..."
cd "$FT_DIR"
$FREQTRADE download-data \
    --config config.json \
    --timerange "${TRAIN_START}-${TODAY}" \
    --timeframe 1h \
    2>&1 | tail -5

if [ $? -ne 0 ]; then
    echo "[B3-REOPT] FAIL: Data download failed"
    $PYTHON "$REPO/scripts/b3_msb_notify.py" --status "FAIL" --reason "Data download failed"
    exit 1
fi

# ── Step 2: Hyperopt (train period) ──
echo "[B3-REOPT] Step 2: Running Hyperopt..."
HYPEROPT_RESULT="$LOG_DIR/hyperopt_${TODAY}.json"

$FREQTRADE hyperopt \
    --config config.json \
    --strategy B3_MSB_Strategy \
    --hyperopt-loss SharpeHyperOptLossDaily \
    --timerange "${TRAIN_START}-${OOS_START}" \
    --epochs 150 \
    --spaces buy \
    --no-color \
    --print-json \
    2>&1 | tee "$LOG_DIR/hyperopt_stdout_${TODAY}.log"

HYPEROPT_EXIT=$?

if [ $HYPEROPT_EXIT -ne 0 ]; then
    echo "[B3-REOPT] FAIL: Hyperopt failed (exit=$HYPEROPT_EXIT)"
    $PYTHON "$REPO/scripts/b3_msb_notify.py" --status "FAIL" --reason "Hyperopt execution failed"
    exit 1
fi

# ── Step 3 & 4: OOS 백테스트 + 검증 (Python 스크립트) ──
echo "[B3-REOPT] Step 3-4: OOS validation..."
$PYTHON "$REPO/scripts/b3_msb_oos_validate.py" \
    --ft-dir "$FT_DIR" \
    --override-path "$OVERRIDE" \
    --log-dir "$LOG_DIR" \
    --train-start "$TRAIN_START" \
    --oos-start "$OOS_START" \
    --today "$TODAY" \
    2>&1

VALIDATE_EXIT=$?

if [ $VALIDATE_EXIT -eq 0 ]; then
    echo "[B3-REOPT] SUCCESS: OOS passed, params updated"
else
    echo "[B3-REOPT] SKIP: OOS failed or insufficient, keeping current params"
fi

echo "[B3-REOPT] Cycle complete"
echo ""
