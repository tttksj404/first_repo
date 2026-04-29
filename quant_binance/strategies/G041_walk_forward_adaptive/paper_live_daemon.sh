#!/usr/bin/env bash
# G058 paper-live 무한 루프 daemon. 매 시간 1회 cycle 실행.
# 실행: bash paper_live_daemon.sh &  (background)
# 종료: kill <PID> 또는 ps + grep paper_live_daemon

set +e
ROOT="$HOME/Desktop/first_repo"
SCRIPT="$ROOT/quant_binance/strategies/G041_walk_forward_adaptive/paper_live.py"
PYTHON="C:/Users/SSAFY/AppData/Local/Programs/Python/Python311/python.exe"

cd "$ROOT" || exit 1

while true; do
  # 매 시간 정각에 맞춰 sleep
  NOW=$(date +%s)
  NEXT_HOUR=$(( ((NOW / 3600) + 1) * 3600 ))
  SLEEP_SEC=$(( NEXT_HOUR - NOW ))
  echo "[daemon $(date)] next cycle in ${SLEEP_SEC}s"
  sleep "$SLEEP_SEC"

  echo "[daemon $(date)] running cycle..."
  PYTHONIOENCODING=utf-8 "$PYTHON" "$SCRIPT" 2>&1 | head -10
  echo "[daemon $(date)] cycle done"
done
