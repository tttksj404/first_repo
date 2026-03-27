# /hyperopt-check — 파라미터 최적화 과최적화 방지

전략 파라미터를 최적화(Hyperopt)할 때 과최적화(Overfitting)를 방지하고 결과를 올바르게 검증합니다.

## 사용법

```
/hyperopt-check                      # 최적화 결과 전반 검증
/hyperopt-check --results results/   # 결과 디렉토리 지정
/hyperopt-check --walk-forward       # 워크포워드 검증 실행
```

## 과최적화 징후 감지

### 1. 결과가 너무 좋으면 의심
```
⚠️ 과최적화 징후:
  샤프 > 3.0      → 실거래에서 절대 재현 불가
  승률 > 75%      → 너무 완벽한 후향 최적화
  드로다운 < 5%   → 현실에서 불가능
  수익 팩터 > 5.0 → 데이터 스누핑 의심
```

### 2. 파라미터 안정성 체크
```python
# 최적 파라미터 근방에서 성과가 급격히 떨어지면 과최적화
param_sensitivity = {}
best_rsi_period = 14  # 최적값

for rsi_period in range(10, 20):
    result = backtest(rsi_period=rsi_period)
    param_sensitivity[rsi_period] = result['sharpe']

# ❌ 과최적화: 14만 높고 나머지는 모두 낮음
# ✅ 강건한 전략: 12~16 구간 모두 비슷한 성과
```

### 3. 워크포워드(Walk-Forward) 검증
```
데이터 분할 방법:
  전체 기간: 2022-01-01 ~ 2026-01-01 (4년)

  Window 1:
    학습(In-Sample):  2022-01 ~ 2023-06 (18개월)
    검증(OOS):        2023-07 ~ 2023-12 (6개월)

  Window 2:
    학습(In-Sample):  2022-07 ~ 2024-06 (24개월)
    검증(OOS):        2024-07 ~ 2024-12 (6개월)

  Window 3:
    학습(In-Sample):  2023-01 ~ 2025-06 (30개월)
    검증(OOS):        2025-07 ~ 2025-12 (6개월)

판단 기준:
  OOS 샤프 / IS 샤프 비율 > 0.5 → ✅ 강건
  OOS 샤프 / IS 샤프 비율 < 0.3 → ❌ 과최적화
```

### 4. 파라미터 공간 체크
```python
# ❌ 과도한 파라미터 → 데이터 스누핑
params = {
    'rsi_period': range(5, 50),     # 45개 옵션
    'ema_fast': range(5, 100),      # 95개 옵션
    'ema_slow': range(10, 200),     # 190개 옵션
    'atr_period': range(5, 30),     # 25개 옵션
    # 총 조합: 45 × 95 × 190 × 25 = 2천만 가지
    # 충분한 데이터 없이 탐색하면 과최적화 확실
}

# ✅ 적정 규모 (거래 횟수 × 5 이하의 조합)
# 예) 거래 200회 → 최대 1,000가지 조합
```

### 5. 상관관계 과다 지표 금지
```python
# ❌ 의미 없는 중복 지표 (모두 같은 것 측정)
signals = [
    rsi_signal,    # 모멘텀
    stoch_signal,  # 모멘텀 (RSI와 고상관)
    williams_r,    # 모멘텀 (RSI와 고상관)
]
# 최적화 시 세 개 파라미터 공간 탐색 → 데이터 스누핑

# ✅ 다른 정보를 측정하는 지표 조합
signals = [
    trend_signal,    # 추세 (EMA)
    momentum_signal, # 모멘텀 (RSI)
    volatility_signal # 변동성 (ATR)
]
```

## 검증 결과 해석

```
HYPEROPT CHECK RESULT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IS 샤프 비율  : 2.41
OOS 샤프 비율 : 1.18 (IS 대비 49%) ✅
파라미터 안정성: ✅ RSI 12~17 구간 모두 샤프 > 1.0
과최적화 징후  : 없음 ✅
파라미터 조합  : 1,200가지 (적정) ✅

최적 파라미터:
  RSI period : 14
  EMA fast   : 21
  EMA slow   : 55

권고: 이 파라미터로 2주 페이퍼 트레이딩 후 실거래 검토
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```
