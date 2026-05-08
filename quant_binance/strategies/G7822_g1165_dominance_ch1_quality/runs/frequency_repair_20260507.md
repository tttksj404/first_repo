# G7822 Frequency Repair Check - 2026-05-07

## Question

G7822 improves on G1165, but it does not solve the paper-observation problem:
it remains a sparse CH1 strategy with 53 trades across the validation windows.

The question tested here was whether the entry-frequency problem can be solved
inside the same CH1/G7822 family without breaking the risk/return profile.

## Method

Script: `quant_binance/strategies/_scripts/g7823_frequency_repair_search.py`

Result: `quant_binance/strategies/_scripts/g7823_frequency_repair_results.json`

Search surface:
- CH1 thresholds: 76, 78, 80.
- ATR bands: 0-8, 0-10, 2-8, 2-10, 3-8.
- Holds: 24h, 36h, 48h.
- Exit pairs around the G1165/G7822 family.
- Leverage/size profiles: 8x/25%, 8x/30%, 10x/20%, 10x/25%.
- Max concurrent: 5 or 8.
- Universe modes: no-dead, no-dead-no-weak, quality-rotators, liquid-alts.

Balanced pass gate:
- At least 100 trades.
- Win rate at least 60%.
- Total PnL above G7822.
- Annualized PnL above G1165.
- Zero liquidations.
- All periods positive.
- Max period drawdown no more than 2x G7822.

## Findings

No CH1/G7822-family candidate passed the balanced frequency gate.

The strongest all-period-positive, liquidation-free CH1 variants reached only
81 trades, about 1.58 trades/month. The best row was:

| Candidate | Trades | Trades/Month | Win Rate | PnL USD | Annualized PnL | Max DD |
|---|---:|---:|---:|---:|---:|---:|
| G11325-equivalent search row | 81 | 1.58 | 71.60% | 1272.12 | 297.64 | 162.77 |

This improves frequency by about 53% versus G7822, but it is still not a fast
paper-observation strategy, and drawdown rises materially.

The 100+ trade CH1 candidates failed period consistency. The best 100+ trade,
liquidation-free row by score had:

| Candidate | Trades | Trades/Month | Win Rate | PnL USD | Annualized PnL | Max DD | Weakness |
|---|---:|---:|---:|---:|---:|---:|---|
| G10989-equivalent search row | 102 | 1.99 | 50.98% | 598.82 | 140.11 | 207.41 | At least one period negative |

The highest-frequency CH1 rows were worse:

| Candidate | Trades | Trades/Month | Win Rate | PnL USD | Annualized PnL | Max DD |
|---|---:|---:|---:|---:|---:|---:|
| G7861-equivalent search row | 486 | 9.47 | 46.91% | -507.60 | -118.77 | 400.14 |

## Conclusion

The entry-frequency issue should not be solved by relaxing G7822. In this
search, loosening CH1 enough to create frequent paper fills destroys expectancy
or period consistency.

Recommended structure:
- Keep G7822 as the higher-quality CH1 replacement/shadow candidate.
- Use a separate non-CH1 high-frequency sleeve for fast paper observation.
- The current best fit is G4692 watch-confirm breakout, because it has zero
  overlap with G1165/G1995 and produces 631 trades across the same validation
  windows.

G4692 reference metrics:

| Period | Trades | Approx Trades/Month | Win Rate | PnL USD | Annualized PnL | Max DD |
|---|---:|---:|---:|---:|---:|---:|
| OOS22-23 | 250 | 10.4 | 56.40% | 265.09 | 132.55 | 97.54 |
| OOS24-Q1 | 246 | 16.4 | 58.94% | 179.07 | 143.34 | 55.17 |
| IS25-26 | 135 | 11.1 | 58.52% | 97.63 | 95.28 | 90.65 |
| Weighted | 631 | ~12.3 | 57.84% | 541.79 | 126.76 | 97.54 |

Practical decision:

G7822 can replace or shadow G1165 for quality, but the frequency problem is
solved by pairing it with G4692, not by mutating G7822.
