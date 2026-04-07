# /verify — 코드 검증 루프

코드를 커밋하거나 PR 올리기 전에 전체 품질 검사를 실행합니다.

## 실행 순서

1. **빌드 확인** — 컴파일/실행 오류 체크
2. **타입 체크** — mypy / tsc 실행 (해당 시)
3. **린트** — ruff / eslint / flake8
4. **테스트** — pytest / jest 실행 + 커버리지
5. **console.log / print 잔재** — 디버그 출력 검색
6. **git 상태** — 미커밋 변경사항 확인

## 모드

- `/verify` — 기본 전체 검사
- `/verify quick` — 빌드 + 타입만
- `/verify pre-commit` — 커밋 전 필수 항목만
- `/verify pre-pr` — PR 전 전체 (보안 포함)

## 출력 형식

```
VERIFY RESULT: PASS / FAIL
✅ Build        : OK
✅ Types        : OK
❌ Lint         : 3 issues (file.py:42)
✅ Tests        : 24/24 passed (87% coverage)
⚠️  Debug prints : 2 found
✅ Git          : Clean

PR Ready: NO — lint 수정 필요
```

CRITICAL / HIGH 이슈가 있으면 반드시 수정 후 재실행.
