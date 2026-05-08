# Strict Quality Check - 2026-05-07

## Question

Can we keep the solved frequency target and also improve every G1165/G7822
quality metric?

Strict target:

- Unique direct entries/month >= 30.
- WR >= G1165 68.63%.
- WR >= G7822 69.81%.
- Max component period DD <= G1165 96.75.
- Max component period DD <= G7822 92.88.
- PnL and annualized PnL above G7822.
- Zero liquidations.
- All periods positive.

Script: `quant_binance/strategies/_scripts/g7826_quality_frequency_strict_search.py`

## Result

Strict pass count: 0.

No full-window bundle in the current candidate surface satisfied frequency,
G1165/G7822 win-rate, and G1165/G7822 drawdown together.

## Best Frequency Bundles By Quality

| Start | Components | Unique TPM | WR | Annual | PnL | Max DD | Failed Quality Gates |
|---|---|---:|---:|---:|---:|---:|---|
| G7822 only | G7822+G4472+G4474+G4604+G4677 | 30.24 | 56.80% | 574.06 | 2453.50 | 166.19 | WR, DD |
| G7822+G4692 | G7822+G4692+G4472+G4474+G4604+G4677 | 30.28 | 56.99% | 700.82 | 2995.29 | 166.19 | WR, DD |

## High-Cadence WR Ceiling

Among full-window candidates with at least 10 trades/month, the best observed
WRs were:

| Candidate | Family | Trades/Month | WR | Max DD |
|---|---|---:|---:|---:|
| G4452 | controlled_loose_breakout | 13.25 | 59.12% | 47.21 |
| G4456 | controlled_loose_breakout | 13.76 | 58.36% | 45.76 |
| G4677 | watch_confirm | 12.45 | 58.22% | 92.79 |
| G4662 | watch_confirm | 12.57 | 58.14% | 90.67 |
| G4464 | controlled_loose_breakout | 14.75 | 57.99% | 80.83 |

This is the core conflict: the sleeves that provide enough frequency do not
have a ~69% win rate. Adding enough of them to reach 30 unique entries/month
pulls aggregate WR down.

## What Can Be Improved Now

DD can be repaired with size scaling because the frequency count does not
depend on notional size. For example, the best G7822+G4692 frequency-quality
bundle has max component DD 166.19. Scaling the added breakout sleeves to about
55% of their tested size would bring their component DD below G7822's 92.88
while keeping the same paper entry count and still adding positive expected PnL.

WR cannot be repaired by sizing. It requires a new high-frequency alpha family
whose own WR is near 69%, or a filter that removes low-WR breakout entries
without dropping unique cadence below 30/month.

## Decision

The current frequency-solved bundle remains useful for fast paper observation,
but it does not satisfy "all other metrics improved."

Next required research target: discover or build a new full-window sleeve with
at least 10-15 trades/month and WR materially above 65%, or a regime/symbol/hour
filter that lifts the selected breakout sleeves' WR while keeping the bundle
above 30 unique entries/month.
