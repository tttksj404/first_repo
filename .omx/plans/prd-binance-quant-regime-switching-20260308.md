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

Primitive feature definitions:

```text
breakout_norm =
  clamp(
    abs(last_trade_price - breakout_reference_price) /
    max(0.75 * atr_14_1h_price, 0.0025 * last_trade_price),
    0,
    1
  )

vol_z_5m_norm = clamp((zscore(quote_volume_5m, 20) + 2) / 4, 0, 1)
vol_z_1h_norm = clamp((zscore(quote_volume_1h, 20) + 2) / 4, 0, 1)

taker_imbalance_norm =
  clamp((buy_taker_volume - sell_taker_volume) / (buy_taker_volume + sell_taker_volume + epsilon) * 0.5 + 0.5, 0, 1)

spread_bps_norm = clamp(spread_bps / spread_bps_ceiling, 0, 1)
probe_slippage_bps_norm = clamp(probe_slippage_bps / slippage_bps_ceiling, 0, 1)

depth_10bps_norm = clamp(depth_usd_within_10bps / depth_usd_target, 0, 1)

book_stability_norm =
  1 - clamp(stddev(order_book_imbalance_1s, 30) / order_book_imbalance_std_ceiling, 0, 1)

realized_vol_1h_norm = percentile_rank(realized_vol_1h, history_90d)
realized_vol_4h_norm = percentile_rank(realized_vol_4h, history_90d)
vol_shock_norm = clamp(realized_vol_1h / max(median_realized_vol_1h_30d, epsilon) - 1, 0, vol_shock_ceiling) / vol_shock_ceiling

basis_stretch_percentile = percentile_rank(abs(basis_bps), basis_history_90d)
oi_surge_percentile =
  percentile_rank(
    max(open_interest / max(ema(open_interest, 24), epsilon) - 1, 0),
    oi_surge_history_90d
  )
```

Tie handling:

- percentile ranks use midpoint rank for ties
- any divide-by-zero guard uses `epsilon = 1e-9`
- any required primitive missing from snapshot yields `DATA_INCOMPLETE`

### 1. Trend Score

Directional persistence score built from:

- 1h return rank within rolling 90-day window
- 4h return rank within rolling 90-day window
- EMA slope alignment: `EMA(20) > EMA(50) > EMA(100)` for long trend and inverse for short trend
- breakout distance from the prior `20` completed `1h` bars high / low

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
- `breakout_reference_price` = prior `20` completed `1h` bars high for longs, low for shorts
- `breakout_norm` = normalized distance from the breakout reference, clamped to `[0, 1]`
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

Decision cadence:

- the strategy evaluates one immutable snapshot every completed `5` minutes
- all consecutive-cycle rules refer to consecutive completed `5m` decision snapshots
- intra-cycle market data updates may refresh buffers, but cannot trigger a new regime decision before the next `5m` boundary

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
gross_expected_edge_bps >= 1.5 * estimated_round_trip_cost_bps
```

Estimated round-trip cost includes:

- taker/maker fees
- expected slippage
- funding drag for planned futures holding period

### Expected Edge Definition

`gross_expected_edge_bps` must come from historical conditional forward returns, not from a hand-tuned guess.

For each symbol and mode:

- bucket observations by `predictability_score` decile
- split by `trend_direction`
- compute median forward return over the mode horizon
- keep the value gross of execution and funding costs

Initial horizons:

- futures: `240` minutes
- spot: `720` minutes

Formula:

```text
gross_expected_edge_bps =
  median_forward_return_bps(
    symbol,
    mode,
    score_bucket,
    trend_direction,
    horizon
  )
```

Round-trip cost model:

```text
estimated_round_trip_cost_bps =
  entry_fee_bps +
  exit_fee_bps +
  expected_entry_slippage_bps +
  expected_exit_slippage_bps +
  expected_funding_drag_bps
```

Net edge for reporting only:

```text
net_expected_edge_bps =
  gross_expected_edge_bps - estimated_round_trip_cost_bps
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

`system health is degraded` is true if any of the following holds:

- any required market stream is stale for more than `stale_data_seconds`
- snapshot freshness exceeds `2 * stale_data_seconds`
- order-state reconciliation lag exceeds `15` seconds
- two consecutive decision cycles fail snapshot validation
- kill-switch is armed by risk or broker error policy

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

Passive entry is allowed only when all conditions pass:

- spread is at most `4 bps`
- queue-adjusted fill probability over the next `30` seconds is at least `65%`
- maker fee advantage plus spread capture exceeds modeled adverse selection by at least `1 bp`

Otherwise route to aggressive execution or skip if the slippage budget is exceeded.

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

`feature_values` must use a fixed flat schema with units:

- `ret_rank_1h`: unitless `[0,1]`
- `ret_rank_4h`: unitless `[0,1]`
- `breakout_norm`: unitless `[0,1]`
- `ema_stack_score`: unitless `[0,1]`
- `vol_z_5m_norm`: unitless `[0,1]`
- `vol_z_1h_norm`: unitless `[0,1]`
- `taker_imbalance_norm`: unitless `[0,1]`
- `spread_bps_norm`: unitless `[0,1]`
- `probe_slippage_bps_norm`: unitless `[0,1]`
- `depth_10bps_norm`: unitless `[0,1]`
- `book_stability_norm`: unitless `[0,1]`
- `realized_vol_1h_norm`: unitless `[0,1]`
- `realized_vol_4h_norm`: unitless `[0,1]`
- `vol_shock_norm`: unitless `[0,1]`
- `funding_abs_percentile`: unitless `[0,1]`
- `oi_surge_percentile`: unitless `[0,1]`
- `basis_stretch_percentile`: unitless `[0,1]`
- `regime_alignment`: unitless `[0,1]`
- `trend_strength`: unitless `[0,1]`
- `volume_confirmation`: unitless `[0,1]`
- `liquidity_score`: unitless `[0,1]`
- `volatility_penalty`: unitless `[0,1]`
- `overheat_penalty`: unitless `[0,1]`
- `predictability_score`: points `[0,100]`
- `gross_expected_edge_bps`: bps
- `net_expected_edge_bps`: bps
- `estimated_round_trip_cost_bps`: bps

## Decision Log Contract

Every trade or skip decision must persist:

- `decision_id`
- `decision_hash`
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
- `gross_expected_edge_bps`
- `net_expected_edge_bps`
- `estimated_round_trip_cost_bps`
- `order_intent_notional_usd`
- `stop_distance_bps`
- `linked_order_ids`
- `exit_reason_code`
- `divergence_code`
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

Verification method for criterion 5:

- run the same frozen snapshot fixtures through backtest, paper, and live-sim strategy entrypoints
- require byte-identical decision payloads and matching `decision_hash`

Verification method for criterion 6:

- given `decision_id` alone, an automated audit script must reconstruct the config version, snapshot, feature values, decision payload, linked orders, and exit reason without manual lookup

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
