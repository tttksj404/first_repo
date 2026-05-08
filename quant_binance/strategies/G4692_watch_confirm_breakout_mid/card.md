# G4692 - Watch-Confirm Breakout Mid

- **Status**: best current non-CH1 paper candidate, runtime implementation pending
- **Parent**: G4006
- **Discovery**: G1309 watch-confirm breakout search
- **Exchange / Market**: Bitget USDT futures
- **TF / Symbol**: 1h, no_dead alt universe
- **Direction**: long only
- **Capital context**: 100 USD

## Thesis

G4692 keeps the proven strict breakout edge from G4006, but changes weak
breakouts from immediate entries into watch states. A weak breakout can only
become a trade if the next completed 1h candle confirms the strict breakout
threshold. This preserves the user's idea that weak signals should be read and
responded to, while avoiding the losing behavior found in immediate weak-entry
and fast-stop tests.

## Entry Rules

### Strict Immediate

- Close breaks the previous 24h high by at least 50 bps.
- 24h return is at least +10%.
- Current quote-volume ratio versus prior 48h median is at least 3.0.
- ATR percent 14h between 0% and 8%.

### Watch State

- Close breaks the previous 24h high by at least 30 bps.
- 24h return is at least +8%.
- Volume ratio is at least 2.5.
- ATR percent 14h between 0% and 8%.
- If the same bar already passes strict immediate rules, it is handled as a
  strict trade instead of a watch-confirm trade.

### Confirmation Entry

- Confirmation must happen on the next completed 1h candle.
- Confirmation close must break the previous 24h high by at least 50 bps.
- Confirmation 24h return must be at least +10%.
- Confirmation volume ratio must be at least 3.0.
- If the watch state fails below the prior 24h high before confirmation, no
  trade is opened.

## Exit Rules

### Strict Immediate Exit

- Take profit: +6% price move.
- Stop loss: -8% price move.
- Time exit: 36 bars / 36 hours.

### Watch-Confirm Exit

- Take profit: +5% price move.
- Stop loss: -6.5% price move.
- Time exit: 24 bars / 24 hours.

Both paths use conservative path assumption: if TP and SL touch in the same
bar, SL wins.

## Positioning

- Strict immediate: 8x leverage, 20% margin size.
- Watch-confirm: 7x leverage, 16% margin size.
- Max concurrent positions: 5.
- Round-trip cost assumption: 24 bps.

## Backtest Result

Source: `quant_binance/strategies/_scripts/g1309_watch_confirm_breakout_results.json`

| Period | Trades | Win Rate | PnL USD | Annualized PnL | Max DD |
|---|---:|---:|---:|---:|---:|
| OOS22-23 | 250 | 56.40% | 265.09 | 132.55 | 97.54 |
| OOS24-Q1 | 246 | 58.94% | 179.07 | 143.34 | 55.17 |
| IS25-26 | 135 | 58.52% | 97.63 | 95.28 | 90.65 |
| Weighted | 631 | 57.84% | 541.79 | 126.76 | 97.54 |

## Engine Attribution

| Engine | Trades | Win Rate | PnL USD |
|---|---:|---:|---:|
| Strict breakout | 502 | 58.57% | 495.42 |
| Watch-confirm | 129 | 55.04% | 46.37 |

## Slot Fit

- G1309 tested 121 watch-confirm variants.
- PASS candidates: 10.
- G4692 had the highest overall score and the best latest-period PnL among the
  PASS set.
- G1165 overlap Jaccard: 0.0000.
- G1995 overlap Jaccard: 0.0000.
- Walk-forward train-selection leader was G4676, but G4692 had stronger latest
  period and lower drawdown than the G4006-like exit leader.

## Decision

Promote G4692 as the current best non-CH1 paper candidate, replacing G4006 as
the preferred breakout probe. Do not deploy it through the old immediate-only
breakout emulator; runtime must support persisted watch states and next-bar
confirmation before Oracle paper testing.

## Frequency Bundle Use

G4692 is also the selected breakout sleeve for the G7822 frequency solution
bundles:

- Moderate-frequency bundle: `../G7822_G4692_frequency_solution/card.md`.
- Revised high-cadence bundle: `../G7822_G4692_G264402_high_cadence_bundle/card.md`.

In that bundle, G7822 supplies the higher-quality CH1 replacement/shadow role,
while G4692 supplies paper-observation cadence. Direct timestamp/symbol/side
overlap between G7822 and G4692 was 0 in the validation windows.
