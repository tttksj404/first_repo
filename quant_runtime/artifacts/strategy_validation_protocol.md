# Strategy Validation Protocol

## Purpose

This protocol defines the minimum evidence required before a strategy idea can move from research to paper-live, micro-live, and live override approval.

The goal is to stop strategy selection from being driven by a single attractive metric such as total PnL, PF, or one favorable recent run.

For this repo, final approval should always prioritize:

1. Path realism
2. Cost realism
3. Recent-regime robustness
4. Execution quality
5. Operational simplicity

## Strategy Classes

Use the same validation pipeline for every candidate, but tag the strategy class first because evidence quality requirements differ by class.

- `conviction_swing`
  Long hold, low win rate, high R multiple, fat-tail payoff. Example: PEPE hantang style.
- `rotation_trend`
  Directional regime-following strategy across a small symbol set.
- `execution_overlay`
  Exit logic, TP ladder, trailing, or order-routing changes applied to an existing entry model.
- `filter_overlay`
  Weekday, time-of-day, drawdown recovery, macro, or regime gating applied to an existing base strategy.

## Approval Stages

### Stage 0: Hypothesis

Required output:

- Strategy name
- Strategy class
- Symbols
- Hold horizon
- Leverage / margin assumptions
- Exact entry trigger
- Exact exit trigger
- Primary failure mode

Reject immediately if the idea cannot be stated in one paragraph with explicit rules.

### Stage 1: Broad Search

Purpose:

- Fast rejection of weak ideas
- Not final approval

Tools:

- `quant_binance/backtest/run_bootstrap.py`
- `quant_binance/backtest/analyze_backtest.py`

Required checks:

- Positive net result after cost sweep
- Symbol-level breakdown is not dominated by a single accidental outlier
- Score buckets show directional improvement, or the edge is intentionally low-score contrarian and documented as such

Pass criteria:

- Candidate remains positive at base cost and one harsher cost scenario
- Trade count is large enough to be worth deeper simulation

Notes:

- Do not approve a strategy from Stage 1 alone.
- `batch_backtest.py` uses forward-return shortcuts and is only a search filter, not a final judge.

### Stage 2: Path-Based Simulation

Purpose:

- Validate the actual payout path of the strategy
- Especially important for high-leverage and long-hold systems

Tools:

- `quant_binance/backtest/tp_execution_backtest.py`
- Strategy-specific path simulators such as PEPE / swing-hold style runs

Required checks:

- Exit path realism on 5m bars
- Hold horizon realism
- Partial exit / trailing / full-exit behavior
- Leverage sensitivity
- Margin fraction sensitivity

Primary metrics:

- PF
- Total PnL
- Median final equity
- Ruin probability
- Time-to-double or capital-multiplication speed

Pass criteria:

- Positive result survives at least 3 nearby parameter variants
- Ruin remains acceptable for the intended account mode
- Median outcome is not wildly weaker than headline total PnL

Notes:

- For bootstrap-style small-capital strategies, optimize for capital growth shape, not smoothness.
- For builder-style strategies, optimize for repeatability first.

### Stage 3: Recent Replay Comparison

Purpose:

- Check whether the candidate still works in recent market structure
- Prevent adoption of strategies that only look good in old data

Tools:

- `quant_binance/backtest/recent_comparison.py`
- `quant_binance/backtest/comparison.py`

Required checks:

- Compare candidate against current strategy
- Compare candidate against at least one simple baseline
- Inspect walk-forward windows, not just aggregate totals

Primary metrics:

- Positive walk-forward ratio
- Window count
- Relative performance vs baseline
- Rejection / blocked opportunity pattern

Pass criteria:

- Candidate beats or clearly complements the current strategy in recent replay
- Candidate is not just parity with a simpler baseline

### Stage 4: Cost and Execution Reality Check

Purpose:

- Make sure a backtest edge survives the real exchange surface

Inputs:

- `quant_runtime/artifacts/cost_calibration.json`
- `quant_runtime/execution_quality_state.json`
- Paper/live execution summaries

Required checks:

- Slippage sample count is non-trivial for the target symbols
- Fee and slippage assumptions are symbol-specific where possible
- Strategy survives stress at `+5bps`, `+10bps`, and `+15bps` slippage where relevant

Pass criteria:

- Edge survives at realistic and stressed cost assumptions
- Execution quality does not imply that live fills will erase the modeled edge

Hard warning:

- If symbol slippage sample count is near zero, approval confidence must be downgraded.

### Stage 5: Paper-Live Validation

Purpose:

- Validate decision behavior, blocked opportunity behavior, and execution plumbing

Required checks:

- Closed trade count
- Realized PnL
- Blocked opportunities
- Policy validation status
- Sustainability report

Minimum evidence:

- At least `20` closed trades for normal promotion consideration
- At least `3` walk-forward windows if the run is segmented that way

Promotion blockers:

- `policy_validation_status != pass`
- `needs_work` sustainability verdict with unresolved reasons
- Too many blocked profit opportunities
- Operating state mismatch

### Stage 6: Micro-Live

Purpose:

- Confirm that paper edge is retained in real fills

Required checks:

- Realized edge retention
- Reject rate
- Fill ratio
- Protection degraded rate
- Realized vs expected edge gap

Pass criteria:

- Positive realized PnL or clearly positive realized edge retention
- No major execution degradation
- No safety / reconciliation problems

## Decision Rules

### Approve to Research Candidate

Allow if:

- Stage 1 passes

### Approve to Paper-Live

Allow only if:

- Stage 1 passes
- Stage 2 passes
- Stage 3 passes
- Stage 4 is at least partially credible

### Approve to Micro-Live

Allow only if:

- Stage 2 and Stage 3 remain positive
- Stage 5 has enough evidence
- No unresolved execution-quality red flags

### Approve to Live Override

Allow only if:

- Candidate beats or meaningfully complements the current strategy
- Cost realism is acceptable
- Paper-live evidence is no longer thin
- Recent replay is not baseline-parity only
- The candidate aligns with the actual symbol universe and capital objective

## Required Output for Every Approval Memo

Every approval or rejection note must explicitly answer:

1. What is the strategy trying to optimize: jackpot growth, repeatable compounding, or execution robustness?
2. What is the exact symbol universe?
3. What assumptions are path-dependent?
4. What assumptions are cost-sensitive?
5. What recent-regime evidence exists?
6. What is the minimum live sample still missing?
7. What would invalidate the strategy fastest?

## Current Repo Guidance

Based on the current repo structure, use these rules immediately:

- Treat `batch_backtest.py` as a search filter only.
- Treat path-based exit simulation as mandatory for any `72h` hold or high-leverage strategy.
- Do not approve new symbol rotations if the best verified edge is still concentrated in a different symbol.
- Do not compare ruin numbers across reports unless leverage, margin fraction, stop, and hold horizon are matched.
- Do not promote a strategy when execution-quality evidence is still effectively zero.

## Recommended Validation Loop

1. Run broad search and reject weak ideas quickly.
2. Run path-based simulation on the survivors.
3. Replay the most recent regime against baselines.
4. Stress costs with realistic and pessimistic slippage.
5. Run paper-live until trade count is no longer thin.
6. Run micro-live with intentionally tiny size.
7. Only then consider live override approval.

## PEPE-Style Exception

For a PEPE / high-conviction meme strategy, final judgment should emphasize:

- OOS PF
- Slippage-stressed ruin
- Parameter robustness across nearby variants
- Median final equity
- Time-to-double

and should de-emphasize:

- Smooth equity curve
- High win rate
- Low blocked-opportunity count

because those are not the primary design goal of a fat-tail bootstrap strategy.
