# Expanded Data Alpha Attempts - 2026-05-07

## Why This Was Run

The prior conclusion was too narrow: it mostly covered 1h price/breakout-family
methods. This pass checked whether additional local data sources can repair the
remaining WR problem.

## Added Sources Checked

| Source | Coverage | Result |
|---|---|---|
| 5m klines | DOGE/ETH/PEPE/SOL, 2024-01-01 to 2026-04-27 | Existing G111 CH1-style 5m scalps failed; wide lead/lag search needs chunking |
| Funding | 35 symbols, 2024-01-01 to 2026-04-27 | G090-long is promising after hour filtering |
| Liquidation proxy | 30d only | Not enough for full historical proof |
| OI | BTC/ETH/SOL/XRP, 2025-03-25 to 2026-04-04 | Not enough for full historical proof |

## Useful Find

Script: `quant_binance/strategies/_scripts/g7833_g090_filter_high_wr_search.py`

Best G090 hour filter:

| Metric | Value |
|---|---:|
| Trades | 225 |
| Trades/month | 8.08 |
| WR | 95.56% |
| PnL units | 1509.66 |
| Max DD units | 7.26 |
| All years positive | true |
| All years WR >= 65% | true |

Selected hours:

`[1, 3, 0, 2, 21, 20, 4, 23, 6, 19]`

Year split:

| Year | Trades | WR | PnL units |
|---|---:|---:|---:|
| 2024 | 69 | 94.20% | 346.83 |
| 2025 | 126 | 97.62% | 1063.11 |
| 2026 | 30 | 90.00% | 99.72 |

This is the first locally found sleeve that is both meaningful cadence and very
high WR. It does not solve the full 30/month target alone, but it is the right
kind of sleeve to add.

## Existing 5m Check

Script: `quant_binance/strategies/_scripts/g111_5m_user_pattern.py`

The broad 5m CH1-style pattern was high-frequency but negative:

- 5m hold: WR 35.8-41.1% by year, negative annualized result.
- 10m hold: WR 42.3-46.1% by year, negative annualized result.
- 30m hold: WR 46.7-50.9% by year, negative annualized result.
- Score >= 80: too sparse and unstable.

## Incomplete Wide Runs

The following scripts were created, but the initial broad surfaces exceeded the
interactive timeout and must be run in smaller chunks before they can be called
exhaustive:

- `g7831_5m_leadlag_high_wr_search.py`
- `g7832_funding_extreme_high_wr_search.py`
- `g7834_g090_variant_search.py`

This means the honest state is not "all methods exhausted." The honest state is:

- 1h price/breakout-family methods were explored deeply and did not solve
  all-metric improvement.
- A promising high-WR funding/CH1 hour-filtered sleeve was found.
- Wide 5m lead/lag and broader G090 variant searches still need chunked
  execution.

## Follow-up Chunked Exploration

The timeout-limited scripts were converted to chunk/resume style execution:

- `g7831_5m_leadlag_high_wr_search.py`
- `g7832_funding_extreme_high_wr_search.py`
- `g7834_g090_variant_search.py`

Each now supports `--chunk-index`, `--chunk-count`, `--top-limit`,
`--max-seconds`, and merge behavior where applicable. This preserves the broad
surface while making the search runnable as many small resumable jobs.

### Funding Extreme Partial Surface

Script: `quant_binance/strategies/_scripts/g7832_funding_extreme_high_wr_search.py`

Partial coverage completed:

- Chunks merged: 16 / 512
- Specs evaluated in merged partial: 2,560
- Strict pass: 22
- Dream pass: 4
- Result file: `g7832_funding_extreme_high_wr_search_results.json`

Best balanced funding candidates from the partial surface:

| Candidate | Mode | Trades/month | WR | PnL units | Max DD | Period counts | Notes |
|---|---|---:|---:|---:|---:|---|---|
| G805740 | negative squeeze long | 21.57 | 71.99% | 41.72 | 23.46 | 229 / 360 | Best cadence/balance; both periods positive; zero liquidations |
| G827758 | positive follow long, 08-15 UTC | 11.76 | 73.52% | 21.11 | 21.22 | 245 / 76 | Cleaner period balance than sparse high-WR fade variants |
| G789356 | positive fade short | 16.41 | 79.91% | 30.07 | 23.49 | 443 / 5 | Strong headline, but 2025-26 sample is too thin |

