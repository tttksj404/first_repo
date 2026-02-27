# 🤖 Notion Automation Scripts Guide

이 폴더는 노션 API 제어 및 알고리즘 문제 정리를 위한 **무결성 보장 자동화 도구**들이 담겨 있습니다.

## 📂 핵심 도구 리스트

### 1. 코어 엔진 (Core Engine) - `notion_automation/core/`
- `core/notion_worker.py`: 블루프린트 데이터를 기반으로 쪼개기(Chunking) 및 재시도(Retry) 로직을 실행하는 표준 작업자입니다.
- `core/gpt_setup_prompt.txt`: 타 AI(GPT 등)와 협업 시 동일한 가독성/기술 원칙을 지키게 만드는 시스템 프롬프트입니다.

### 2. 고밀도 복구 스크립트 (Ultra-Detailed Rebuilders) - `notion_automation/ultra_rebuilders/`
사용자님이 만족하신 '연구소' 수준의 상세함을 보장하며, 실제 정답 코드를 포함하여 페이지를 통째로 재건축합니다.
- `ultra_rebuilders/worker_14_perfect.py`: 상어 초등학교 (다중 정렬)
- `ultra_rebuilders/worker_15_ultra.py`: 원판 돌리기 (원형 덱 조작)
- `ultra_rebuilders/worker_16_ultra.py`: 이차원 배열과 연산 (전치 행렬)
- `ultra_rebuilders/worker_17_ultra.py`: 경사로 (인덱스 가딩)
- `ultra_rebuilders/worker_19_ultra.py`: 연산자 끼워넣기 (백트래킹)
- `ultra_rebuilders/master_fix_13.py`: 마법사 상어와 파이어볼 (객체 분합)
- (기타 다수 배치/마스터 스크립트 포함)

### 3. 특정 문제 해결 (Specific Problem Fixes) - `notion_automation/fixes/`
- `fixes/fix_snake_deep.py`: 뱀 (Deque 시뮬레이션)
- `fixes/rebuild_shark_deep.py`: 아기 상어 (우선순위 BFS)
- `fixes/rebuild_link_deep.py`: 스타트와 링크 (백트래킹 팀 매칭)
- `fixes/rebuild_marble_deep.py`: 구슬 탈출 2 (4D BFS)
- `fixes/fix_empty_taxi.py`: 스타트 택시 (복합 BFS)

### 4. 분석 및 시스템 가이드 (Analysis & Guides) - `notion_automation/analysis_guides/`
- `analysis_guides/analyze_weak_points.py`: 전체 페이지 분석 후 오답 노트 생성.
- `analysis_guides/detailed_ai_guide.py`: AI 활용 백과사전 페이지 생성.
- `analysis_guides/enhance_notion_study.py`: 알고리즘별 필수 양식 및 혼합 패턴 주입.
- `analysis_guides/create_ai_guide.py`, `analysis_guides/update_ai_guide.py`: 가이드 생성 및 업데이트 도구.

### 5. 초기 도구 및 검색 라이브러리 (Legacy Tools) - `notion_automation/legacy_tools/`
