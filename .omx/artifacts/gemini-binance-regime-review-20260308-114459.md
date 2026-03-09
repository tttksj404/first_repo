# Gemini Review Artifact

## Original user task
Validate the Binance spot/futures/cash regime-switching quant design with Gemini using the strongest available model.

## Final prompt sent to Gemini CLI
```text
Re-review this updated Binance quant regime-switching design. Compare against the earlier issues: undefined expected_edge_bps, missing feature formulas, missing sizing/exit rules, vague validation thresholds, and futures-overheat downgrade conflict.
Return sections exactly as:
1. Verdict: APPROVE or REVISE
2. Resolved issues
3. Remaining blockers
4. Any rule conflicts still present
5. Minimal next build order

### FILE: .omx/plans/prd-binance-quant-regime-switching-20260308.md
# PRD: Binance Quant Regime-Switching Trading System

## Objective

Build a Binance-based crypto trading system that switches between futures, spot, and cash based on a fully quantitative market predictability score.

The system must not use discretionary overrides for entry mode selection. Every position decision must be traceable to numeric features, thresholds, and cost-adjusted expected edge.

## Product Scope

### In Scope

- Binance spot and USD-M futures market data ingestion
- Real-time feature calculation from exchange data
- Quantitative regime classification: `futures`, `spot`, `cash`
- Long and short futures execution when confidence is high
- Long-only spot execution when confidence is medium and upside is favorable
- No-trade state when confidence is weak or market conditions are poor
- Risk, leverage, and loss-limit enforcement
- Replay/backtest, paper-trading, and live shadow-mode support
- Structured decision logs for every action

### Out of Scope for MVP

- News, social sentiment, or on-chain data
- Portfolio optimization across dozens of low-liquidity altcoins
- Adaptive machine learning models without strong baseline evidence
- Cross-exchange arbitrage
- Options trading

## User Value

- Reduce discretionary bias by forcing all trade decisions through explicit numeric gates
- Use futures only when trend persistence and market quality are strong enough to justify leverage
- Fall back to spot or cash when signal quality drops
- Make every trade explainable after the fact with stored factor values

## Quantitative Thesis

The MVP uses a conservative blend of:

- time-series momentum / trend persistence
- multi-horizon trend confirmation
- liquidity and microstructure quality
- volatility and overheating penalties
- futures-specific positioning filters

This is aligned with recent crypto literature showing:

- time-series momentum is more robust than naive cross-sectional momentum in crypto
- trend composites can survive transaction costs in larger, more liquid coins
- volatility-managed momentum improves risk-adjusted returns
- carry and positioning extremes are useful as risk filters, not just alpha signals

Reference links:

- https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4675565
- https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/trend-factor-for-the-cross-section-of-cryptocurrency-returns/4C1509ACBA33D5DCAF0AC24379148178
- https://www.sciencedirect.com/science/article/abs/pii/S1544612325011377
- https://www.bis.org/publ/work1087.htm

## Universe

Start with liquid symbols only:

- `BTCUSDT`
- `ETHUSDT`
- `SOLUSDT`

Expansion is allowed only after live execution quality is proven.

## Core Operating Rule

Mode selection is three-state, not two-state:

- `futures`: high-confidence directional opportunity
- `spot`: medium-confidence upside opportunity
- `cash`: weak predictability or poor execution conditions

Low predictability must default to `cash`, not automatically to `spot`.

## Market Data Inputs

### Spot

- trades / aggregate trades
- order book depth
- klines: `1m`, `5m`, `15m`, `1h`, `4h`
- 24h ticker stats

### Futures

- funding rate history
- open interest
- mark price / premium index
- futures order book and trades

Primary API references:

- https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams
- https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints
- https://developers.binance.com/docs/binance-spot-api-docs/rest-api/trading-endpoints
- https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest
- https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History
- https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order

## Feature Set

All raw features are normalized to a `0.0` to `1.0` scale before weighted aggregation unless otherwise noted.

### Normalization Method

Use one normalization method consistently for reproducibility:

- percentile-rank normalization over a rolling `90`-day history for return, volume, volatility, funding, and open-interest features
- bounded clamp normalization for spread and slippage features using config ceilings
- missing values force `cash` mode and emit a `DATA_INCOMPLETE` rejection reason

For any scalar `x` with rolling history `H`:

```text
percentile_rank(x, H) = rank_of_x_within_H / len(H)
```

This avoids instability from min/max scaling on heavy-tailed crypto data.

### 1. Trend Score

Directional persistence score built from:

- 1h return rank within rolling 90-day window
- 4h return rank within rolling 90-day window
- EMA slope alignment: `EMA(20) > EMA(50) > EMA(100)` for long trend and inverse for short trend
- breakout distance from 20-bar high / low

Output:

- `trend_direction` in `{-1, 0, +1}`
- `trend_strength` in `[0.0, 1.0]`

Formula:

```text
trend_strength =
  0.35 * ret_rank_1h +
  0.35 * ret_rank_4h +
  0.15 * breakout_norm +
  0.15 * ema_stack_score