The practical takeaway is that funding did produce additional high-WR/high-cadence
sleeves. The sparse positive-fade variants should be treated as watchlist only
until more chunks or a period-balanced variant confirms them.

### 5m Lead/Lag First Chunks

Script: `quant_binance/strategies/_scripts/g7831_5m_leadlag_high_wr_search.py`

Initial very small chunks were run with chunk count 4,096. The best early rows
were high-cadence but still cost-negative:

- Example: ETH -> PEPE follow, 53.62 trades/month, WR 63.32%, PnL negative.

This family is not rejected; only the first small completed chunks failed.

### G090 Variant First Chunks

Script: `quant_binance/strategies/_scripts/g7834_g090_variant_search.py`

Initial chunked rows mostly showed the expected failure mode: relaxing G090 too
far raises cadence but collapses WR and PnL. Ranking was adjusted so future
chunks prioritize all-year positivity and WR ahead of raw frequency.

## Combined Sleeve Check

Script: `quant_binance/strategies/_scripts/g7835_high_wr_sleeve_combo_validation.py`

The new combination check applies a conservative portfolio constraint:

- de-duplicate same `timestamp/symbol/side`
- skip same-symbol overlapping holds
- max concurrent positions: 5

This revealed an important correction: the raw G090 hour-filter had 225 signals
and 8.08/month, but under this conservative same-symbol overlap constraint it
takes 53 trades, or 1.90/month. The raw signal is still high quality, but the
portfolio-taken count is smaller.

Best combined result so far:

| Combo | Trades/month | WR | PnL units | Max DD | Liquidations | All years positive |
|---|---:|---:|---:|---:|---:|---|
| G090 + G805740 + G827758 | 32.05 | 71.44% | 162.53 | 22.10 | 0 | true |

Year split:

| Year | Trades | WR | PnL units |
|---|---:|---:|---:|
| 2024 | 303 | 72.94% | 62.86 |
| 2025 | 472 | 69.92% | 75.36 |
| 2026 | 118 | 73.73% | 24.32 |

Family attribution:

| Family | Trades | WR | PnL units |
|---|---:|---:|---:|
| G805740 balanced negative squeeze | 527 | 69.26% | 6.05 |
| G827758 balanced positive follow midday | 321 | 73.52% | 21.11 |
| G090 hour filter | 45 | 82.22% | 135.37 |

This does not mean the full broad search is complete. It does mean the state has
improved from "one high-quality but sparse sleeve" to "one conservative
portfolio-level combo that reaches the 30/month cadence target with 70%+ WR,
all-year positivity, and zero tested liquidations."

## Oracle Paper Deployment

Script: `quant_binance/strategies/_scripts/deploy_g7835_to_oracle.py`

G7835 was packaged as a Bitget futures paper-only combo emulator:

- `g090_hour_filter`
- `G805740_balanced_negative_squeeze`
- `G827758_balanced_positive_follow_midday`

Deployment notes:

- Oracle SSH was initially stuck on port 443 during banner exchange while OCI
  showed the VM as running.
- OCI `SOFTRESET` was used to recover the VM; after the lifecycle returned to
  `RUNNING`, SSH access recovered.
- No active zero-entry service was disabled because the no-entry candidates
  (`G1165`, `G129183`) were already inactive. The only active service found was
  `G4692`, with open/closed entries, so it was preserved.
- `G7835` was deployed as `g7835-emulator.service`.

Post-deploy verification:

| Item | Result |
|---|---|
| Service | active |
| Heartbeats | 2 |
| Symbols checked in latest cycle | 19 |
| Fetch errors | 0 |
| Current candidate signals | 0 |
| Current open positions | 0 |

An initial runtime issue was fixed during deployment: Bitget
`history-candles` rejected `limit=220` with HTTP 400, so the runtime was patched
to use the existing Bitget-compatible `limit=200`.

## Next Execution Step

Continue chunk execution, prioritizing:

1. More `g7832` chunks because the partial surface is already producing
   balanced candidates.
2. Targeted `g7834` chunks around higher score thresholds and the known good
   hour filter, now that ranking no longer over-promotes raw frequency.
3. Additional `g7831` chunks only after adding faster precomputed event masks or
   narrowing to leader/follower pairs that survive early cost checks.
