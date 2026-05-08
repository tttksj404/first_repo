# G1165 - Exit/Veto Optimized Path-Safe CH1

- **Status**: paper-live Oracle Cloud active (`g1165-emulator.service`, deployed 2026-05-06)
- **Parent**: G914
- **Change vs parent**: Optimize TP/SL, hold, ATR band, and leverage-size profile from the G915 search.
- **TF / Symbol**: 1h, no-dead alt universe
- **Direction**: long only
- **Capital context**: 100 USD

## Thesis

G900 showed that naive ensembles with structure/funding trades diluted the edge. G915 therefore searched the part that actually improved: path-safe exits around the CH1 long lottery core. G1165 is the top-ranked candidate after 864 exit/veto combinations.

## Entry Rules

- CH1/Mingogogo score >= 80.
- ATR percent 14h between 3% and 8%.
- Exclude dead-weight symbols: WIF, LTC, BTC.
- Side: long only.
- Max concurrent positions: 5.

## Exit Rules

- Take profit: +14% price move.
- Stop loss: -7.5% price move.
- Time exit: 36 bars / 36 hours.
- Conservative path assumption: if TP and SL touch in the same bar, SL wins.

## Positioning

- Leverage: 10x.
- Margin size per trade: 25% of 100 USD equity.
- Round-trip cost assumption: 24 bps.

## Backtest Result

Source: `quant_binance/strategies/_scripts/g915_exit_veto_results.json`

| Period | Trades | Win Rate | PnL USD | Annualized PnL | Liquidation Rate | Max Period DD |
|---|---:|---:|---:|---:|---:|---:|
| OOS22-23 | 16 | 56.25% | 144.22 | 72.11 | 0.00% | 50.42 |
| OOS24-Q1 | 30 | 70.00% | 530.54 | 424.67 | 0.00% | 96.75 |
| IS25-26 | 5 | 100.00% | 150.67 | 147.05 | 0.00% | 0.00 |
| Weighted | 51 | 68.63% | 825.43 | 193.13 | 0.00% | 96.75 |

## Search Result

- G915 search candidates tested: 864.
- PASS candidates: 192.
- Top cluster: `thr=80`, `hold=36`, `atr_min=3`, `lev=10`, `size=0.25`, `TP=14%`, `SL=7.5%`.
- Funding veto at `max_funding=0.0008` did not change top performance, so it is not required yet.
- `ATR max=8` and `ATR max=10` tied; choose `ATR max=8` as the cleaner risk filter.

## Decision

G1165 supersedes G914 as the current best research candidate and is now running as a paper-only Oracle service. It increases annualized PnL from G914's `$153.42` to `$193.13` while preserving zero tested liquidations. Keep it paper-only until live-like runtime behavior has enough observed fills/exits to validate the backtest assumptions.

## Paper Deployment

- Oracle VM: `g185-restored`.
- Public IP at deployment: `138.2.127.203`.
- Service: `g1165-emulator.service`.
- Runtime path: `~/g1165/runtime/state.json`.
- Deployment check: service active, `paper_only=true`, `heartbeats=1`, `last_error=null`, starting equity `$100.00`.
- Existing restored-VM strategy services were all inactive with zero closed trades and `cumulative_pnl_usd=0.0`, so no comparable negative-PnL active strategy needed to be disabled.

## Next Candidate

G1166/G1201 variants are useful sanity checks:

- G1166: same as G1165 plus funding veto `<= 0.0008`, currently no effect.
- G1201: same as G1165 but `ATR max=10`, currently tied.

The next genuinely new alpha experiment should use liquidation/OI as a primary signal rather than funding as a naive parallel sleeve.
