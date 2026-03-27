# /quant-review — 퀀트/트레이딩 코드 리뷰

코인 매매 전략 코드를 대상으로 로직 오류·리스크·성능을 검토합니다.

## 검사 항목

### CRITICAL (즉시 수정 — 실제 손실 유발 가능)
- **주문 수량/가격에 float 연산** — Decimal 또는 거래소 precision 사용 필수
- **API 키 하드코딩** — 환경변수로 분리
- **예외 발생 시 포지션 미정리** — 오픈 포지션 방치 위험
- **레버리지 값 하드코딩** — 설정 파일로 분리
- **시장가 주문 슬리피지 미고려** — 특히 유동성 낮은 페어

### HIGH (전략 실패 유발)
- **백테스트 룩어헤드 바이어스** — future 데이터가 현재 결정에 영향
- **수수료 미반영** — 매매 수수료, 펀딩피 누락
- **복수 신호 중복 진입** — 중복 오더 체크 로직 없음
- **포지션 크기 고정** — 자본 대비 % 기반 사이징 권장
- **WebSocket 재연결 로직 없음** — 연결 끊기면 신호 누락

### MEDIUM (성능·안정성)
- API rate limit 처리 없음
- 로깅 레벨 미분리 (DEBUG/INFO/ERROR)
- 헬스체크 / 알림 없음
- 전략 파라미터 하드코딩 (설정 파일로)

## 트레이딩 특화 패턴 체크

```python
# ❌ 위험
quantity = balance * 0.1 / price  # float 오차

# ✅ 안전
from decimal import Decimal
quantity = Decimal(str(balance)) * Decimal("0.1") / Decimal(str(price))
```

## 출력 형식

```
QUANT REVIEW: PASS / FAIL
💀 CRITICAL : 2건 (즉시 수정)
🔴 HIGH     : 3건
🟡 MEDIUM   : 5건
실거래 투입 전 CRITICAL·HIGH 모두 해결 필요
```
