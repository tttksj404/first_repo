# G4006 - Breakout Long Raw

- **Status**: paper-probe candidate, not live-approved
- **Parent**: none; intentionally non-CH1
- **Discovery**: G1304 multi-family non-overlap search, G1305 walk-forward filter validation
- **Exchange / Market**: Bitget USDT futures
- **TF / Symbol**: 1h, no_dead alt universe
- **Direction**: long only
- **Capital context**: 100 USD

## Thesis

G4006 is the cleanest G1503 replacement shape found so far because it does not
reuse CH1/Mingogogo score entries. It buys high-volume upside breakouts after a
24h momentum impulse, so it should diversify the active G1165 and proposed
G1995 CH1 slots instead of increasing the same-entry crowding.

## Entry Rules

- Close breaks the previous 24h high by at least 50 bps.
- 24h return is at least +10%.
- Current quote-volume ratio versus prior 48h median is at least 3.0.
- ATR percent 14h between 0% and 8%.
- Universe: no_dead runtime alt subset.
- Side: long only.
- Max concurrent positions: 5.

## Exit Rules

- Take profit: +6% price move.
- Stop loss: -8% price move.
- Time exit: 36 bars / 36 hours.
- Conservative path assumption: if TP and SL touch in the same bar, SL wins.

## Positioning

- Leverage: 8x.
- Margin size per trade: 20% of 100 USD equity.
- Round-trip cost assumption: 24 bps.

## Backtest Result

Source: `quant_binance/strategies/_scripts/g1304_multi_family_non_overlap_results.json`

| Period | Trades | Win Rate | PnL USD | Annualized PnL | Liquidation Rate | Max Period DD |
|---|---:|---:|---:|---:|---:|---:|
| OOS22-23 | 241 | 56.43% | 211.22 | 105.61 | 0.00% | 109.01 |
| OOS24-Q1 | 235 | 58.72% | 207.30 | 165.93 | 0.00% | 61.09 |
| IS25-26 | 129 | 57.36% | 77.21 | 75.35 | 0.00% | 96.29 |
| Weighted | 605 | 57.52% | 495.73 | 115.99 | 0.00% | 109.01 |

## Walk-Forward Result

Source: `quant_binance/strategies/_scripts/g1305_breakout_walkforward_filter_results.json`

| OOS Fold | Trades | Win Rate | PnL USD | Annualized PnL | Max DD |
|---|---:|---:|---:|---:|---:|
| Train OOS22, test OOS24 | 235 | 58.72% | 207.30 | 165.93 | 61.09 |
| Train OOS22+OOS24, test IS25 | 129 | 57.36% | 77.21 | 75.35 | 96.29 |
| Aggregate OOS | 364 | 58.24% | 284.51 | 125.12 | 96.29 |

## Slot Fit

- G1304 tested 328 non-CH1 multi-family variants.
- Strict PASS candidates: 0.
- Watchlist PASS candidates: 2.
- G4006 was the best multi-family watchlist candidate.
- G1165 overlap Jaccard: 0.0000.
- G1995 overlap Jaccard: 0.0000.

## Decision

Use G4006 as the primary G1503 replacement paper probe only after deploying the
dedicated breakout emulator. It is not a strict-pass production strategy: win
rate is below 60%, annualized all-period result is just under the strict 120 USD
gate, and drawdown is above the strict 100 USD gate. Its main strength is
independence from CH1 and consistent positive walk-forward OOS behavior.
