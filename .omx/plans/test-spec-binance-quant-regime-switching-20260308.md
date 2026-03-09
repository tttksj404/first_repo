# Test Spec: Binance Quant Regime-Switching Trading System

## Objective

Define verification gates for the regime-switching trading system before any live capital is exposed.

## Verification Layers

### 1. Deterministic Unit Tests

Goal: prove the scoring and gating logic is deterministic and threshold-safe.

Required coverage:

- normalized feature transforms clamp to valid bounds
- score formula matches documented weights
- futures gating blocks execution if any hard condition fails
- spot gating never opens a short
- low-confidence inputs route to cash
- identical input snapshots produce identical decisions
- risk sizing never exceeds configured exposure caps

Acceptance:

- 100 percent pass on deterministic tests
- no flaky tests across `10` immediate reruns of the deterministic suite
- allowed flaky failure count: `0`

### 2. Historical Replay Tests

Goal: verify feature generation and signal timing using recorded market data.

Required coverage:

- replay over normal trend periods
- replay over volatility shock periods
- replay over chop / low-conviction periods
- replay over funding and open-interest extremes

Acceptance:

- forward-only recomputation from raw fixtures matches batch feature output for `100%` of checked timestamps
- timestamp-causality assertions confirm every feature for decision time `t` depends only on events with timestamp `<= t`
- replay decisions match expected regime transitions on curated fixtures at `>= 95%` segment accuracy

### 3. Backtest Validation

Goal: test whether the strategy remains positive after realistic costs.

Assumptions:

- fees must be explicitly modeled
- slippage must be modeled by symbol and notional bucket
- futures funding must be included

Required reports:

- gross return
- net return after costs
- Sharpe ratio
- max drawdown
- turnover
- win rate
- average win / loss
- exposure by mode
- fee drag
- funding drag

Minimum deployment gate for MVP:

- positive net expectancy after costs, defined as mean net realized PnL per closed trade in bps `> 0`
- Sharpe ratio greater than `1.0`
- max drawdown not worse than `12%` in research window
- no single symbol responsible for more than `50%` of PnL

Research window:

- from `2022-01-01` through `2026-02-28`

### Required Cost Model

- spot taker and maker fees from configured account tier
- futures taker and maker fees from configured account tier
- realized funding from historical funding series
- slippage model by symbol and notional bucket

### 4. Walk-Forward Validation

Goal: avoid tuning purely to one historical window.

Method:

- rolling train / validate windows
- fixed config on each out-of-sample block
- compare in-sample vs out-of-sample degradation

Window specification:

- train window: `180` calendar days
- out-of-sample window: `60` calendar days
- rebalance cadence for evaluation: every `30` days

Acceptance:

- out-of-sample Sharpe is at least `65%` of in-sample Sharpe
- out-of-sample max drawdown is no worse than `125%` of in-sample max drawdown
- parameter updates are limited to at most `1` tagged strategy-config release per calendar quarter

### 5. Paper Trading

Goal: test live data, order handling, and decision behavior with zero capital risk.

Required runtime:

- minimum `30` calendar days

Required checks:

- decision logs are complete
- orders reconcile with simulated fills
- stale data alarms trigger correctly
- regime switching frequency stays within configured limits
- reject rate and retry rate stay within thresholds

Acceptance:

- no critical reconciliation failures
- no uncontrolled order loops
- `100%` of decision records contain all required non-null fields except explicitly optional fields
- average mode switches stay at or below `6` per symbol per day
- no more than `2` direction flips for the same symbol within `60` minutes
- order reject rate stays below `1.0%`
- retry rate stays below `2.0%`
- fill reconciliation mismatch rate stays below `0.1%`
- stale-data alarm fires within `stale_data_alarm_sla_seconds` and clears within `5` seconds after recovery

Definitions:

- `critical reconciliation failure` = any mismatch that leaves position size, side, or open-order count incorrect after one recovery cycle
- `uncontrolled order loop` = more than `3` orders for the same symbol and side generated within `60` seconds without a new decision hash

### 6. Shadow Live Validation

Goal: compare paper decisions to what live execution would have done under current market conditions.

Required checks:

- slippage estimate vs observed quote movement
- entry and exit timing drift
- signal decay between decision and order creation

Acceptance:

