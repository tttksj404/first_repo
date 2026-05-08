# G7822 - G1165-Dominating CH1 Quality Filter

- **Status**: research candidate, not deployed
- **Parent/Baseline**: G1165
- **Search source**: `quant_binance/strategies/_scripts/g1167_fast_g1165_dominance_search.py`
- **Result source**: `quant_binance/strategies/_scripts/g1167_fast_g1165_dominance_results.json`
- **Capital context**: 100 USD

## Thesis

G1165 was strong but sparse. G7822 keeps the CH1 path-safe core, removes weak legacy symbols, lowers the ATR floor from 3% to 2%, uses lower leverage with slightly higher margin, and gives winners more room. The goal is not a different alpha sleeve; it is a direct G1165 replacement candidate that beats the baseline on every primary metric before paper deployment.

## Entry Rules

- CH1 score >= 80.
- ATR percent 14h between 2% and 8%.
- Universe: no-dead alt universe, excluding WIF, LTC, BTC, MATIC, XRP, LINK.
- Side: long only.
- Max concurrent positions: 5.

## Exit Rules

- Take profit: +16% price move.
- Stop loss: -7.5% price move.
- Time exit: 48 bars / 48 hours.
- Conservative path assumption: if stop and take profit touch in the same path, stop loss wins first.

## Positioning

- Leverage: 8x.
- Margin size per trade: 30% of 100 USD equity.
- Round-trip cost assumption: 24 bps.

## G1165 Dominance Check

| Metric | G1165 | G7822 | Verdict |
|---|---:|---:|---|
| Trades | 51 | 53 | better |
| Win rate | 68.63% | 69.81% | better |
| PnL USD | 825.43 | 1015.58 | better |
| Annualized PnL | 193.13 | 237.62 | better |
| Monthly PnL | 16.09 | 19.80 | better |
| Max period DD | 96.75 | 92.88 | better |
| Liquidation rate | 0.00% | 0.00% | equal |
| All periods positive | true | true | equal |

## Period Results

| Period | Trades | Win Rate | PnL USD | Annualized PnL | Max DD | Liquidations |
|---|---:|---:|---:|---:|---:|---:|
| OOS22-23 | 17 | 58.82% | 220.01 | 110.00 | 39.81 | 0 |
| OOS24-Q1 | 31 | 70.97% | 624.64 | 499.99 | 92.88 | 0 |
| IS25-26 | 5 | 100.00% | 170.93 | 166.82 | 0.00 | 0 |
| Weighted | 53 | 69.81% | 1015.58 | 237.62 | 92.88 | 0 |

## One-Symbol-Out Sanity

Dropping any one active symbol kept all periods positive and liquidation-free. The weakest drops were SOL, ADA, and DOGE because they reduce trade count or win rate, but annualized PnL stayed above G1165.

## Decision

G7822 is the best direct G1165 replacement candidate found in this run. It is not a new orthogonal sleeve like G129183; it is a stricter and better-scoring CH1 quality variant. The right next step is paper deployment only if replacing or shadowing G1165 is desired.

## Frequency Repair Follow-up

Follow-up result: `runs/frequency_repair_20260507.md`.

The sparse-entry issue should not be solved by relaxing G7822 inside the same
CH1 family. A 19,200-spec frequency-repair search found no balanced 100+ trade
variant that preserved all-period positivity and quality gates. The practical
solution is to keep G7822 as the quality CH1 replacement/shadow candidate and
pair it with a separate high-frequency non-CH1 sleeve such as G4692
watch-confirm breakout for paper-observation cadence.

Moderate-frequency bundle result: `../G7822_G4692_frequency_solution/card.md`.

Revised high-cadence bundle result: `../G7822_G4692_G264402_high_cadence_bundle/card.md`.
