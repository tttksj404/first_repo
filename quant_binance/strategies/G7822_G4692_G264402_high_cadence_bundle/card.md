# G7822 + G4692 + G264402 - Rejected High-Cadence Paper Bundle

- **Status**: rejected / blocked after full-window validation
- **Components**: G7822, G4692, G264402
- **Target cadence**: at least 30 paper entries/month
- **Interpretation**: multi-sleeve paper observation set, not one shared-equity portfolio simulation
- **Full validation source**: `quant_binance/strategies/_scripts/g7824_full_frequency_validation_results.json`

## Why This Exists

The earlier G7822+G4692 bundle produced 13.33 trades/month. That is better than
G7822 alone, but it is not enough for quick paper validation.

This revised bundle tried to add G264402, the highest-cadence retained
OI-pressure candidate. Full validation rejected that conclusion because the
local OI history only covers 2025-03-25 to 2026-04-04, while G7822/G4692 are
judged across OOS22-23, OOS24-Q1, and IS25-26.

## Component Roles

| Component | Role | Approx Entries/Month |
|---|---|---:|
| G7822 | Higher-quality CH1 replacement/shadow for G1165 | 0.41 recent / 1.03 full |
| G4692 | Non-CH1 breakout cadence sleeve | 11.38 recent / 12.30 full |
| G264402 | OI-pressure high-cadence sleeve | 20.43 OI-only validation |

## Cadence Check

The earlier cadence check mixed full-window price validation with short-window
OI validation:

| Component | Entries/Month |
|---|---:|
| G7822 recent IS25-26 | 0.41 |
| G4692 recent IS25-26 | 11.38 |
| G264402 OI validation | 20.43 |
| Combined | 32.22 |

Target: >= 30 entries/month.

Earlier verdict: PASS.

Corrected verdict: FAIL / blocked.

## Full-Window Blocker

Available OI coverage:

| Symbol | OI Start UTC | OI End UTC | Rows |
|---|---:|---:|---:|
| BTCUSDT | 2025-03-25 14:00 | 2026-04-04 13:00 | 9000 |
| ETHUSDT | 2025-03-25 14:00 | 2026-04-04 13:00 | 9000 |
| SOLUSDT | 2025-03-25 14:00 | 2026-04-04 13:00 | 9000 |
| XRPUSDT | 2025-03-25 14:00 | 2026-04-04 13:00 | 9000 |

This does not cover OOS22-23 or OOS24-Q1, so G264402 cannot be accepted as the
frequency fix under the same evidence standard.

## Full-Price Fallback Check

The best full-window price-only add-ons tested were G4474 and G4475. They make
the raw slot-sum cadence look high enough, but much of that comes from overlap
with G4692's breakout family.

| Bundle | Slot-Sum Trades/Month | Unique Direct Trades/Month | Overlap vs G7822+G4692 | Verdict |
|---|---:|---:|---:|---|
| G7822+G4692+G4474 | 32.08 | 25.33 | 346 | FAIL |
| G7822+G4692+G4475 | 33.63 | 26.64 | 359 | FAIL |

## Decision

Do not deploy this bundle as the frequency solution.

Current honest state:

- G7822 remains the G1165 quality replacement candidate.
- G4692 remains the validated moderate-cadence breakout sleeve.
- G264402 remains an OI idea only, pending full-window OI history.
- The frequency problem is solved by the later full-window price-data bundle
  `../G7822_G4692_G4475_G4673_G4472_frequency_solved_bundle/card.md`, not by
  this OI bundle.
