# /indicator-verify — 보조지표 계산 정확도 검증

코드에서 계산한 지표값이 TradingView / TA-Lib 기준값과 일치하는지 검증합니다.
지표 오류는 잘못된 신호의 가장 흔한 원인.

## 사용법

```
/indicator-verify                    # 현재 전략의 모든 지표 검증
/indicator-verify rsi                # RSI만 검증
/indicator-verify --compare talib    # TA-Lib과 비교
```

## 주요 지표별 검증 기준

### RSI (Relative Strength Index)
```python
# ✅ 올바른 구현
import pandas_ta as ta
rsi = ta.rsi(close, length=14)

# ❌ 흔한 실수 — 직접 구현 시 Wilder 평활화 미적용
# RSI 초기값은 단순 평균, 이후 Wilder 지수이동평균 사용

# 검증: TradingView와 소수점 2자리까지 일치해야 함
tolerance = 0.01
assert abs(my_rsi - reference_rsi) < tolerance
```

### EMA / SMA
```python
# ✅ EMA — adjust=False 필수 (TradingView 방식)
ema = close.ewm(span=20, adjust=False).mean()

# ❌ 흔한 실수
ema_wrong = close.ewm(span=20).mean()  # adjust=True가 기본값

# 검증: 첫 값, 중간값, 마지막값 비교
```

### MACD
```python
# 표준 파라미터: fast=12, slow=26, signal=9
# Signal line = 9 EMA of MACD line
# Histogram = MACD - Signal (not absolute value)

macd = ta.macd(close, fast=12, slow=26, signal=9)
# 반환값: MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
```

### 볼린저 밴드
```python
# 표준: 20기간 SMA ± 2 표준편차
# 표준편차는 모집단(ddof=0), 표본(ddof=1) 중 TradingView는 모집단
bb = ta.bbands(close, length=20, std=2.0, ddof=0)
```

### ATR (Average True Range)
```python
# Wilder 방식 (기본) vs EMA 방식 — 반드시 명시
atr = ta.atr(high, low, close, length=14)
# 첫 ATR = 14일 단순 평균 TR
# 이후 = (이전ATR × 13 + 현재TR) / 14
```

## 검증 자동화 코드

```python
def verify_indicator(my_values, reference_values, name, tolerance=0.01):
    """
    내 지표값 vs 참조값 비교
    마지막 100개 캔들 기준 (초기값 안정화 후)
    """
    diff = abs(my_values[-100:] - reference_values[-100:])
    max_diff = diff.max()
    mean_diff = diff.mean()

    if max_diff > tolerance:
        print(f"❌ {name}: 최대 오차 {max_diff:.4f} (허용: {tolerance})")
        # 오차 발생 위치 찾기
        bad_idx = diff.idxmax()
        print(f"   오차 위치: {bad_idx}, 내값: {my_values[bad_idx]:.4f}, 기준: {reference_values[bad_idx]:.4f}")
    else:
        print(f"✅ {name}: 정상 (평균 오차 {mean_diff:.6f})")
```

## 흔한 오류 패턴

| 오류 | 증상 | 원인 |
|------|------|------|
| RSI 값 차이 | 5~10 포인트 차이 | Wilder 평활화 미적용 |
| EMA 차이 | 초반 값 다름 | adjust=True 사용 |
| ATR 과소 | 첫 N개 캔들 0 | min_periods 미설정 |
| 볼린저 밴드 폭 다름 | 약간 넓거나 좁음 | ddof=1 vs ddof=0 |
| MACD 히스토그램 부호 반전 | 신호 반대로 | MACD-Signal 순서 반전 |

## 출력 형식

```
INDICATOR VERIFICATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RSI(14)         : ✅ 정상 (평균오차 0.000023)
EMA(20)         : ❌ 오차 발견 (최대 0.042 → adjust=True 원인)
MACD(12,26,9)   : ✅ 정상
볼린저밴드(20,2): ⚠️ 경미한 차이 (ddof 확인 필요)
ATR(14)         : ✅ 정상
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
수정 필요: EMA adjust=False 로 변경
```
