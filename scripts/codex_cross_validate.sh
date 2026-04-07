#!/bin/bash
# OpenAI 서버 안정 시 자동 교차검증
REPO="/Users/tttksj/first_repo"
cd "$REPO"

PROMPT="코인 매매 프로그램 교차검증. 5개 개선사항 각각 OK/문제/개선필요 판정.
1. bitget 429→65초재시도, 5xx→백오프, watchdog circuit breaker
2. 메모리: list+prune 500~1000, deque 2000, identity정리. 844→66MB
3. 학습: kline→last_trade_price갱신, edge_table복원, adopted학습포함
4. 3시간 health audit→Claude자동수정, 디스크자동정리
5. autotuner: 6시간마다 score/stop/sizing분석→override적용→15trades후되돌리기
위험이나 edge case 지적해줘."

for i in 1 2 3; do
    RESULT=$(codex exec --full-auto "$PROMPT" 2>&1)
    if echo "$RESULT" | grep -q "ERROR"; then
        echo "[$(date)] attempt $i failed, retrying in 5min..." >> "$REPO/quant_runtime/codex_crossval.log"
        sleep 300
    else
        echo "$RESULT" >> "$REPO/quant_runtime/codex_crossval.log"
        echo "[$(date)] cross-validation complete" >> "$REPO/quant_runtime/codex_crossval.log"
        exit 0
    fi
done
echo "[$(date)] all attempts failed" >> "$REPO/quant_runtime/codex_crossval.log"
