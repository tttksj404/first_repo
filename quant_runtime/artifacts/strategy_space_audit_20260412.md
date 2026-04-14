# 2026-04-12 코인 전략 전수조사 메모

## 결론

지금 레포는 이미 단순 지표 조합 수준은 꽤 넓게 훑고 있다. 문제는 "전략이 부족해서"라기보다 "현재 탐색 축이 1h 가격패턴 + 필터 적층에 치우쳐 있다"는 점이다.

현 시점에서 바로 밀어야 할 새 축은 아래 5개다.

1. 유니버스 상대강도/로테이션
2. 펀딩비·베이시스·미결제약정 기반 캐리/역추세
3. 거시 이벤트 윈도우 전용 규칙
4. 유동성 충격 후 단기 mean reversion
5. 페어/헤지형 상대가치

## 이번 조사에서 확인한 사실

### 1. 현재 1h 전략군은 이미 많이 돌려봤는데, 라이브 승격 후보가 비어 있다

- [`scripts/full_strategy_scan.py`](/Users/tttksj/first_repo/scripts/full_strategy_scan.py:1)는 추세, 모멘텀, 변동성, 복합, 세션, exit 최적화까지 합쳐 `13개 전략군 / 179개 조합`을 스캔한다.
- 동일 스캔 결과 파일 [`quant_runtime/output/signal_research/v4_full_scan_eligible.json`](/Users/tttksj/first_repo/quant_runtime/output/signal_research/v4_full_scan_eligible.json:1)은 `eligible=[]`다.
- 즉 현재 라이브 편입 기준에서는 "괜찮아 보이는 1h 전략"이 아니라 "통과 전략 없음"이 사실에 가깝다.

### 2. 과거 결과에서도 우세 전략은 강하지 않다

- [`quant_runtime/output/signal_research/backtest_results.json`](/Users/tttksj/first_repo/quant_runtime/output/signal_research/backtest_results.json:1) 상위권은 다음 정도다.
- `ETHUSDT Momentum_1h`: PF `1.1072`, 총 `5029.97bps`, 거래 `406`
- `SOLUSDT MA_Cross_1h`: PF `1.0407`, 총 `2779.33bps`, 거래 `710`
- 수익은 일부 있으나 PF가 낮고 드로다운이 커서 "새 주력 전략"으로 보기 어렵다.

### 3. 최신 통합형 브레이크아웃도 현재는 깨진 상태다

- [`quant_runtime/output/gpt54_unified_results.json`](/Users/tttksj/first_repo/quant_runtime/output/gpt54_unified_results.json:1) 기준:
- 총 거래 `36`
- 총 손익 `-22.14 USD`
- 손절 `24`, 익절 `7`, stale exit `5`
- `ETHUSDT`: `16` trades, WR `18.8%`, PnL `-9.66`
- `SOLUSDT`: `20` trades, WR `20.0%`, PnL `-12.48`
- 즉 "정교한 브레이크아웃 연속형"을 더 미세조정하는 것만으로는 부족하다.

## 이미 커버된 전략 축

### A. 독립형 백테스트 전략군

- [`scripts/full_strategy_scan.py`](/Users/tttksj/first_repo/scripts/full_strategy_scan.py:1)
- EMA cross
- MACD cross
- Ichimoku
- 4h→1h MTF trend
- Pullback
- EMA ribbon
- Donchian/Keltner breakout
- ROC momentum
- Bollinger squeeze
- RSI trend confirmation
- MACD + volume + ADX
- Funding contrarian
- Partial TP / time-decay exit

### B. 심화 탐색 전략군

- [`scripts/signal_research_v2.py`](/Users/tttksj/first_repo/scripts/signal_research_v2.py:193)
- `enhanced_ma_cross`
- [`scripts/signal_research_v2.py`](/Users/tttksj/first_repo/scripts/signal_research_v2.py:257)
- `momentum_trend`
- [`scripts/signal_research_v2.py`](/Users/tttksj/first_repo/scripts/signal_research_v2.py:411)
- `composite_strategy`

### C. 실제 엔진이 이미 쓰는 피처/필터 레이어

- [`quant_binance/features/extractor.py`](/Users/tttksj/first_repo/quant_binance/features/extractor.py:253)
- ADX, RSI, EMA cross, pullback, intraday trend
- taker imbalance
- funding rate, basis, open interest
- support alignment, sentiment support
- macro liquidity / macro risk
- alt breadth / alt liquidity / alt fundamental / alt smart money

- [`quant_binance/strategy/scorer.py`](/Users/tttksj/first_repo/quant_binance/strategy/scorer.py:60)
- score 기반 기대엣지 추정
- 비용/슬리피지/펀딩비 반영
- ADX + EMA cross 보너스
- alt overlay 보정

- [`quant_binance/strategy/regime.py`](/Users/tttksj/first_repo/quant_binance/strategy/regime.py:141)
- spot / futures / cash 모드 선택
- 메이저 우대, 거시 리스크 완화, support/sentiment relax, alt overlay gate

### D. 조합형 brute-force 토대

