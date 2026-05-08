# G1503 - No-Dead Expansion Slot CH1

- **Status**: bt-only paper-slot candidate
- **Parent**: G1165
- **Discovery**: G1300 two-slot grid search
- **TF / Symbol**: 1h, no-dead alt universe
- **Direction**: long only
- **Capital context**: 100 USD

## Thesis

G1503 is a lower-leverage, wider-hold expansion slot. It keeps the no-dead CH1
core but relaxes ATR lower bound to capture extra non-G1165 entries, uses only
6x leverage, and lets the trade run for 48 hours with a +16% take-profit.

## Entry Rules

- CH1/Mingogogo score >= 80.
- ATR percent 14h between 0% and 8%.
- Universe: no-dead alt universe.
- Side: long only.
- Max concurrent positions: 5.

## Exit Rules

- Take profit: +16% price move.
- Stop loss: -7.5% price move.
- Time exit: 48 bars / 48 hours.
- Conservative path assumption: if TP and SL touch in the same bar, SL wins.

## Positioning

- Leverage: 6x.
- Margin size per trade: 35% of 100 USD equity.
- Round-trip cost assumption: 24 bps.

## Backtest Result

Source: `quant_binance/strategies/_scripts/g1300_two_slot_results.json`

| Period | Trades | Win Rate | PnL USD | Annualized PnL | Liquidation Rate | Max Period DD |
|---|---:|---:|---:|---:|---:|---:|
| OOS22-23 | 19 | 52.63% | 166.87 | 83.44 | 0.00% | 51.08 |
| OOS24-Q1 | 34 | 61.76% | 478.36 | 382.89 | 0.00% | 89.79 |
| IS25-26 | 11 | 81.82% | 160.24 | 156.39 | 0.00% | 16.25 |
| Weighted | 64 | 62.50% | 805.47 | 188.46 | 0.00% | 89.79 |

## Slot Fit

- G1300 tested 1,152 CH1 slot candidates.
- PASS candidates: 256.
- G1503 is the strongest no-dead low-overlap expansion candidate after filtering out G1165 clones.
- Overlap with G1165:
  - Jaccard: 0.7164.
  - Candidate entries overlapping G1165: 75.00%.
  - G1165 entries covered by candidate: 94.12%.

## Decision

Promote G1503 as the second additional paper-slot candidate. It is less
independent than G1995, but it adds extra ATR-low entries, uses lower leverage,
keeps zero tested liquidations, and has better max-period drawdown than G1165.
Keep paper-only until runtime data confirms that the added lower-ATR entries
are not simply overfit to the historical windows.
