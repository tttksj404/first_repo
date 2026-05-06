# 크립토 전략 전수조사 최종 제안서
## 3모델 MAD 토론 결과 (2026-04-12)

---

## 1. 3모델 투표 결과

| 순위 | Claude (Judge) | GPT-5.4 (Advocate) | Gemini (Devil's Advocate) | 합의 |
|------|---------------|-------------------|--------------------------|------|
| **1** | OI-Price Divergence | VWAP Deviation | SMC (FVG+OB) | **SMC + OI (공동 1위)** |
| **2** | SMC (FVG+OB) | OI-Price Divergence | FreqAI LSTM | **VWAP Deviation** |
| **3** | VWAP Deviation | Liquidation Cluster | Liquidation Cluster | **Liquidation Cluster** |

### 합의 분석
- **3모델 모두 선정**: SMC, OI-Price Divergence (2/3 공통)
- **2/3 모델 선정**: VWAP Deviation, Liquidation Cluster
- **Gemini만 선정**: FreqAI LSTM (나머지 2모델은 과적합 우려로 제외)
- **전원 제외**: MACD/RSI/Stoch (EMA/ADX 중복), Funding Momentum (5m에 느림)

### 신뢰도 점수
- Claude: 78/100
- GPT-5.4: 82/100 (기존 코드베이스 정밀 분석 기반)
- Gemini: 70/100 (ML 과적합 리스크 과소평가 우려)
- **평균: 77/100**

---

## 2. 최종 TOP 3 전략 + 구현 계획

### [전략 1] OI-Price Divergence (가짜 돌파 필터) — 구현 1순위

**선정 이유**: 현재 시스템에 OI 데이터(`oi_surge_percentile`)가 이미 있고, 구현 난이도 대비 효과 최대. 실거래 26건 중 WR 23.1%의 주요 원인인 "가짜 돌파"를 직접 제거.

**핵심 로직**:
```python
# extractor.py에 추가할 피처
def compute_oi_divergence(oi_series, price_series, lookback=24):
    """OI-Price Divergence Score: -1 ~ +1"""
    oi_delta_z = zscore(oi_series - ema(oi_series, lookback))
    
    # 가격 신고가인데 OI 동반 없음 = bearish divergence
    new_high = price_series[-1] > max(price_series[-lookback:-1])
    new_low = price_series[-1] < min(price_series[-lookback:-1])
    
    if new_high and oi_delta_z < -0.5:
        return -0.8  # 강한 약세 다이버전스 (가짜 돌파)
    elif new_high and oi_delta_z > 1.0:
        return +0.7  # 건강한 돌파 (OI 동반)
    elif new_low and oi_delta_z < -0.5:
        return +0.6  # 숏커버 바닥 (약세 소진)
    elif new_low and oi_delta_z > 1.0:
        return -0.7  # 건강한 하락 (신규 숏 유입)
    else:
        return 0.0

# scorer.py 통합
# oi_divergence > 0: predictability_score += 4점
# oi_divergence < -0.5: 진입 차단 (block_trade)
# oi_divergence < 0: predictability_score -= 6점 (비대칭 페널티)
```

**Predictability Score 통합**:
- `oi_confirm_score` = `oi_divergence * 6` (range: -6 ~ +4점)
- `block_trade` 조건: `price_breakout AND oi_delta_z <= 0`

**기대 효과** (보수적):
- WR: +2~4%p (가짜 돌파 차단)
- PF: +0.10~0.25
- MDD: -10~18% (헛된 진입 감소)
- 거래 빈도: -15~25% (노이즈 트레이드 감소 → 좋은 것)

**구현 난이도**: 낮음~중 (3-5일)
**필요 데이터**: Bitget OI API (이미 수집 중)

---

### [전략 2] SMC (Smart Money Concepts) — 구현 2순위

**선정 이유**: 기존 `support_alignment`, `breakout_norm` 위에 "구조적 문맥"을 추가. OHLCV만으로 구현 가능. `joshyattridge/smart-money-concepts` 라이브러리 참조 가능.

**핵심 구성요소**:

#### A. Fair Value Gap (FVG)
```python
def detect_fvg(high, low, close, min_gap_bps=8, max_gap_bps=60):
    """3-캔들 패턴: 이전 고가 < 다음 저가 → 갭 존재"""
    gap_up = low[-1] > high[-3]  # 상승 FVG
    gap_down = high[-1] < low[-3]  # 하락 FVG
    gap_size_bps = abs(low[-1] - high[-3]) / close[-2] * 10000
    
    if gap_up and min_gap_bps <= gap_size_bps <= max_gap_bps:
        return {'type': 'bullish', 'zone': (high[-3], low[-1]), 'size_bps': gap_size_bps}
    elif gap_down and min_gap_bps <= gap_size_bps <= max_gap_bps:
        return {'type': 'bearish', 'zone': (high[-1], low[-3]), 'size_bps': gap_size_bps}
    return None
```

#### B. Order Block (OB)
```python
def detect_order_block(ohlcv, lookback=20):
    """추세 전환 직전 마지막 역방향 캔들 = 기관 주문 집중 영역"""
    for i in range(-lookback, 0):
        # 상승 전 마지막 하락 캔들 (bullish OB)
        if close[i] < open[i] and close[i+1] > open[i+1]:
            displacement = (close[i+1] - open[i+1]) / atr > 1.5
            if displacement:
                return {'type': 'bullish', 'zone': (low[i], high[i])}
    return None
```

#### C. Break of Structure (BOS) / Change of Character (CHoCH)
```python
def detect_structure_break(highs, lows, lookback=20):
    """스윙 고/저점 돌파 감지"""
    swing_highs = find_swing_highs(highs, lookback)
    swing_lows = find_swing_lows(lows, lookback)
    
    # BOS: 추세 방향 유지하면서 구조 돌파
    bos_up = highs[-1] > swing_highs[-1] and lows[-1] > swing_lows[-2]
    # CHoCH: 추세 방향 전환
    choch_up = highs[-1] > swing_highs[-1] and lows[-3] < swing_lows[-1]
    
    return {'bos_up': bos_up, 'choch_up': choch_up, ...}
```

**진입 로직 (통합)**:
```python
# 롱 진입
if (trend_direction == 1 and adx >= 25 and
    bos_up and                          # 구조 돌파 확인
    price_in(fvg_zone or ob_zone) and   # FVG/OB 리테스트
    volume_confirmation >= 0.6 and      # 거래량 동반
    oi_divergence > 0 and               # OI 확인 (전략1 연계)
    predictability_score >= 65):
    
    enter_long()
    sl = min(ob_low, fvg_low) - 0.2 * atr_5m
    tp1 = entry + 1.0 * R  # 부분 익절
    tp2 = prior_liquidity_high or entry + 2.2 * R
```

**Predictability Score 통합**:
- `smc_structure_score` = FVG(0.3) + OB(0.3) + BOS/CHoCH(0.4) → 0~1
- `predictability_score += smc_structure_score * 7` (최대 +7점)
- `gross_expected_edge_bps += smc_structure_score * 8` (최대 +8bps)

**기대 효과** (보수적):
- WR: +3~6%p
- PF: +0.15~0.35
- EV/trade: +6~12bps
- RR비: 1.5~2.5

**리스크**:
- FVG/OB 정의의 주관성 → 명확한 알고리즘 정의 필수
- Curve-fitting 위험 → ablation test로 검증
- 횡보장 휩쏘 → ADX 필터로 방어

**구현 난이도**: 중 (1-2주)
**필요 데이터**: OHLCV만 (추가 없음)

---

### [전략 3] VWAP Deviation Score — 구현 3순위

**선정 이유**: 5m에서 가장 실전적인 "진입가격 최적화 도구". 트렌드 pullback과 횡보 mean-reversion 모두 커버.

**핵심 로직**:
```python
def compute_vwap(price, volume, from_timestamp):
    """Volume Weighted Average Price"""
    cum_pv = cumsum(price * volume, from=from_timestamp)
    cum_v = cumsum(volume, from=from_timestamp)
    vwap = cum_pv / cum_v
    return vwap

def vwap_deviation_score(close, vwap, lookback=96):
    """VWAP 편차 z-score"""
    deviation = close - vwap
    dev_z = zscore(deviation, lookback)
    return dev_z
```

**진입 로직**:
```python
session_vwap = compute_vwap(close, volume, from_utc_0000)
dev_z = vwap_deviation_score(close, session_vwap, 96)

# A. 트렌드 풀백 (ADX >= 20, 트렌드 방향 확인)
if trend_direction == 1 and adx >= 20:
    if -1.8 < dev_z < -0.4 and close > session_vwap:  # VWAP 근접 풀백
        enter_long()
        sl = max(0.8 * atr, 0.5 * abs(close - session_vwap))
        tp1 = session_vwap + 1.0 * std_dev
        tp2 = prior_swing_high

# B. 횡보 평균회귀 (ADX < 18)
if adx < 18:
    if dev_z >= 2.2 and oi_delta_z <= 0:  # 과매수 + OI 미확인
        enter_short(size_mult=0.5, lev_cap=4)
        tp = session_vwap
    elif dev_z <= -2.0 and oi_delta_z >= 0:  # 과매도
        enter_long(size_mult=0.5, lev_cap=4)
        tp = session_vwap
```

**VWAP 세션 정의 (핵심)**:
- **기본 VWAP**: UTC 00:00 앵커 (24h 롤링)
- **펀딩 VWAP**: 마지막 펀딩 정산 시점 앵커 (8h 롤링)
- 두 VWAP의 교차/이격도도 추가 시그널 가능

**Predictability Score 통합**:
- 트렌드 레짐: `+2~3점` (pullback 확인용)
- 비트렌드 레짐: 별도 서브북으로 운영 (mean-reversion)
- `vwap_regime_score = clip(abs(dev_z) / 2, 0, 1)` → 스코어 가중치

**기대 효과** (보수적):
- 서브북 WR: 53~58%
- PF: 1.15~1.35
- EV/trade: +3~6bps
- 진입가격 개선: 2~5bps (슬리피지 감소 효과)

**리스크**:
- 24/7 크립토에서 세션 정의 민감 → 백테스트 시 세션 변경 금지
- 강한 뉴스장에서 VWAP 복귀 실패 → 이벤트 윈도우 필터 필수
- 추세장에서 mean-reversion 모드 오작동 → ADX 게이트 필수

**구현 난이도**: 중 (1주)
**필요 데이터**: OHLCV만 (추가 없음)

---

## 3. 통합 아키텍처

```
[기존 시스템]                    [신규 추가]
                                 
EMA/ADX/ATR ──┐                 
Pullback ─────┤                 SMC (FVG+OB+BOS) ──┐
Funding Rate ─┤ Predictability  OI Divergence ─────┤ Enhanced
Macro Event ──┤ Score           VWAP Deviation ────┤ Score
Sentiment ────┤ (기존 35개)      Liq Cluster* ─────┘ (+4 피처)
Overheat ─────┘                 
                                 
         ↓                               ↓
   [진입 결정]  ←── 합산 ───→  [강화된 진입 결정]
         ↓                               ↓
   [기존 SL/TP] ←── 개선 ───→ [VWAP+Liq 기반 SL/TP]
```

### 구현 순서 (시간순)

| 단계 | 전략 | 기간 | 의존성 |
|------|------|------|--------|
| **1단계** | OI-Price Divergence | 3-5일 | 없음 (OI 데이터 이미 존재) |
| **2단계** | VWAP Deviation | 1주 | 없음 (OHLCV만) |
| **3단계** | SMC (FVG+OB+BOS) | 1-2주 | 없음 (OHLCV만) |
| **4단계** | Liquidation Cluster | 2-3주 | 체결 데이터 피드 구축 |

---

## 4. 백테스트 계획

### 필수 검증 항목 (CLAUDE.md 준수)
1. **Ablation Test**: baseline → +OI → +VWAP → +SMC → +OI+VWAP+SMC
2. **Walk-Forward**: 4-fold 시간순, WF >= 3/4
3. **Monte Carlo**: 1000회, ruin <= 5%
4. **Fee-safe**: fee / sl_dollar < 0.20
5. **슬리피지 스트레스**: 0/5/10/15/20bps
6. **파라미터 감도**: 인접 조합 10+개 전부 수익

### 주의사항 (3모델 공통 권고)
- **bar-close only**: SMC의 BOS/CHoCH/FVG를 intrabar로 읽으면 look-ahead bias
- **OI timestamp 정렬**: 1-bar misalignment가 성능 크게 부풀림
- **VWAP 세션 고정**: 백테스트 중간에 세션 정의 변경 금지
- **중복 효과 할인**: 개별 개선치 합의 40~60%만 총 uplift로 인정
- **레버리지 고정**: 1~20x 범위, 강제청산 buffer + funding 비용 포함

---

## 5. 불확실한 점 (확실성 검증)

| 항목 | 확실성 | 더 확인 필요한 것 |
|------|--------|------------------|
| OI Divergence 효과 | 70% | Bitget OI 데이터 품질/지연 시간 실측 |
| SMC 알고리즘 재현성 | 60% | FVG/OB 정의를 5m에서 실제 테스트 |
| VWAP 세션 최적 앵커 | 55% | UTC00/펀딩시점/Asian open 비교 테스트 |
| 전략 간 상관관계 | 50% | 동시 발화 빈도, 중복 시그널 비율 측정 |
| 실거래 슬리피지 | 65% | Paper trading 2주 이상 필요 |

**한 줄 결론**: 지금 시스템은 이미 트렌드 엔진이므로, 다음 한 방은 MACD나 ML이 아니라 **OI로 가짜 돌파를 제거하고, SMC로 구조를 붙이고, VWAP로 진입가를 개선**하는 방향이 가장 높은 지속 EV를 낸다.