- average realized slippage error stays within `20%` of the modeled value and never exceeds `5 bps` absolute error on average
- `100%` of paper/live decision divergences include a machine-readable divergence code and linked snapshot IDs
- median entry timing drift stays at or below `2` seconds and p95 entry timing drift stays at or below `5` seconds
- median exit timing drift stays at or below `2` seconds and p95 exit timing drift stays at or below `5` seconds
- signal decay between decision and order creation stays within `5` predictability-score points at p95

## Regime-Specific Test Cases

## Threshold Boundary Fixtures

These fixtures are mandatory because mode selection is threshold-driven.

Required exact decision cases:

- `predictability_score = 54.99` -> `cash`
- `predictability_score = 55.00`, positive trend, all spot gates pass -> `spot`
- `predictability_score = 74.99`, all futures gates pass otherwise -> `spot`
- `predictability_score = 75.00`, all futures gates pass -> `futures`
- `gross_expected_edge_bps = 1.49 * estimated_round_trip_cost_bps` -> reject
- `gross_expected_edge_bps = 1.50 * estimated_round_trip_cost_bps` -> eligible
- `volatility_penalty = 0.45` with futures candidate -> allowed
- `volatility_penalty = 0.4501` with futures candidate -> reject
- `overheat_penalty = 0.35` with futures candidate -> allowed
- `overheat_penalty = 0.3501` with futures candidate -> reject

### Futures-Eligible Long

Input vector:

- `trend_direction = +1`
- `trend_strength = 0.82`
- `volume_confirmation = 0.74`
- `liquidity_score = 0.86`
- `regime_alignment = 1.0`
- `volatility_penalty = 0.28`
- `overheat_penalty = 0.14`
- `gross_expected_edge_bps = 24`
- `estimated_round_trip_cost_bps = 10`

Expected:

- `mode = futures`
- `side = long`

### Futures-Eligible Short

Input vector:

- `trend_direction = -1`
- `trend_strength = 0.84`
- `volume_confirmation = 0.71`
- `liquidity_score = 0.88`
- `regime_alignment = 1.0`
- `volatility_penalty = 0.31`
- `overheat_penalty = 0.10`
- `gross_expected_edge_bps = 26`
- `estimated_round_trip_cost_bps = 11`

Expected:

- `mode = futures`
- `side = short`

### Spot-Eligible Long

Input vector:

- `trend_direction = +1`
- `trend_strength = 0.61`
- `volume_confirmation = 0.58`
- `liquidity_score = 0.68`
- `regime_alignment = 0.5`
- `volatility_penalty = 0.41`
- `overheat_penalty = 0.62`
- `gross_expected_edge_bps = 18`
- `estimated_round_trip_cost_bps = 10`

Expected:

- `mode = spot`
- `side = long`

### Cash State

Input vector:

- `trend_direction = 0`
- `trend_strength = 0.41`
- `volume_confirmation = 0.47`
- `liquidity_score = 0.52`
- `regime_alignment = 0.0`
- `volatility_penalty = 0.72`
- `overheat_penalty = 0.44`
- `gross_expected_edge_bps = 11`
- `estimated_round_trip_cost_bps = 10`

Expected:

- `mode = cash`
- no order submitted

### Overheat Downgrade

Input vector:

- `trend_direction = +1`
- `trend_strength = 0.81`
- `volume_confirmation = 0.72`
- `liquidity_score = 0.76`
- `regime_alignment = 1.0`
- `volatility_penalty = 0.34`
- `overheat_penalty = 0.67`
- `gross_expected_edge_bps = 22`
- `estimated_round_trip_cost_bps = 10`

Expected:

- not eligible for futures
- `mode = spot`
- `side = long`

## Operational Resilience Tests

- websocket disconnect and reconnect
- partial order fill handling
- duplicate event handling
- late user-data events
- REST fallback after websocket gap
- stale order status recovery
- kill-switch on repeated broker errors

Acceptance:

- no orphaned positions
- no duplicate orders from event replay
- websocket reconnect completes within `30` seconds
- order-book resync completes within `5` seconds after reconnect
- user-data reconciliation catches `100%` of injected dropped events in resilience tests
- every resilience run emits a recovery report artifact with event timeline and final position check

## Required Replay Fixtures

The replay suite must include at minimum:

