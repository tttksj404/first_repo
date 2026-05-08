# Full Frequency Validation - 2026-05-07

## Result

The high-cadence fix is not accepted.

G264402 cannot be used as the final frequency solution because local OI history
only covers 2025-03-25 14:00 UTC to 2026-04-04 13:00 UTC. That excludes the
OOS22-23 and OOS24-Q1 windows used for G7822 and G4692.

## Rechecked Components

| Component | Trades | Trades/Month | WR | PnL | Annual | Max DD | Liq | All Periods Positive |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| G7822 | 53 | 1.03 | 69.81% | 1015.58 | 237.62 | 92.88 | 0 | true |
| G4692 | 631 | 12.30 | 57.84% | 541.79 | 126.76 | 97.54 | 0 | true |
| G4474 | 962 | 18.75 | 54.26% | 411.05 | 96.18 | 166.19 | 0 | true |
| G4475 | 1042 | 20.31 | 53.17% | 222.31 | 52.01 | 113.88 | 0 | true |

## Bundle Attempts

| Bundle | Slot-Sum Trades/Month | Unique Direct Trades/Month | Added Unique Entries | Overlap | Verdict |
|---|---:|---:|---:|---:|---|
| G7822+G4692+G4474 | 32.08 | 25.33 | 616 | 346 | FAIL |
| G7822+G4692+G4475 | 33.63 | 26.64 | 683 | 359 | FAIL |

Slot-sum can exceed 30, but after timestamp/symbol/side de-duplication the
best full-price fallback only reaches 26.64 unique entries/month. That is still
below the 30/month target.

## Decision

Keep:

- G7822 as the quality G1165 replacement candidate.
- G4692 as the moderate-cadence validated breakout sleeve.

Do not treat G264402, G4474, or G4475 as solving the frequency problem.

Next research target: find a non-breakout, full-window validated sleeve that
adds at least 3.36 unique entries/month after overlap while staying positive in
all periods with zero liquidations.
