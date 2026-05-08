# G1995 - Top10 Slot CH1

- **Status**: bt-only paper-slot candidate
- **Parent**: G1165
- **Discovery**: G1300 two-slot grid search
- **TF / Symbol**: 1h, top10 alt universe
- **Direction**: long only
- **Capital context**: 100 USD

## Thesis

G1995 keeps the path-safe CH1 lottery edge but changes the slot shape enough to
matter operationally: top10-only universe, relaxed ATR lower bound, and a wider
take-profit target. It is designed as an additional Oracle paper slot rather
than a direct replacement for G1165.

## Entry Rules

- CH1/Mingogogo score >= 80.
- ATR percent 14h between 0% and 8%.
- Universe: top10 alt subset.
- Side: long only.
- Max concurrent positions: 5.

## Exit Rules

- Take profit: +16% price move.
- Stop loss: -7.5% price move.
- Time exit: 36 bars / 36 hours.
- Conservative path assumption: if TP and SL touch in the same bar, SL wins.

## Positioning

- Leverage: 10x.
- Margin size per trade: 25% of 100 USD equity.
- Round-trip cost assumption: 24 bps.

## Backtest Result

Source: `quant_binance/strategies/_scripts/g1300_two_slot_results.json`

| Period | Trades | Win Rate | PnL USD | Annualized PnL | Liquidation Rate | Max Period DD |
|---|---:|---:|---:|---:|---:|---:|
| OOS22-23 | 16 | 68.75% | 216.24 | 108.12 | 0.00% | 50.42 |
| OOS24-Q1 | 31 | 64.52% | 489.56 | 391.86 | 0.00% | 97.89 |
| IS25-26 | 10 | 90.00% | 168.29 | 164.24 | 0.00% | 19.35 |
| Weighted | 57 | 70.18% | 874.09 | 204.51 | 0.00% | 97.89 |

## Slot Fit

- G1300 tested 1,152 CH1 slot candidates.
- PASS candidates: 256.
- G1995 was the highest slot-score candidate after penalizing overlap with G1165.
- Overlap with G1165:
  - Jaccard: 0.5211.
  - Candidate entries overlapping G1165: 64.91%.
  - G1165 entries covered by candidate: 72.55%.

## Decision

Promote G1995 as the first additional paper-slot candidate. It has higher
annualized backtest PnL than G1165 in the G1300 search and materially lower
entry overlap than same-universe variants. Keep paper-only until runtime fills
confirm that the wider +16% take-profit is not too optimistic.
