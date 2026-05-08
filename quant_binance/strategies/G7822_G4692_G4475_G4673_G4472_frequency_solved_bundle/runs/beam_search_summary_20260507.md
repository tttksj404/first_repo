# Beam Search Frequency Summary - 2026-05-07

## Goal

Solve the G7822 paper-frequency problem under full-window validation.

Acceptance gate:

- Unique direct entries/month >= 30.
- Candidate components must be all-period-positive.
- Candidate components must be liquidation-free.
- Bundle slot-sum WR must stay >= 54%.
- Count timestamp/symbol/side duplicates only once.

## Search

Script: `quant_binance/strategies/_scripts/g7825_frequency_bundle_beam_search.py`

Inputs:

- G7822 and G4692 fixed as the base.
- Pre-gated G1307 controlled-loose breakout candidates.
- Pre-gated G1309 watch-confirm breakout candidates.
- Pre-gated G1304 multi-family non-CH1 candidates.

Retained candidates: 62 from 82 pre-gated rows.

## Best Pass

| Component | Family |
|---|---|
| G7822 | ch1_quality |
| G4692 | watch_confirm |
| G4475 | controlled_loose_breakout |
| G4673 | watch_confirm |
| G4472 | controlled_loose_breakout |

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

## Decision

Frequency problem is solved for paper observation by adding multiple
full-window breakout-family sleeves, not by relaxing G7822 itself and not by
using the short-window OI candidate.

This is not live-ready sizing. Before live use, build a runtime allocator that
deduplicates same-symbol entries and caps total breakout-family exposure.