- [`scripts/exhaustive_all.py`](/Users/tttksj/first_repo/scripts/exhaustive_all.py:197)
- 20개 atomic filter
- ADX / trend strength / volume confirmation
- intraday alignment / ATR expansion
- RSI zone / TTM squeeze
- FVG / engulfing / VWAP / volume spike
- kill zone / MTF / EMA stack

이 스크립트는 이미 "필터 조합 x TP/SL/HOLD/LEV/SIDE" 방향의 대규모 탐색 틀을 가지고 있다. 따라서 다음 단계는 같은 필터를 더 미세하게 비트는 게 아니라, 아예 다른 전략 축을 넣는 것이다.

## 아직 약하거나 비어 있는 전략 축

### 1. 유니버스 상대강도 / 크로스섹셔널 로테이션

- 현재 엔진은 심볼별 판단은 강하지만 "오늘 어떤 코인을 버리고 어떤 코인으로 갈아탈지"를 강하게 모델링하지 않는다.
- 필요한 형태:
- top-K relative strength
- category rotation
- majors vs alts switching
- 주기적 리밸런싱

### 2. 펀딩비·베이시스·OI 기반 캐리/역추세 전용 전략

- 현재는 펀딩과 베이시스를 penalty/overlay로 쓰는 쪽에 가깝다.
- 별도 전략으로는 약하다.
- 필요한 형태:
- extreme positive funding short
- extreme negative funding long
- basis normalization mean reversion
- OI surge + price divergence unwind

### 3. 거시 이벤트 윈도우 전략

- 거시 정보는 리스크 완화용으로는 들어와 있지만, "이벤트 전후 n시간만 따로 규칙"은 약하다.
- 필요한 형태:
- FOMC / CPI / PPI / NFP 전후 majors-only
- 발표 전 포지션 축소 / 발표 후 확인 진입
- alt freeze window

### 4. 유동성 충격 후 단기 mean reversion

- 일반적 볼밴 역추세는 크립토에서 잘 안 먹혔다.
- 대신 다음 조건이 붙은 충격 복원형은 아직 약하게만 다뤄졌다.
- 필요한 형태:
- liquidation spike
- wick + OI flush
- funding extreme + reversal candle
- session open dislocation

### 5. 페어/헤지형 상대가치

- 지금은 사실상 방향성 전략 중심이다.
- 필요한 형태:
- ETH/BTC relative breakout
- SOL/ETH beta-adjusted spread
- majors long vs weak alts short

### 6. 알트 섹터/내러티브 로테이션

- [`quant_binance/ALTCOIN_INTELLIGENCE.md`](/Users/tttksj/first_repo/quant_binance/ALTCOIN_INTELLIGENCE.md:1)는 입력 스택을 정의하지만, 이를 활용한 전략 레이어는 아직 얇다.
- 필요한 형태:
- category momentum score 기반 top bucket rotation
- stablecoin flow + breadth expansion 진입
- unlock risk 회피

## 실전 탐색 우선순위

### Round 1. Rotation

- 목표: "한 종목 절대판단"에서 "오늘 살 종목 랭킹"으로 이동
- 후보:
- majors only top-1
- majors+alts top-2
- category momentum top bucket
- BTC dominance risk-off switch

### Round 2. Carry / Basis

- 목표: 가격추세가 아니라 구조적 과열/왜곡에서 엣지 찾기
- 후보:
- funding contrarian hold-to-next-window
- funding + OI divergence
- basis stretch mean reversion
- positive funding short with macro risk-off

### Round 3. Macro Window

- 목표: 이벤트 앞뒤를 별도 전략으로 분리
- 후보:
- pre-event flat / post-event confirmation
- majors-only during event
- alt freeze 12h
- event-day volatility breakout only

### Round 4. Shock Reversion

- 목표: 평시 역추세 말고 "충격 이후만" 반대로 잡기
- 후보:
- wick + volume spike + OI flush
- ATR shock + funding extreme
- session gap snapback

### Round 5. Relative Value

- 목표: 순방향 베팅 의존도를 낮추기
- 후보:
- ETH/BTC spread
- SOL vs majors strength spread
- strong majors long / weak alts short

## 지금 당장 버려야 할 접근

1. 1h 지표를 하나 더 얹는 단순 적층
2. PF 1.0~1.1 수준 전략을 파라미터 미세조정으로 살리려는 시도
3. 단일 심볼 기준 최적화
4. 정성적 가격대 고정 타깃

## 운영 메모

- "모든 경우의 수"를 진짜 완전탐색하는 건 가능은 하지만, 현재 레포 기준으로도 multiple testing 과적합 위험이 크다.
- 그래서 brute-force는 유지하되, 전략 축은 3~8개씩 나눠서 라운드별로 평가해야 한다.
- 승격 기준은 최소한 아래를 같이 봐야 한다.
- PF
- trade count
- max drawdown
- cost stress
- walk-forward
- paper/live sample quality

## 한 줄 판단

새 전략이 필요하다. 다만 답은 "EMA/MACD/볼밴 조합 더 섞기"가 아니라, `rotation + carry + macro window + shock reversion + relative value` 축으로 탐색면 자체를 옮기는 데 있다.
