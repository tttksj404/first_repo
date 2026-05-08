# High-WR Repair Attempts - 2026-05-07

## Goal

Find a way to keep the frequency solution while also repairing WR/DD quality.

Desired shape:

- At least 30 unique entries/month at bundle level.
- Added sleeve WR high enough to keep aggregate WR near G1165/G7822 levels.
- Positive PnL in every full validation window.
- Zero liquidations.
- DD not worse than G1165/G7822 after practical scaling.

## Attempt 1: New Price Alpha Families

Script: `quant_binance/strategies/_scripts/g7827_high_wr_alpha_search.py`

Families tested:

- Trend pullback continuation.
- Climax reclaim / reversal.

Focused specs tested: 1,152.

Result:

- Strict high-WR pass count: 0.
- Dream pass count: 0.
- Best reported candidate had 10.76 trades/month and WR 59.78%, but PnL was negative and not all-period-positive.

## Attempt 2: Symbol/Hour Filters

Script: `quant_binance/strategies/_scripts/g7828_filtered_high_wr_sleeve_search.py`

Filtered existing high-cadence sleeves by:

- Top symbols.
- Top hours.
- Top symbol/hour cells.

Result:

- WR 65% and >=8 trades/month pass: 1.
- WR 65% and >=12 trades/month pass: 0.
- WR 69% and >=8 trades/month pass: 0.

Best usable filtered sleeve:

| Candidate | Filter | Trades/Month | WR | PnL | Max DD | All Periods Positive |
|---|---|---:|---:|---:|---:|---|
| G4456 | top hours | 8.05 | 65.13% | 323.36 | 29.07 | true |

This improves WR versus raw cadence sleeves, but it is still below G1165/G7822
WR and not frequent enough to solve the bundle alone.

## Attempt 3: High-WR Pocket Bundling

Script: `quant_binance/strategies/_scripts/g7829_filtered_pocket_bundle_search.py`

Combined only pockets with standalone WR >= 69%.

Result:

- Pass count: 0.
- Even after combining up to 20 high-WR pockets, G7822-included bundle frequency
  topped out around 5.48 trades/month in the beam result.

The high-WR pockets exist, but they are too sparse.

## Attempt 4: Exit Profile Tuning

Script: `quant_binance/strategies/_scripts/g7830_exit_profile_high_wr_tuning.py`

Base signals:

- G4452
- G4456
- G4662
- G4677

Tuned short TP/SL exits across 3h, 6h, 9h, and 12h holds.

Result:

- WR can be pushed to 75.03%.
- The high-WR versions are negative PnL and not all-period-positive.
- WR 65% + >=8 trades/month + positive all-period result count: 0.

## Current Conclusion

The frequency problem is solvable with the current candidate pool.

The "frequency plus all other metrics improved" problem is not solved by:

- stacking breakout-family sleeves,
- filtering symbol/hour pockets,
- changing TP/SL exits, or
- the tested trend-pullback / climax-reclaim alpha families.

The blocker is not DD. DD can be reduced through size scaling. The blocker is
win rate: the only full-window sleeves with enough cadence have WR around
58-65%, while G1165/G7822 are near 69%.

## Next Viable Path

Stop stacking price-breakout variants. The next research path needs a genuinely
different data source or alpha source, for example:

- full-window OI/funding history,
- liquidation/forced-flow data,
- order-book imbalance snapshots,
- cross-asset lead/lag with 5m data,
- or a walk-forward regime classifier that filters breakout entries without
collapsing cadence.
