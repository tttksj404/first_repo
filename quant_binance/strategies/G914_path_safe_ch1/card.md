# G914 - Path-Safe CH1 Lottery

- **Status**: bt-only candidate
- **Parent**: G800/G400 CH1 lottery family
- **Change vs parent**: Adds path-based TP/SL risk control and lowers per-trade leverage from 20x-style close-to-close assumptions to 8x path-tested exposure.
- **TF / Symbol**: 1h, no-dead alt universe
- **Direction**: long only
- **Capital context**: 100 USD

## Thesis

Previous G400/G800 winners looked strong on close-to-close exits, but 20x intrabar path checks exposed excessive liquidation risk. G914 keeps the proven CH1 selective-entry edge, then adds hard TP/SL so winners can still breathe while liquidation risk is cut to zero in the tested periods.

## Entry Rules

- CH1/Mingogogo score >= 80.
- ATR percent 14h between 3% and 10%.
- Universe excludes known dead-weight symbols: WIF, LTC, BTC.
- Side is long only.
- Max concurrent positions: 5.

## Exit Rules

- Take profit: +12% price move.
- Stop loss: -7.5% price move.
- Time exit: 36 bars / 36 hours.
- Conservative path assumption: if TP and SL touch in the same bar, SL wins.

## Positioning

- Leverage: 8x.
- Margin size per trade: 30% of 100 USD equity.
- Round-trip cost assumption: 24 bps.

## Backtest Result

Source: `quant_binance/strategies/_scripts/g900_ensemble_discovery.py`

| Period | Trades | Win Rate | PnL USD | Annualized PnL | Liquidation Rate | Max Period DD |
|---|---:|---:|---:|---:|---:|---:|
| OOS22-23 | 16 | 56.25% | 104.85 | 52.43 | 0.00% | 48.41 |
| OOS24-Q1 | 30 | 70.00% | 424.10 | 339.47 | 0.00% | 92.88 |
| IS25-26 | 5 | 100.00% | 126.75 | 123.70 | 0.00% | 0.00 |
| Weighted | 51 | 68.63% | 655.70 | 153.42 | 0.00% | 92.88 |

## Ensemble Findings

- Strict structure breakout/breakdown generated no additional trades in the tested periods.
- Relaxed structure breakout/breakdown produced thousands of trades but was strongly cost-negative.
- Funding-fade and CH1+funding parallel sleeves increased trade count but dropped win rate below promotion thresholds.
- Current best result is not a forced multi-alpha blend; it is the CH1 edge with path-safe exits.

## Decision

G914 is the current best candidate for the user's small-capital, high-upside context because it preserves the only proven alpha shape while removing the hidden intrabar liquidation problem. It is not ready for live deployment until replay implementation and paper validation match this research harness.

## Next Candidate

G915 should test the same entry rule with adaptive exit variants:

- TP 10-14%.
- SL 6-8%.
- Hold 24-48h.
- Optional funding veto only, not funding as a separate trade engine.