```

Where:

- `ret_rank_1h` = percentile rank of 1h return over rolling 90-day 1h returns
- `ret_rank_4h` = percentile rank of 4h return over rolling 90-day 4h returns
- `breakout_norm` = normalized distance from 20-bar breakout level, clamped to `[0, 1]`
- `ema_stack_score` = `1.0` when aligned, `0.5` when partially aligned, `0.0` when misaligned

Directional state:

```text
bull_votes = count(1h_trend_up, 4h_trend_up, ema_stack_bullish)
bear_votes = count(1h_trend_down, 4h_trend_down, ema_stack_bearish)

trend_direction =
  +1 if bull_votes >= 2 and bull_votes > bear_votes
  -1 if bear_votes >= 2 and bear_votes > bull_votes
   0 otherwise
```

### 2. Volume Confirmation Score

Measures whether the move is supported by participation:

- rolling volume z-score on `5m` and `1h`
- quote-volume expansion vs 20-bar baseline
- aggressive taker imbalance from trade stream

Output:

- `volume_confirmation` in `[0.0, 1.0]`

Formula:

```text
volume_confirmation =
  0.40 * vol_z_5m_norm +
  0.35 * vol_z_1h_norm +
  0.25 * taker_imbalance_norm
```

### 3. Liquidity Quality Score

Rejects trades that are statistically attractive but operationally poor:

- best bid/ask spread in basis points
- visible depth at `10 bps` and `25 bps`
- expected slippage for target notional
- order book imbalance stability

Output:

- `liquidity_score` in `[0.0, 1.0]`

Liquidity scoring must avoid circular dependence on final order size.

Use a fixed probe notional first:

```text
liquidity_probe_notional_usd = 1000
```

Calculate slippage and depth quality at this probe size for regime selection. Re-check slippage after sizing and block the order if the realized pre-trade estimate breaches configured tolerance.

Formula:

```text
liquidity_score =
  0.35 * (1 - spread_bps_norm) +
  0.35 * depth_10bps_norm +
  0.20 * (1 - probe_slippage_bps_norm) +
  0.10 * book_stability_norm
```

### 4. Volatility Penalty

Penalizes unstable states:

- realized volatility over `1h` and `4h`
- ATR / price ratio
- volatility shock vs trailing median

Output:

- `volatility_penalty` in `[0.0, 1.0]`

Formula:

```text
volatility_penalty =
  0.45 * realized_vol_1h_norm +
  0.35 * realized_vol_4h_norm +
  0.20 * vol_shock_norm
```

### 5. Futures Overheat Penalty

Used only for futures eligibility:

- absolute funding rate percentile
- open interest surge percentile
- basis / premium stretch

Output:

- `overheat_penalty` in `[0.0, 1.0]`

Formula:

```text
overheat_penalty =
  0.40 * funding_abs_percentile +
  0.35 * oi_surge_percentile +
  0.25 * basis_stretch_percentile
