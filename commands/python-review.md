# /python-review — Python 코드 리뷰

git diff로 변경된 .py 파일을 대상으로 보안·품질·관습 검사.

## 검사 항목

### CRITICAL (즉시 수정)
- SQL/커맨드 인젝션 취약점
- `eval()` / `exec()` 무분별한 사용
- 하드코딩된 API 키 / 시크릿
- `pickle` 역직렬화 위험
- 빈 `except:` 절

### HIGH (머지 전 수정)
- 타입 힌트 누락 (public 함수)
- mutable 기본 인자 (`def f(x=[])`)
- 예외 무시 (`except: pass`)
- `with` 문 없는 파일/소켓 처리
- 비관용적 루프 (`for i in range(len(x))`)

### MEDIUM (권고)
- PEP 8 위반
- docstring 누락
- `print()` 대신 `logging` 권장
- 비효율적 문자열 처리

## 정적 분석 도구 실행

```bash
ruff check .
mypy .
black --check .
```

## 승인 기준

- ✅ CRITICAL·HIGH 없음 → 승인
- ⚠️ MEDIUM만 → 조건부 승인
- ❌ CRITICAL·HIGH 존재 → 블록

## 코인 트레이딩 추가 체크
- API 키가 환경변수로 관리되는지
- 주문 수량/가격 계산에 float 대신 Decimal 사용 여부
- 예외 처리 시 포지션 정리 로직 존재 여부
