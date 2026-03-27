# /strategy-plan — 트레이딩 전략 설계

새로운 매매 전략을 체계적으로 설계합니다. Planner → Generator → Evaluator 패턴 적용.

## 사용법

```
/strategy-plan <전략 아이디어>
예) /strategy-plan BTC 볼린저밴드 + RSI 복합 전략
```

## 설계 단계

### Phase 1: Planner — 전략 명세화
다음 항목을 먼저 정의:

- **대상 페어**: BTC/USDT, ETH/USDT 등
- **타임프레임**: 1m / 5m / 15m / 1h / 4h / 1d
- **진입 조건**: 구체적인 지표 값과 조건
- **청산 조건**: TP / SL / 트레일링 / 시간 기반
- **포지션 방향**: Long only / Short only / 양방향
- **포지션 사이징**: 자본의 몇 %

### Phase 2: Generator — 구현 계획
```
필요한 파일:
├── strategy/my_strategy.py   # 핵심 로직
├── tests/test_my_strategy.py # 유닛 테스트
└── config/my_strategy.yaml   # 파라미터
```

주요 함수 설계:
- `generate_signal(candles)` → "LONG" | "SHORT" | None
- `calculate_position_size(balance, price)` → float
- `get_stop_loss(entry_price, direction)` → float

### Phase 3: Evaluator — 검증 기준 (Sprint Contract)
백테스트 통과 기준:
- [ ] 샤프 비율 > 1.0
- [ ] 최대 드로다운 < 20%
- [ ] 수수료 포함 수익률 > 0
- [ ] 거래 횟수 충분 (최소 30회 이상)
- [ ] 룩어헤드 바이어스 없음

### Phase 4: 백테스트 설계
```python
# 권장 백테스트 기간
train_period = "2023-01-01 ~ 2023-12-31"  # 학습
test_period  = "2024-01-01 ~ 2024-06-30"  # 검증
live_test    = "소액 실거래 2주"            # 최종 확인
```

## 출력 형식

전략 설계서를 `plans/<전략명>-plan.md`로 저장.
