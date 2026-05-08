# G151 — Frequency Boost (score 75)

## Status
- `draft` (backtest rerun pending in this session)

## Parent
- `G150_user_intent`

## Single Change
- `mode_thresholds.futures_score_min`: `76 -> 75`

## Hypothesis
- 현재 라이브 오버라이드는 `PEPEUSDT` 단일 종목이라 진입 빈도가 낮다.
- `G150` 계열의 4종목 universe(ETH/SOL/DOGE/PEPE)를 유지한 채 점수 임계값을 1pt 완화하면:
- 진입 수는 증가하고, 거래당 기대값은 소폭 낮아질 수 있으나 총합 PnL은 유지 또는 개선 가능하다.

## Reference Evidence
- `G150` 카드 기준(60d, 4종목): `140 trades`, `WR 50%`, `total +2050 bps`
- `G135` 계열 히스토리에서 임계값 완화는 일반적으로 빈도 증가 효과가 확인됨.

## Next Validation
1. `STRATEGY_OVERRIDE_PATH=quant_binance/strategies/G151_freq_boost_score75/overrides.json` 로 replay/paper 재검증
2. 60d 기준 최소 체크:
3. `n_trades >= G150`
4. `total_net_bps > 0`
5. `win_rate >= 45%`
