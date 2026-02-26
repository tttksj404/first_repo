# 🤖 Notion Automation Scripts Guide

이 폴더는 노션 API 제어 및 알고리즘 문제 정리를 위한 **무결성 보장 자동화 도구**들이 담겨 있습니다.

## 📂 핵심 도구 리스트

### 1. 코어 엔진 (Core Engine)
- `notion_worker.py`: 블루프린트 데이터를 기반으로 쪼개기(Chunking) 및 재시도(Retry) 로직을 실행하는 표준 작업자입니다.
- `gpt_setup_prompt.txt`: 타 AI(GPT 등)와 협업 시 동일한 가독성/기술 원칙을 지키게 만드는 시스템 프롬프트입니다.

### 2. 고밀도 복구 스크립트 (Ultra-Detailed Rebuilders)
사용자님이 만족하신 '연구소' 수준의 상세함을 보장하며, 실제 정답 코드를 포함하여 페이지를 통째로 재건축합니다.
- `worker_14_perfect.py`: 상어 초등학교 (다중 정렬)
- `worker_15_ultra.py`: 원판 돌리기 (원형 덱 조작)
- `worker_16_ultra.py`: 이차원 배열과 연산 (전치 행렬)
- `worker_17_ultra.py`: 경사로 (인덱스 가딩)
- `worker_19_ultra.py`: 연산자 끼워넣기 (백트래킹)
- `master_fix_13.py`: 마법사 상어와 파이어볼 (객체 분합)

### 3. 특정 문제 해결 (Specific Problem Fixes)
- `fix_snake_deep.py`: 뱀 (Deque 시뮬레이션)
- `rebuild_shark_deep.py`: 아기 상어 (우선순위 BFS)
- `rebuild_link_deep.py`: 스타트와 링크 (백트래킹 팀 매칭)
- `rebuild_marble_deep.py`: 구슬 탈출 2 (4D BFS)
- `fix_empty_taxi.py`: 스타트 택시 (복합 BFS)

### 4. 분석 및 시스템 가이드 (Analysis & Guides)
- `analyze_weak_points.py`: 전체 페이지 분석 후 오답 노트 생성.
- `detailed_ai_guide.py`: AI 활용 백과사전 페이지 생성.
- `enhance_notion_study.py`: 알고리즘별 필수 양식 및 혼합 패턴 주입.

### 5. 초기 도구 및 검색 라이브러리 (Legacy Tools)
`legacy_tools/` 폴더에 위치하며, 초기 구조 분석 및 단순 업데이트용 스크립트들입니다.
- `search_notion.py`: 노션 페이지 검색 및 ID 추출.
- `read_notion_current.py`: 현재 노션 페이지 내용 읽기.
- `analyze_structure.py`: 노션 블록 구조 분석.
- `remodel_all_pages.py`: 초기 전체 페이지 리모델링 스크립트.

---

## 🛠️ 사용 시 주의사항
1. **무결성 검증:** 모든 스크립트는 실행 후 반드시 `GET` 요청을 통해 블록 개수를 재검증하는 루프가 포함되어 있습니다.
2. **API 안정성:** `time.sleep(0.5~1.0)`이 각 블록 전송 사이에 걸려 있으니, 작업 중 프로그램을 강제 종료하지 마세요.
3. **요약 금지:** 이 폴더의 모든 코드는 **'분량 타협 금지'** 원칙에 따라 작성되었습니다.
