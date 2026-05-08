# G7822 + G4692 + G4475 + G4673 + G4472 - Frequency-Solved Paper Bundle

- **Status**: frequency target passed; strict all-metric improvement not passed
- **Result source**: `quant_binance/strategies/_scripts/g7825_frequency_bundle_beam_search_results.json`
- **Target**: at least 30 de-duplicated direct entries/month
- **Interpretation**: multi-sleeve paper observation bundle, not one shared-equity live portfolio
- **Capital context**: 100 USD per sleeve in backtest accounting

## Why This Exists

G7822 improves G1165 quality but stays sparse. G7822+G4692 only reaches 13.33
unique entries/month. G264402 looked like a high-cadence fix, but was rejected
because local OI data does not cover the full validation window.

This bundle solves cadence using only full-window price-data candidates. The
search used timestamp/symbol/side de-duplication, so repeated entries across
similar breakout sleeves are not double-counted as unique paper observations.

## Components

| Component | Role | Trades/Month | WR | PnL | Max DD | Liq |
|---|---|---:|---:|---:|---:|---:|
| G7822 | Quality CH1 replacement | 1.03 | 69.81% | 1015.58 | 92.88 | 0 |
| G4692 | Watch-confirm breakout base cadence | 12.30 | 57.84% | 541.79 | 97.54 | 0 |
| G4475 | Controlled loose breakout ret8/vol25 mid exit | 20.31 | 53.17% | 222.31 | 113.88 | 0 |
| G4673 | Watch-confirm breakout c2 hold-break30 | 14.81 | 55.92% | 453.38 | 165.29 | 0 |
| G4472 | Controlled loose breakout break30/vol25 fast exit | 15.41 | 57.02% | 129.88 | 75.88 | 0 |

## Bundle Result

| Metric | Value |
|---|---:|
| Unique direct entries | 1632 |
| Unique entries/month | 31.80 |
| Slot-sum trades/month | 63.86 |
| Slot-sum WR | 55.91% |
| Slot-sum PnL | 2362.94 |
| Slot-sum annualized PnL | 552.87 |
| Max component period DD | 165.29 |
| Liquidations | 0 |
| All component periods positive | true |

## Period Check

| Period | Slot-Sum Trades | Trades/Month | WR | PnL |
|---|---:|---:|---:|---:|
| OOS22-23 | 1307 | 54.43 | 54.09% | 755.70 |
| OOS24-Q1 | 1272 | 84.80 | 56.76% | 1056.89 |
| IS25-26 | 698 | 56.74 | 57.74% | 550.35 |

## Decision

This is the first full-window validated bundle in this thread that clears the
>=30 unique entries/month paper-observation target.

Use it as the high-cadence paper validation plan:

- Keep G7822 as the quality benchmark.
- Keep G4692 as the base independent cadence sleeve.
- Add G4475, G4673, and G4472 to force enough paper observations.

Do not treat this as live-ready portfolio sizing. The added sleeves are
breakout-family variants, so a shared-capital runtime needs an allocator,
duplicate-entry lock, and family exposure cap before any live-facing step.

## Strict Quality Caveat

Follow-up strict search found no current full-window bundle that also keeps
G1165/G7822-level WR and DD while staying above 30 unique entries/month.

Best frequency-quality recheck:

| Bundle | Unique Entries/Month | WR | Max DD | Verdict |
|---|---:|---:|---:|---|
| G7822+G4692+G4472+G4474+G4604+G4677 | 30.28 | 56.99% | 166.19 | FAIL WR/DD |

See `runs/strict_quality_check_20260507.md`.

Additional high-WR repair attempts are documented in
`runs/high_wr_repair_attempts_20260507.md`. The short version: current
full-window price-data methods can solve frequency, but not the combination of
frequency plus G1165/G7822-level WR.
