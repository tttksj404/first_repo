# G7822 + G4692 - Quality plus Moderate-Frequency Paper Bundle

- **Status**: validated moderate-frequency base; superseded for high cadence by `../G7822_G4692_G4475_G4673_G4472_frequency_solved_bundle/card.md`
- **Components**: G7822 quality CH1 replacement + G4692 watch-confirm breakout
- **Result source**: `quant_binance/strategies/_scripts/g7822_g4692_frequency_solution_results.json`
- **Capital context**: 100 USD per sleeve

## Thesis

G7822 is the better G1165 replacement candidate, but it remains sparse. Trying
to relax the same CH1 family enough to create frequent fills damaged expectancy
or period consistency. The frequency problem is therefore solved by pairing the
quality CH1 sleeve with a non-CH1 high-cadence sleeve.

G4692 is the current best fit because it is a watch-confirm breakout strategy
with much higher trade count and zero direct entry overlap with G7822 in the
validation windows.

## Component Roles

| Component | Role | Keep / Change |
|---|---|---|
| G7822 | Higher-quality CH1 replacement or shadow for G1165 | Keep unchanged |
| G4692 | High-frequency non-CH1 paper-observation sleeve | Pair with G7822 |

## Combined Result

This is a slot-sum paper observation bundle, not a single shared-equity
execution simulation.

| Period | G7822 Trades | G4692 Trades | Combined Trades | Trades/Month | Win Rate | PnL USD | Liquidations |
|---|---:|---:|---:|---:|---:|---:|---:|
| OOS22-23 | 17 | 250 | 267 | 11.12 | 56.55% | 485.10 | 0 |
| OOS24-Q1 | 31 | 246 | 277 | 18.47 | 60.29% | 803.71 | 0 |
| IS25-26 | 5 | 135 | 140 | 11.38 | 60.00% | 268.56 | 0 |
| Weighted | 53 | 631 | 684 | 13.33 | 58.77% | 1557.37 | 0 |

## Frequency Gate

Original target: at least 4 paper-observation trades/month.

Result: 13.33 trades/month.

Original verdict: PASS.

Revised target after user feedback: at least 30 paper-observation trades/month.

Revised verdict: FAIL. This two-sleeve bundle is an improvement over G7822
alone, but it is not enough for fast paper validation.

## Overlap Check

Direct timestamp/symbol/side overlap between G7822 and G4692:

| Metric | Value |
|---|---:|
| Overlap trades | 0 |
| Jaccard overlap | 0.000000 |
| G7822 covered by G4692 | 0.00% |
| G4692 covered by G7822 | 0.00% |

## Decision

Use this bundle only as a moderate-frequency stepping stone:

- G7822 answers: "Is there a better G1165 replacement?"
- G4692 answers: "Can paper fills happen often enough to observe quickly?"

Do not relax G7822 further for frequency. That path was tested and rejected.
The attempted G264402 high-cadence bundle was rejected after full-window
validation because OI data did not cover OOS22-23 and OOS24-Q1. The eventual
full-window frequency solution is the five-sleeve bundle:

`G7822 + G4692 + G4475 + G4673 + G4472`

That bundle reaches 31.80 de-duplicated direct entries/month.