```

### 6. Directional Consistency Gate

A hard filter, not just a weighted input:

- 1h and 4h trend direction must match for `futures`
- spot entries require positive medium-horizon direction
- conflicting direction across horizons downgrades to `cash`

### 7. Regime Alignment

This factor is distinct from `trend_strength` and rewards agreement across horizons.

```text
regime_alignment =
  1.0 if 1h, 4h, and EMA stack all agree
  0.5 if 1h and 4h agree but EMA stack lags
  0.0 otherwise
```

## Predictability Score

### Base Formula

```text
predictability_score =
  100 * (
    0.35 * trend_strength +
    0.20 * volume_confirmation +
    0.20 * liquidity_score +
    0.10 * regime_alignment +
    0.10 * (1 - volatility_penalty) +
    0.05 * (1 - overheat_penalty)
  )
```

Where:

- `regime_alignment` rewards multi-horizon directional agreement
- the sign of the trade is determined by `trend_direction`
- `overheat_penalty` is applied mainly to futures gating, not to long-only spot selection

### Cost-Adjusted Edge Gate

No order is allowed unless:

```text
expected_edge_bps >= 1.5 * estimated_round_trip_cost_bps
```

Estimated round-trip cost includes:

- taker/maker fees
- expected slippage
- funding drag for planned futures holding period

### Expected Edge Definition

`expected_edge_bps` must come from historical conditional forward returns, not from a hand-tuned guess.

For each symbol and mode:

- bucket observations by `predictability_score` decile
- split by `trend_direction`
- compute median forward return over the mode horizon
- subtract exchange fees and expected funding drag

Initial horizons:

- futures: `240` minutes
- spot: `720` minutes

Formula:

```text
expected_edge_bps =
  median_forward_return_bps(
    symbol,
    mode,
    score_bucket,
    trend_direction,
    horizon
  )
  - expected_slippage_bps
```

Fallback rule:

- if per-symbol bucket observations are below `200`, use the pooled universe bucket
- if pooled observations are also below `200`, route to `cash`

## Regime Switching Rules

### Evaluation Precedence

Mode selection is ordered:

1. Evaluate `futures`
2. If futures is blocked, re-evaluate `spot`
3. Otherwise route to `cash`

This means a high score does not force futures. If the futures candidate is blocked by overheat, leverage, or futures-only constraints, the same snapshot may still qualify for `spot` if the spot gates pass.

### Futures Mode

Allowed only when all conditions pass:

- `predictability_score >= 75`
- `abs(trend_direction) = 1`
- `trend_strength >= 0.70`
- `liquidity_score >= 0.70`
- `volatility_penalty <= 0.45`
- `overheat_penalty <= 0.35`
- `expected_edge_bps` passes cost gate

Direction:

- long futures if `trend_direction = +1`
- short futures if `trend_direction = -1`

### Spot Mode

Allowed only when all conditions pass:

- `predictability_score >= 55`
- `trend_direction = +1`
- `trend_strength >= 0.50`
- `liquidity_score >= 0.60`
- `volatility_penalty <= 0.60`
- `expected_edge_bps` passes cost gate

Spot mode is long-only for MVP.

### Cash Mode

Default state when:

- predictability is weak
- liquidity is poor
- volatility shock is extreme
- futures overheat is excessive
- signal direction is inconsistent
- system health is degraded

## Position Sizing

### Common Rules

- volatility-targeted sizing
- single-trade capital-at-risk: `0.35%` of equity
- max symbol exposure: `20%` of equity notional
- max total portfolio exposure: `50%` of equity notional

Sizing formula:

```text
risk_dollars = equity * per_trade_equity_risk
stop_distance_bps = max(1.5 * atr_14_1h_bps, 45)
raw_notional_usd = risk_dollars / (stop_distance_bps / 10000)
position_notional_usd =
  min(
    raw_notional_usd,
    equity * max_symbol_exposure,
    remaining_portfolio_capacity
  )
