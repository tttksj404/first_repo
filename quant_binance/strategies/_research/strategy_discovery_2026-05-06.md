# Strategy Discovery Brief - 2026-05-06

## Question

Past strategy search has mostly exhausted parameter tuning around the current CH1/Mingogogo-style long lottery engine. The next useful step is not another broad mutation sweep, but strategy discovery: separate the surviving edge shape from repeated failure modes, then test a few genuinely different alpha sources.

This is research evidence, not live-trading approval.

## Evidence Summary

The existing long-lottery family has one robust shape:

- `threshold ~= 80`
- `hold = 24h` or `36h`
- `universe = no_dead` or sometimes `top10`
- `size ~= 0.20` on `$100`
- `leverage = 15x-20x`
- `max_concurrent = 5`
- `ATR max = 6-10`, with `ATR min = 3` improving selectivity in several G800 winners

Best in-family evidence:

- `G400/G403`: stress-cost annual PnL around `$343.73`, `n=64`, `WR=87.5%`, liquidation-rate around `3.12%`.
- `G800`: `1458` grid combos tested, `14` robust passers. Top variants cluster around `thr=80`, `hold=24/36`, `univ=no_dead`, `lev=20`, `size=0.2`, `max_conc=5`.
- `G800` strongest stress examples:
  - `hold=24`, `atr_min=0`, `atr_max=10`, `no_dead`, `20x`: `n=64`, `WR=87.5%`, annual PnL `$328.50`, liquidation-rate `3.12%`.
  - `hold=24`, `atr_min=3`, `atr_max=10`, `no_dead`, `20x`: `n=51`, `WR=94.12%`, annual PnL `$316.74`, liquidation-rate `1.96%`.
  - `hold=36`, `atr_min=3`, `atr_max=10`, `no_dead`, `20x`: `n=51`, `WR=90.20%`, annual PnL `$313.40`, liquidation-rate `1.96%`.

Repeated failure modes:

- Lowering threshold for frequency destroys edge. `G193` increased trades to `174` but dropped WR to `64.4%`; `G072` was deeply negative.
- Shorter holds weaken the thesis. `G188`, `G194`, `G141`, and UTC+1h variants underperformed or failed.
- Symmetric high-frequency long/short signals are cost-negative. `G500` family produced thousands of trades with negative annual PnL across periods.
- Short-only search has not found a stable edge. `G600` family mostly failed period positivity and expectancy.
- Extreme leverage gambling can inflate annual PnL but creates unacceptable path risk. `G710-G716` includes candidates with 10-26% liquidation rates or very thin samples.

## Interpretation

The current engine is not a general-purpose trading strategy. It is a sparse, long-only, post-overextension lottery/reversion sleeve. It wins when it waits for a narrow condition, lets the move breathe for about a day, and removes dead-weight symbols. It loses when forced to trade often, forced to short, or forced to exit quickly.

That means the next discovery work should not ask "how do we make this trade more often?" It should ask:

1. Can we make the current sparse sleeve safer with better path validation?
2. Can we add a second independent alpha source that naturally produces entries when CH1 is quiet?
3. Can we prove any new alpha survives the same three-period OOS/IS validation?

## Proposed Strategy Lines

### G900 - Path-Validated CH1 Lottery Core

Purpose: preserve the only confirmed in-family edge, but verify it with intrabar path risk instead of close-to-close optimism.

Candidate surface:

- `thr=80`
- `hold in {24, 36}`
- `atr_min in {0, 3}`
- `atr_max in {8, 10}`
- `univ in {no_dead, top10}`
- `lev in {15, 20}`
- `size=0.20`
- `max_conc=5`

Promotion gate:

- three periods positive
- stress cost positive
- liquidation rate <= 3%
- drawdown measured on path, not just final trade PnL
- no single symbol contributes more than 35% of total PnL

### G910 - Liquidation/OI Squeeze Alpha

Purpose: add an orthogonal source instead of stretching CH1. Use liquidation/OI/funding as primary signal, not as a late filter.

Hypothesis:

- crowded long liquidation clusters followed by OI reset can create short-term bounce entries
- crowded short liquidation clusters plus rising OI can create continuation entries
- funding extremes are useful only when paired with positioning reset and volume expansion

Candidate surface:

- liquidation spike percentile
- OI change over 1h/4h
- funding sign and percentile
- BTC regime gate
- hold `6h/12h/24h`
- max leverage `5x/10x`, not `20x` initially

Promotion gate:

- must beat CH1 on entry frequency without going cost-negative
- long and short legs evaluated separately
- no live promotion until paper sample exists

### G920 - Leader/Fills Mirror Alpha

Purpose: test whether Hyperliquid leaderboard/fill data creates a delayed copy or fade signal that is independent of candle-derived CH1.

Hypothesis:

- profitable trader clusters may predict short continuation when multiple leaders enter the same direction near breakout
- copy/fade should be evaluated by symbol, delay bucket, and market regime

Candidate surface:

- same-direction leader count
- leader realized PnL tier
- delay bucket `0-15m`, `15-60m`, `1-4h`
- copy vs fade
- hold `4h/12h/24h`

Promotion gate:

- enough fills per period
- no single leader dominates
- signal remains positive after realistic delay and cost

### G930 - 5m Structure Breakout Jackpot Replay

Purpose: evaluate the separate 5m high-upside paper logic with historical replay instead of relying on live-paper trickle samples.

Candidate surface:

- 12-bar structure breakout
- volume expansion
- BTC regime agreement
- ATR-aware stop
- compare `3x` and `5x`
- TP/runner/time-exit path simulation

