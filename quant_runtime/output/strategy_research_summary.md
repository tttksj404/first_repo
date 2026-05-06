# 크립토 전략 전수조사 종합 결과 (2026-04-12)

## 현재 시스템 보유 전략
1. **Regime-Switching + Predictability Score** (핵심) - 35개 피처 벡터, 5m 결정경계
2. **Funding Rate Contrarian** - 펀딩비 >=0.015% 시 역방향
3. **EMA Cross + ADX** - 심볼별 최적 EMA/ADX 프로필
4. **Pullback Entry** - EMA50 + RSI 과매도 복구
5. **Macro Event Calendar** - BLS CPI/PPI 이벤트 보수화
6. **News/Sentiment Signal** - Fear&Greed + Google News RSS

## 미구현 유망 전략 (오픈소스 + 리서치 기반)

### Tier 1: 즉시 적용 가능 (OHLCV 데이터만 필요)
1. **Smart Money Concepts (FVG + Order Block + BOS/CHoCH)**
   - 소스: github.com/joshyattridge/smart-money-concepts
   - Fair Value Gap: 갭 채움 평균회귀
   - Order Block: 대량 주문 집중 가격대
   - Break of Structure: 추세 전환 감지
   - 기존 시스템의 support/resistance 로직 대체/강화 가능

2. **MACD Histogram Momentum**
   - hist[t] - hist[t-1] / abs(hist[t-1])
   - 트렌드 강도 보조 가중치 (+3-5% 승률 개선 기대)

3. **RSI Divergence Detection**
   - 가격 신고/저가 vs RSI 괴리 감지
   - 거짓 신호 15-20% 감소 기대

4. **Stochastic RSI + K%D Cross**
   - 진입 확인 필터 (진입 정확도 +8-12%)

5. **VWAP Deviation Score**
   - VWAP = 기관 벤치마크 가격
   - (price - VWAP) / ATR -> 과매수/과매도 판단

6. **NostalgiaForInfinity (NFIX) 전략 패턴**
   - freqtrade 최고 인기 전략
   - 수십개 지표 AND/OR 조합 노이즈 필터링
   - 5m 타임프레임 직접 적용 가능

### Tier 2: 추가 데이터 필요 (API 기반)
7. **Funding Rate Momentum (변화 가속도)**
   - (funding[t] - funding[t-24h]) / |funding[t]|
   - 현재 funding contrarian 전략 +20-30% 수익 개선 기대

8. **Cross-Exchange Funding Rate Divergence**
   - 소스: github.com/aoki-h-jp/funding-rate-arbitrage
   - Bitget 지원, 거래소 간 펀딩비 차이 감지
   - 방향 시그널로 활용

9. **Liquidation Cluster Map**
   - 소스: github.com/aoki-h-jp/py-liquidation-map
   - 청산 밀집대 기반 SL/TP 최적화
   - 청산 캐스케이드 진입 타이밍

10. **OI Divergence (가격 vs Open Interest)**
    - 가격 상승 + OI 감소 = 숏커버 랠리 (약세)
    - 가격 상승 + OI 증가 = 신규 롱 진입 (강세)

### Tier 3: ML/고급 모델
11. **FreqAI 동적 가중치 + 레짐 필터**
    - 소스: github.com/Netanelshoshan/freqAI-LSTM
    - 트렌드 강도에 따라 지표 가중치 자동 조정
    - LSTM 3층(hidden=128, dropout=40%)

12. **GJR-GARCH Regime Switch**
    - 소스: github.com/etatx0/Regime-Switch
    - 비대칭 변동성 포착 (하락 시 변동성 확대)
    - Markov Chain 2-3 레짐 분류

13. **XGBoost + LSTM Hybrid**
    - LSTM: 시계열 패턴, XGBoost: 매크로/센티먼트
    - R2 ~0.98 (Springer 2025 연구)

14. **HMM + KAMA Adaptive**
    - 저변동성: 모멘텀 전략 / 고변동성: 평균회귀
    - Kaufman Adaptive MA로 노이즈 필터링

### Tier 4: 온체인/외부 데이터
15. **Exchange Inflow/Outflow Signal**
    - 대규모 거래소 유출 = 매집 시그널
    - 대규모 유입 = 매도 압력
    - Glassnode/CryptoQuant API 필요

16. **Stablecoin Inflow Momentum**
    - USDT/USDC 거래소 유입 가속 = 매수 대기 자금

17. **Correlation Shock Penalty**
    - BTC/알트 상관계수 급변 시 포트폴리오 리스크 감소

## 핵심 신규 변수 후보 (우선순위순)
| # | 변수명 | 유형 | 데이터 요구 | 기대 효과 |
|---|--------|------|------------|----------|
| 1 | fvg_score | SMC | OHLCV | 지지/저항 정확도 +25% |
| 2 | order_block_zone | SMC | OHLCV | 진입 정확도 +15% |
| 3 | macd_hist_momentum | 기술적 | OHLCV | 트렌드 강도 +3-5% |
| 4 | rsi_divergence | 기술적 | OHLCV | 거짓 신호 -15-20% |
| 5 | vwap_deviation | 기술적 | OHLCV | 과매수/과매도 판단 |
| 6 | funding_momentum | 구조적 | API | 펀딩 전략 +20-30% |
| 7 | oi_price_divergence | 구조적 | API | 추세 강도 검증 |
| 8 | liq_cluster_distance | 구조적 | 체결 | SL/TP 최적화 |
| 9 | volume_regime_shift | 기술적 | OHLCV | DD 감소 8-12% |
| 10 | stoch_rsi_signal | 기술적 | OHLCV | 진입 확인 +8-12% |