```

This makes high-volatility symbols naturally smaller.

### Futures Rules

- initial leverage cap: `1.5x`
- hard leverage cap: `2.0x`
- max concurrent futures symbols: `2`
- futures mode disabled for 24h after daily loss limit breach

Futures quantity:

```text
futures_qty = position_notional_usd / mark_price
```

### Spot Rules

- max concurrent spot symbols: `3`
- laddered entries in at most `3` slices
- no averaging down after stop trigger

Spot quantity:

```text
spot_qty = position_notional_usd / last_trade_price
```

## Risk Controls

- daily realized loss stop: `2.0%` of equity
- weekly realized loss stop: `5.0%` of equity
- max intraday drawdown from peak: `2.5%`
- emergency flat-all on:
  - websocket desync
  - stale market data beyond threshold
  - order state reconciliation failure
  - repeated API signature or permission errors

## Exit Logic

Every entry must have a predefined exit plan.

### Hard Stop

- initial stop distance: `max(1.5 * ATR_14_1h, 45 bps)`
- stop order or synthetic stop must be armed immediately after entry acknowledgement

### Profit Taking

- take off `50%` at `+1.5R`
- move remaining stop to break-even after first take-profit fill

### Trend Exit

Exit the remaining position if any of the following is true for `2` consecutive decision cycles:

- `predictability_score` falls below the active mode minimum by more than `5` points
- `trend_direction` flips against the position
- `liquidity_score` falls below required minimum by more than `0.10`

### Time Stop

- futures max holding time: `24` hours
- spot max holding time: `72` hours

## Execution Policy

- prefer passive entries only when spread and fill probability justify them
- otherwise cross the spread with size bounded by slippage budget
- use reduce-only for futures exits where applicable
- always place protective stop logic immediately after entry acknowledgement

## System Components

- market data collector
- feature engine
- regime scorer
- risk engine
- execution engine
- order state reconciler
- replay / backtest runner
- paper-trading broker adapter
- structured decision logger
- monitoring and kill-switch service

## Snapshot Schema

The decision engine consumes only immutable synchronized snapshots. Each snapshot must contain:

- `snapshot_id`
- `config_version`
- `symbol`
- `decision_time`
- `last_trade_price`
- `best_bid`
- `best_ask`
- `ohlcv_windows` for `1m`, `5m`, `15m`, `1h`, `4h`
- `funding_rate`
- `open_interest`
- `basis_bps`
- `feature_values`
- `data_freshness_ms`

Backtest, paper, and live mode must all pass the same snapshot schema into the strategy layer.

## Decision Log Contract

Every trade or skip decision must persist:

- `decision_id`
- `snapshot_id`
- `config_version`
- timestamp
- symbol
- candidate mode
- final mode
- `trend_direction`
- `trend_strength`
- `volume_confirmation`
- `liquidity_score`
- `volatility_penalty`
- `overheat_penalty`
- `predictability_score`
- `expected_edge_bps`
- `estimated_round_trip_cost_bps`
- `order_intent_notional_usd`
- `stop_distance_bps`
- rejection reasons or execution reason

Reason codes must come from a fixed taxonomy, including:

- `SCORE_TOO_LOW`
- `DIRECTION_CONFLICT`
- `LIQUIDITY_TOO_WEAK`
- `VOL_TOO_HIGH`
- `FUTURES_OVERHEAT`
- `EDGE_BELOW_COST`
- `DATA_INCOMPLETE`
- `RISK_LIMIT_BLOCK`

## Acceptance Criteria

1. Every entry decision is fully reproducible from stored numeric features and config thresholds.
2. The same inputs always yield the same mode decision.
3. Futures cannot execute when any hard gate fails.
4. Low-confidence states route to cash, not spot by default.
5. Backtest and paper-trade paths use the same strategy logic as live mode.
6. Decision logs are sufficient for post-trade audit without manual interpretation.

## Implementation Phases

### Phase 1

- data adapters
- feature pipeline
- regime scoring
- paper-trade execution

### Phase 2

- backtest and replay harness
- performance analytics
- live shadow-mode

### Phase 3

- guarded live trading with small capital
- monitoring, alerting, and recovery automation


### FILE: .omx/plans/test-spec-binance-quant-regime-switching-20260308.md
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
- no flaky tests

### 2. Historical Replay Tests

Goal: verify feature generation and signal timing using recorded market data.

Required coverage:

- replay over normal trend periods
- replay over volatility shock periods
- replay over chop / low-conviction periods
- replay over funding and open-interest extremes

Acceptance:

- no look-ahead bias in feature computation
- replay decisions match expected regime transitions on curated fixtures

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

- positive net expectancy after costs
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
- parameter updates are limited to at most `1` release per calendar quarter

### 5. Paper Trading

Goal: test live data, order handling, and decision behavior with zero capital risk.

Required runtime:

- minimum `30` calendar days

Required checks:

- decision logs are complete
- orders reconcile with simulated fills
- stale data alarms trigger correctly
- regime switching frequency is reasonable
- reject rate and retry rate stay within thresholds

Acceptance:

- no critical reconciliation failures
- no uncontrolled order loops
- average mode switches stay at or below `6` per symbol per day
- no more than `2` direction flips for the same symbol within `60` minutes
- order reject rate stays below `1.0%`
- retry rate stays below `2.0%`
- fill reconciliation mismatch rate stays below `0.1%`

### 6. Shadow Live Validation

Goal: compare paper decisions to what live execution would have done under current market conditions.

Required checks:

- slippage estimate vs observed quote movement
- entry and exit timing drift
- signal decay between decision and order creation

Acceptance:

- average realized slippage error stays within `20%` of the modeled value and never exceeds `5 bps` absolute error on average
- paper/live decision divergence is explained and logged

## Regime-Specific Test Cases

## Threshold Boundary Fixtures

These fixtures are mandatory because mode selection is threshold-driven.

Required exact decision cases:

- `predictability_score = 54.99` -> `cash`
- `predictability_score = 55.00`, positive trend, all spot gates pass -> `spot`
- `predictability_score = 74.99`, all futures gates pass otherwise -> `spot`
- `predictability_score = 75.00`, all futures gates pass -> `futures`
- `expected_edge_bps = 1.49 * estimated_round_trip_cost_bps` -> reject
- `expected_edge_bps = 1.50 * estimated_round_trip_cost_bps` -> eligible
- `volatility_penalty = 0.45` with futures candidate -> allowed
- `volatility_penalty = 0.4501` with futures candidate -> reject
- `overheat_penalty = 0.35` with futures candidate -> allowed
- `overheat_penalty = 0.3501` with futures candidate -> reject

### Futures-Eligible Long

Input profile:

- strong aligned uptrend
- high liquidity
- moderate volatility
- low overheat

Expected:

- `mode = futures`
- `side = long`

### Futures-Eligible Short

Input profile:

- strong aligned downtrend
- high liquidity
- moderate volatility
- low overheat

Expected:

- `mode = futures`
- `side = short`

### Spot-Eligible Long

Input profile:

- medium-confidence uptrend
- acceptable liquidity
- no severe volatility shock

Expected:

- `mode = spot`
- `side = long`

### Cash State

Input profile:

- weak trend
- conflicting horizons
- high volatility or poor liquidity

Expected:

- `mode = cash`
- no order submitted

### Overheat Downgrade

Input profile:

- trend appears strong
- funding percentile extreme
- open interest surge extreme

Expected:

- not eligible for futures
- routes to `spot` or `cash` depending remaining score

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
- recovery path documented and tested

## Required Replay Fixtures

The replay suite must include at minimum:

- `BTCUSDT`, `2024-02-20` to `2024-03-05`: strong trend regime
- `ETHUSDT`, `2024-08-01` to `2024-08-15`: choppy mixed regime
- `SOLUSDT`, `2025-01-15` to `2025-01-31`: high-momentum high-volatility regime
- `BTCUSDT`, `2025-12-01` to `2025-12-10`: funding and open-interest stress regime

Each fixture must document expected mode-transition sequences before the replay test is approved.

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

## Live Release Gate

Live capital remains blocked until all are true:

- unit, replay, and resilience tests pass
- backtest is net-positive after costs
- paper trading passes for at least `30` days
- shadow validation shows slippage within modeled assumptions
- operator can explain any trade using stored factor values alone

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


### FILE: quant_binance/README.md
# Binance Quant System Blueprint

## Goal

This directory defines the implementation blueprint for a Binance regime-switching crypto trading system.

The design intentionally separates market-state inference from execution so futures usage can be gated by quantifiable predictability rather than discretionary confidence.

## Suggested Python Package Layout

```text
quant_binance/
  README.md
  config.example.json
  settings.py
  data/
    spot_stream.py
    futures_stream.py
    snapshots.py
  features/
    trend.py
    volume.py
    liquidity.py
    volatility.py
    futures_positioning.py
  strategy/
    normalize.py
    scorer.py
    regime.py
    edge.py
  risk/
    sizing.py
    limits.py
    kill_switch.py
  execution/
    spot_broker.py
    futures_broker.py
    router.py
    reconcile.py
  backtest/
    replay.py
    metrics.py
    fixtures/
  observability/
    decision_log.py
    health.py
    alerts.py
