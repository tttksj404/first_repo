#!/bin/bash

# 1. 현재 스크립트가 위치한 디렉토리로 이동
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR/../analysis_guides"

# 2. 파이썬 스크립트 실행 (macOS용 python3 사용)
# 만약 환경이 다르다면 'which python3' 결과로 경로를 수정할 수 있습니다.
/usr/bin/python3 generate_leet_daily.py >> "$DIR/leet_auto_log.txt" 2>&1

echo "--- Execution at $(date) ---" >> "$DIR/leet_auto_log.txt"
