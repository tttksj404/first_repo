# /checkpoint — 작업 체크포인트 저장/확인

개발 중 중요 시점에 상태를 저장하고 이전 상태와 비교합니다.

## 사용법

- `/checkpoint create <이름>` — 현재 상태 저장 (git stash or commit + 로그)
- `/checkpoint verify <이름>` — 저장된 체크포인트와 현재 비교
- `/checkpoint list` — 저장된 체크포인트 전체 목록
- `/checkpoint clear` — 오래된 것 정리 (최근 5개 유지)

## 저장 내용

- git SHA
- 변경된 파일 목록
- 테스트 통과 수 / 커버리지
- 빌드 상태
- 타임스탬프

## verify 출력 예시

```
CHECKPOINT DIFF: start → after-refactor
Files changed  : +3 / -1
Tests          : +5 passed / 0 failed
Coverage       : 82% → 87%
Build          : OK
```

## 활용 흐름

1. 기능 시작 전 `/checkpoint create start`
2. 핵심 구현 후 `/checkpoint create core`
3. 리팩터링 후 `/checkpoint verify start`
4. PR 전 최종 확인