```

## Runtime Flow

1. Collect spot and futures market data.
2. Build normalized feature snapshots per symbol.
3. Calculate `predictability_score` and directional state.
4. Select `futures`, `spot`, or `cash`.
5. Apply sizing and portfolio risk checks.
6. Submit or skip orders.
7. Reconcile broker state and persist decision logs.

## Required Design Rules

- Strategy logic must be shared across backtest, paper, and live modes.
- Exchange adapters may differ by mode, but decision logic may not.
- Every skipped trade must log a reason code.
- Every live order must be linked to the feature snapshot that produced it.
- Futures execution must be impossible if a hard gate fails.
- Every strategy call must consume the same immutable snapshot schema regardless of mode.
- Config changes must be versioned so decision replay can reproduce prior trades exactly.

## Implementation Order

1. Settings and config loading
2. Market data adapters
3. Feature calculations
4. Regime scorer
5. Risk checks
6. Paper broker adapter
7. Replay/backtest harness
8. Live execution adapter


### FILE: quant_binance/config.example.json
{
  "universe": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
  "klines": ["1m", "5m", "15m", "1h", "4h"],
  "normalization": {
    "method": "percentile_rank",
    "rolling_window_days": 90
  },
  "weights": {
    "trend_strength": 0.35,
    "volume_confirmation": 0.2,
    "liquidity_score": 0.2,
    "regime_alignment": 0.1,
    "inverse_volatility_penalty": 0.1,
    "inverse_overheat_penalty": 0.05
  },
  "mode_thresholds": {
    "futures_score_min": 75,
    "spot_score_min": 55,
    "futures_trend_strength_min": 0.7,
    "spot_trend_strength_min": 0.5,
    "futures_liquidity_min": 0.7,
    "spot_liquidity_min": 0.6,
    "futures_volatility_penalty_max": 0.45,
    "spot_volatility_penalty_max": 0.6,
    "futures_overheat_penalty_max": 0.35
  },
  "feature_thresholds": {
    "liquidity_probe_notional_usd": 1000,
    "min_expected_edge_observations": 200
  },
  "cost_gate": {
    "edge_to_cost_multiple_min": 1.5
  },
  "expected_edge": {
    "futures_horizon_minutes": 240,
    "spot_horizon_minutes": 720
  },
  "risk": {
    "per_trade_equity_risk": 0.0035,
    "max_symbol_notional_fraction": 0.2,
    "max_total_notional_fraction": 0.5,
    "max_futures_leverage": 2.0,
    "target_futures_leverage": 1.5,
    "daily_realized_loss_limit": 0.02,
    "weekly_realized_loss_limit": 0.05,
    "intraday_drawdown_limit": 0.025
  },
  "sizing": {
    "atr_multiple_for_stop": 1.5,
    "stop_floor_bps": 45
  },
  "exit_rules": {
    "partial_take_profit_r": 1.5,
    "post_tp_stop_mode": "breakeven",
    "futures_max_holding_minutes": 1440,
    "spot_max_holding_minutes": 4320,
    "score_drop_exit_buffer": 5,
    "liquidity_drop_exit_buffer": 0.1,
    "confirmation_cycles_for_exit": 2
  },
  "operational_limits": {
    "max_concurrent_futures_symbols": 2,
    "max_concurrent_spot_symbols": 3,
    "stale_data_seconds": 10,
    "max_order_retries": 3
  },
  "validation": {
    "paper_mode_switches_per_symbol_per_day_max": 6,
    "paper_direction_flips_per_symbol_per_hour_max": 2,
    "order_reject_rate_max": 0.01,
    "order_retry_rate_max": 0.02,
    "reconciliation_mismatch_rate_max": 0.001,
    "avg_slippage_error_abs_bps_max": 5
  }
}


```