Promotion gate:

- path-based replay positive before paper continuation
- live-paper used only as execution-quality evidence, not alpha proof

## Next Experiment Round

Round A: Build `G900` path validation first. It is the shortest route to knowing whether the current best-looking candidate is real after intrabar risk.

Round B: Run a small `G910` liquidation/OI prototype with 6-8 variants. This is the best candidate for a truly new alpha source because the repo already has fetch scripts and earlier PB104/PB103 notes.

Round C: Run `G920` only if the fill dataset has enough coverage after delay bucketing. If sample is too thin, archive it as a research lead instead of forcing a conclusion.

Round D: Replay `G930` to quantify the 5m jackpot bot's chop sensitivity before any live-risk discussion.

## Decision

Keep `G800`-style CH1 lottery as the current reference core, but stop trying to solve low frequency by lowering thresholds or adding shorts. The discovery path should branch into independent event/positioning/fill-based alphas, with the same three-period validation discipline.

## G900 Ensemble Discovery Update

Implemented and ran `quant_binance/strategies/_scripts/g900_ensemble_discovery.py`.

Result:

- `85` candidate combinations tested after pruning previously cost-negative broad structure variants.
- `12` candidates passed the research gate.
- The best candidate was `G914_path_safe_ch1`, not a forced multi-alpha blend.
- `G914` keeps CH1 selective long entries and adds path-based exits: `8x`, `30%` margin size, `36h` hold, `TP +12%`, `SL -7.5%`, `ATR 3-10%`.
- Weighted result: `51` trades, `68.63%` win rate, `$655.70` total PnL, `$153.42` annualized PnL, `0%` liquidation rate, all three periods positive.

Negative evidence:

- 20x close-to-close CH1 winners showed excessive intrabar liquidation exposure under path testing.
- Relaxed structure long/short breakout created thousands of trades but was cost-negative.
- Funding-fade as a parallel sleeve increased trade count but diluted win rate below promotion thresholds.
- Strict structure filters added no trades, so they were not a real ensemble improvement yet.

Current conclusion:

The best immediate strategy for the user's current small-capital context is `G914`: preserve the proven CH1 edge, but convert it from an unsafe hold-through-lottery into a path-safe TP/SL lottery. The next true ensemble step should test funding as a veto/filter and liquidation/OI as a primary signal, not as a naive parallel trade engine.

## G915 Exit/Veto Search Update

Implemented and ran `quant_binance/strategies/_scripts/g915_exit_veto_search.py`.

Result:

- `864` path-safe CH1 exit/veto variants tested.
- `192` candidates passed the research gate.
- Best candidate: `G1165_exit_veto_best`.
- Spec: `threshold=80`, `hold=36h`, `ATR=3-8%`, `10x`, `25%` margin size, `TP +14%`, `SL -7.5%`.
- Weighted result: `51` trades, `68.63%` win rate, `$825.43` total PnL, `$193.13` annualized PnL, `0%` liquidation rate, all three periods positive.

Comparison to `G914`:

- Annualized PnL improved from `$153.42` to `$193.13`.
- Liquidation rate stayed `0%`.
- Max period drawdown increased slightly from `$92.88` to `$96.75`, still under the `$100` research gate.

Funding veto finding:

- `max_funding <= 0.0008` tied the top result but did not change trades/performance in the tested periods.
- Therefore funding is not yet useful as a top-level entry engine or mandatory veto. It remains a future robustness filter candidate.

Current candidate hierarchy:

1. `G1165_exit_veto_best` - best bt-only path-safe CH1 candidate.
2. `G914_path_safe_ch1` - previous safer reference.
3. `G800/G400 close-to-close variants` - useful alpha evidence, but unsafe unless path exits are added.

## G1300 Two-Slot Search Update

Implemented and ran `quant_binance/strategies/_scripts/g1300_two_slot_search.py` to find two additional Oracle paper-slot candidates beyond deployed `G1165`.

Design:

- Baseline: deployed `G1165`.
- Candidate surface: `1,152` CH1 slot variants across `no_dead` and `top10` universes.
- Search dimensions: hold `24/36/48h`, ATR bands, `5x/6x/8x/10x` leverage-size profiles, TP `12/14/16%`, SL `6/7.5%`.
- Scoring includes G1165 entry-overlap penalty, so direct clones are de-prioritized.

Result:

- PASS candidates: `256 / 1,152`.
- Recommended slot 1: `G1995_top10_slot_ch1`.
  - Top10 universe, `10x`, `25%` margin, `36h`, `TP 16%`, `SL 7.5%`, `ATR 0-8%`.
  - Weighted: `57` trades, `70.18%` WR, `$874.09` PnL, `$204.51` annualized, `0` liquidations, max period DD `$97.89`.
  - G1165 overlap Jaccard: `0.5211`.
- Recommended slot 2: `G1503_no_dead_expansion_slot`.
  - No-dead universe, `6x`, `35%` margin, `48h`, `TP 16%`, `SL 7.5%`, `ATR 0-8%`.
  - Weighted: `64` trades, `62.50%` WR, `$805.47` PnL, `$188.46` annualized, `0` liquidations, max period DD `$89.79`.
  - G1165 overlap Jaccard: `0.7164`; chosen as the strongest non-clone no-dead expansion slot.

Decision:

Promote `G1995` and `G1503` as bt-only paper-slot candidates. They should be paper-deployed only after confirming that Oracle should run three simultaneous CH1-family services with separate margin accounting.