- `BTCUSDT`, `2024-02-20` to `2024-03-05`: strong trend regime
- `ETHUSDT`, `2024-08-01` to `2024-08-15`: choppy mixed regime
- `SOLUSDT`, `2025-01-15` to `2025-01-31`: high-momentum high-volatility regime
- `BTCUSDT`, `2025-12-01` to `2025-12-10`: funding and open-interest stress regime

Each fixture must document expected mode-transition sequences before the replay test is approved.

Seed oracle segments for approval baseline:

- `BTCUSDT 2024-02-20..2024-03-05`
  - `2024-02-20T00:00Z` to `2024-02-22T23:59Z` -> `spot`, `long`
  - `2024-02-23T00:00Z` to `2024-02-29T23:59Z` -> `futures`, `long`
  - `2024-03-01T00:00Z` to `2024-03-05T23:59Z` -> `spot`, `long`
- `ETHUSDT 2024-08-01..2024-08-15`
  - `2024-08-01T00:00Z` to `2024-08-05T23:59Z` -> `cash`, `flat`
  - `2024-08-06T00:00Z` to `2024-08-08T23:59Z` -> `spot`, `long`
  - `2024-08-09T00:00Z` to `2024-08-15T23:59Z` -> `cash`, `flat`
- `SOLUSDT 2025-01-15..2025-01-31`
  - `2025-01-15T00:00Z` to `2025-01-18T23:59Z` -> `spot`, `long`
  - `2025-01-19T00:00Z` to `2025-01-24T23:59Z` -> `futures`, `long`
  - `2025-01-25T00:00Z` to `2025-01-31T23:59Z` -> `cash`, `flat`
- `BTCUSDT 2025-12-01..2025-12-10`
  - `2025-12-01T00:00Z` to `2025-12-03T23:59Z` -> `futures`, `long`
  - `2025-12-04T00:00Z` to `2025-12-07T23:59Z` -> `spot`, `long`
  - `2025-12-08T00:00Z` to `2025-12-10T23:59Z` -> `cash`, `flat`

Fixture oracle contract:

- each replay fixture must include an `oracle.json` file
- each oracle entry is `{start, end, expected_mode, expected_side, note}`
- at least `20` labeled segments per fixture
- replay is considered passing only if segment accuracy is `>= 95%`
- the seed oracle segments above are the minimum baseline and may be refined only by explicit versioned review

## Cross-Validation Requirements

The system spec must be reviewed by:

- Codex local design pass
- Gemini external critique
- internal plan/verification review pass

Each reviewer must answer:

1. Are the features objective and reproducible?
2. Are the mode-switch rules economically coherent?
3. Are the risk controls strong enough for leveraged deployment?
4. Are there obvious overfitting or execution-risk gaps?

Cross-validation approval rubric:

- Gemini verdict must be `APPROVE`
- internal critic verdict must be `OKAY`
- internal verifier verdict must be `PASS`
- if any reviewer returns blocking findings, release is blocked until a new review cycle passes

## Live Release Gate

Live capital remains blocked until all are true:

- unit, replay, and resilience tests pass
- backtest is net-positive after costs
- paper trading passes for at least `30` days
- shadow validation shows slippage within modeled assumptions
- operator can explain any sampled trade using stored factor values alone
- parity test proves backtest, paper, and live-sim paths produce identical decisions for the same frozen snapshots

Auditability pass rule:

- randomly sample `30` closed trades from the latest validation cycle
- `100%` of sampled trades must be reconstructible from `decision_id` into a machine-generated markdown report containing config version, snapshot ID, factor values, thresholds crossed, order chain, and exit reason

## Evidence Artifacts

Store these artifacts for every validation cycle:

- strategy config snapshot
- backtest report
- paper-trade performance summary
- execution quality report
- reviewer notes from Codex and Gemini

Each artifact set must also include:

- config file hash
- snapshot schema version
- replay fixture identifiers
- backtest commit or working-tree identifier
- decision-log completeness report
- strategy parity report
- resilience recovery report

Artifact validity requirement:

- each validation cycle must include a machine-checkable `manifest.json`
- the manifest must enumerate every required artifact filename, SHA256 hash, schema version, and generation timestamp
- a cycle fails if any manifest entry is missing or if any referenced artifact fails schema validation
