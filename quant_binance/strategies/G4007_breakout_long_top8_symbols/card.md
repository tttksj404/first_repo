# G4007 - Breakout Long Top8 Symbols

- **Status**: paper-probe candidate, not live-approved
- **Parent**: G4006
- **Discovery**: G1305 walk-forward filter validation
- **Exchange / Market**: Bitget USDT futures
- **TF / Symbol**: 1h, walk-forward top-8 symbol filter
- **Direction**: long only
- **Capital context**: 100 USD

## Thesis

G4007 keeps the same non-CH1 breakout engine as G4006 but narrows the runtime
symbols to the latest walk-forward top-8 set. It trades lower coverage and lower
expected annual PnL for much cleaner drawdown and higher win rate.

## Entry Rules

- Close breaks the previous 24h high by at least 50 bps.
- 24h return is at least +10%.
- Current quote-volume ratio versus prior 48h median is at least 3.0.
- ATR percent 14h between 0% and 8%.
- Latest walk-forward symbol set: AVAX, DOT, ETH, MATIC, NEAR, SOL, SUI, XRP.
- Side: long only.
- Max concurrent positions: 5.

## Exit Rules

- Take profit: +6% price move.
- Stop loss: -8% price move.
- Time exit: 36 bars / 36 hours.
- Conservative path assumption: if TP and SL touch in the same bar, SL wins.

## Positioning

- Leverage: 8x.
- Margin size per trade: 20% of 100 USD equity.
- Round-trip cost assumption: 24 bps.

## Walk-Forward Result

Source: `quant_binance/strategies/_scripts/g1305_breakout_walkforward_filter_results.json`

| OOS Fold | Selected Symbols | Trades | Win Rate | PnL USD | Annualized PnL | Max DD |
|---|---|---:|---:|---:|---:|---:|
| Train OOS22, test OOS24 | ADA, AVAX, DOGE, DOT, MATIC, NEAR, SOL, XRP | 94 | 63.83% | 187.95 | 150.44 | 33.61 |
| Train OOS22+OOS24, test IS25 | AVAX, DOT, ETH, MATIC, NEAR, SOL, SUI, XRP | 39 | 58.97% | 63.41 | 61.89 | 36.72 |
| Aggregate OOS | walk-forward top8 | 133 | 62.41% | 251.36 | 110.54 | 36.72 |

## Slot Fit

- G1165 overlap Jaccard: 0.0000.
- G1995 overlap Jaccard: 0.0000.
- Compared with G4006 raw, aggregate OOS DD improves from 96.29 USD to 36.72
  USD, while annualized OOS PnL decreases from 125.12 USD to 110.54 USD.

## Decision

Use G4007 as the lower-drawdown companion probe to G4006, not as an automatic
replacement unless Oracle paper fills confirm that the reduced symbol set still
generates enough trades. Runtime should skip any exchange-unavailable symbol and
log the fetch error rather than silently changing the validation thesis.
