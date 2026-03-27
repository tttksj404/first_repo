# /ohlcv-validate — OHLCV 시장 데이터 품질 검증

데이터 품질 문제는 백테스트 오류와 봇 오작동의 가장 흔한 원인입니다.
거래 전 반드시 실행.

## 사용법

```
/ohlcv-validate                          # 현재 데이터 파일 전체 검증
/ohlcv-validate data/BTC_1h.csv          # 특정 파일
/ohlcv-validate --pair BTC/USDT --tf 1h  # 거래소에서 직접 검증
```

## 검증 항목

### 1. 누락 캔들 감지
```python
# 예상 캔들 수 vs 실제 캔들 수
expected = (end_ts - start_ts) / timeframe_seconds
actual   = len(df)
missing  = expected - actual

# 연속 누락 구간 찾기
gaps = df[df.index.to_series().diff() > timeframe * 1.5]
```

### 2. 가격 이상치 (스파이크) 감지
```python
# 전 캔들 대비 ±10% 이상 순간 변동 → 의심
price_change = df['close'].pct_change().abs()
spikes = df[price_change > 0.10]

# High/Low가 Open/Close 범위를 크게 벗어나는 경우
invalid = df[df['high'] < df[['open', 'close']].max(axis=1)]
```

### 3. OHLC 논리 무결성
```python
# 반드시 성립해야 하는 조건들
assert (df['high'] >= df['low']).all()          # High ≥ Low
assert (df['high'] >= df['open']).all()         # High ≥ Open
assert (df['high'] >= df['close']).all()        # High ≥ Close
assert (df['low']  <= df['open']).all()         # Low ≤ Open
assert (df['low']  <= df['close']).all()        # Low ≤ Close
assert (df['volume'] >= 0).all()                # 거래량 ≥ 0
```

### 4. 타임스탬프 검증
```python
# UTC 기준인지 확인
# 중복 타임스탬프 제거
# 순서 정렬 확인
duplicates = df[df.index.duplicated()]
unsorted   = df[df.index != df.index.sort_values()]
```

### 5. 거래량 이상치
```python
# 거래량 0인 캔들 (휴장일 or 데이터 오류)
zero_volume = df[df['volume'] == 0]

# 평균 대비 10배 이상 거래량 급증 (오류 or 이벤트)
avg_vol = df['volume'].rolling(24).mean()
volume_spikes = df[df['volume'] > avg_vol * 10]
```

## 자동 수정 옵션

```
--fix-gaps       : 누락 캔들을 직전 캔들로 forward-fill
--remove-spikes  : ±15% 이상 스파이크 캔들 제거
--deduplicate    : 중복 타임스탬프 제거
--sort           : 시간 순서 정렬
```

## 출력 형식

```
OHLCV VALIDATION — BTC/USDT 1h (2024-01-01 ~ 2026-03-27)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
총 캔들        : 19,320 / 예상 19,488
누락 캔들      : 168개 (0.86%) ⚠️
가격 스파이크  : 3개 발견 (2024-03-05, 2024-08-12, 2025-01-19)
OHLC 무결성    : ✅ 정상
중복 타임스탬프: 0개 ✅
거래량 이상치  : 7개 ⚠️ (평균 10배 이상)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
판정: ⚠️ 수정 필요 — --fix-gaps --remove-spikes 실행 권장
백테스트 전 반드시 수정 완료
```
