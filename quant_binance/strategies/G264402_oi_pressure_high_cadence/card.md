# G264402 - OI Pressure High-Cadence Candidate

- **Status**: blocked pending full-window OI validation
- **Discovery**: `scripts/fast_exhaustive_oi_pressure_grid.py`
- **Result source**: `quant_binance/strategies/_scripts/g4703_fast_oi_pressure_grid.json`
- **Full validation source**: `quant_binance/strategies/_scripts/g7824_full_frequency_validation_results.json`
- **Engine**: OI pressure continuation
- **Exchange / Market**: Bitget USDT futures
- **Capital context**: 100 USD

## Thesis

G7822 and G4692 together improve cadence versus G7822 alone, but 13 trades/month
is still too slow for fast paper validation. G264402 looked like a useful
high-cadence add-on inside the available OI-pressure grid.

Full validation changed the decision: the OI data available locally does not
cover the same OOS22-23 and OOS24-Q1 windows used for G7822/G4692, so this
cannot be accepted as the frequency fix yet.

## Entry Rules

- Symbols: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT.
- 12h absolute price move >= 4%.
- 12h open-interest increase >= 2%.
- Volume ratio >= 0.8.
- Direction follows the price move.
- Cooldown: 18 bars.

## Exit Rules

- Take profit: +4% price move.
- Stop loss: -5% price move.
- Time exit: 18 bars / 18 hours.

## Positioning

- Leverage: 10x.
- Margin size per trade: 35% of 100 USD equity.
- Max concurrent handling must be implemented in the dedicated OI runtime.

## OI-Only Validation Result

| Metric | Value |
|---|---:|
| Trades | 252 |
| Approx trades/month | 20.43 |
| Win rate | 57.14% |
| PnL USD | 344.01 |
| Annualized PnL | 334.83 |
| Max DD | 115.67 |
| Liquidations | 0 |
| All periods positive | true |

## Full-Window Coverage Check

| Symbol | OI Start UTC | OI End UTC | Rows |
|---|---:|---:|---:|
| BTCUSDT | 2025-03-25 14:00 | 2026-04-04 13:00 | 9000 |
| ETHUSDT | 2025-03-25 14:00 | 2026-04-04 13:00 | 9000 |
| SOLUSDT | 2025-03-25 14:00 | 2026-04-04 13:00 | 9000 |
| XRPUSDT | 2025-03-25 14:00 | 2026-04-04 13:00 | 9000 |

Missing coverage: OOS22-23 and OOS24-Q1.

## Decision

Do not use G264402 as the accepted high-cadence add-on until full-window OI
history is available and it passes the same period gates as the price-data
strategies.