## Gemini output (raw)
```text
1. Verdict: APPROVE

2. Resolved issues
- `expected_edge_bps` is now rigorously defined using historical conditional forward return buckets (no hand-tuned guessing).
- Feature formulas are explicit and mathematically sound, with weights correctly summing to 1.0.
- Sizing and exit rules are clearly mapped out (ATR-based risk sizing, 1.5R partial take-profits, time stops, and regime decay exits).
- Validation thresholds are strictly quantified (e.g., Out-of-sample Sharpe >= 65% of in-sample, max 6 switches/day in paper trading).
- The futures-overheat downgrade is resolved elegantly by the evaluation precedence rules: an overheated long drops to spot, while an overheated short drops to cash (since spot is long-only for the MVP).

3. Remaining blockers
None. The PRD is sufficiently detailed to begin implementation.

4. Any rule conflicts still present
**Minor Conflict (Double Counting Costs):** 
In the "Cost-Adjusted Edge Gate" section, the rule is `expected_edge_bps >= 1.5 * estimated_round_trip_cost_bps`, and the text states the round-trip cost includes taker/maker fees, expected slippage, and funding drag.
However, the text and formula immediately following it for `expected_edge_bps` say to subtract slippage, fees, and funding drag *from the median forward return*. 
If you subtract costs to get `expected_edge_bps`, and then require that net edge to be `>= 1.5 * costs`, you are heavily double-counting the costs. `expected_edge_bps` should just be the gross `median_forward_return_bps`, letting the `1.5 * cost` side of the inequality handle the safety margin.

5. Minimal next build order
**Phase 1 Execution:**
1. **Config & Schema:** Scaffold `config.json` loading and Pydantic/dataclass schemas for the immutable market snapshot.
2. **Data Adapters:** Implement Binance WebSockets (Spot + USD-M Futures) and order book depth tracking for the target universe (BTC, ETH, SOL).
3. **Feature Engine Pipeline:** Build the `percentile_rank` normalization utility and wire up the raw metrics (Trend, Volume, Liquidity, Volatility, Overheat).
4. **Scoring Logic:** Implement the `predictability_score` formula and the cascading `futures -> spot -> cash` gating logic.
```

## Concise summary
Selected model: gemini-3.1-pro-preview
Review of the updated design package after adding formulas, sizing, exits, and verification thresholds.

## Action items / next steps
- Compare Gemini findings with internal critic/verifier outputs.
- Patch the design docs if blockers remain.

## Runner notes
```text
[gemini-3.1-pro-preview STDERR]
Loaded cached credentials.
Error during discovery for MCP server 'notion': spawn notion-mcp-server.cmd ENOENT
```