# Position Generation Deep Dive

Updated: 2026-04-14

## Objective

This note answers 3 questions:

1. Why the current coin program is not emitting positions.
2. What must change if the goal is "PEPE-style high-upside positions must actually appear".
3. How to maximize profit per position without breaking the already-validated edge.

## Executive Summary

The main problem is not simply "the market is bad".

The current runtime path is misaligned with the strategy you actually want to trade.

- The repository root `.env` currently points runtime at `STRATEGY_PROFILE=live-ultra-aggressive` and `STRATEGY_OVERRIDE_PATH=quant_runtime/artifacts/strategy_override.approved.json`.
- The latest generic no-position evidence in `quant_runtime/output/paper-live-shell/latest/overview.json` is from 2026-04-07, before the approved override says it was applied on 2026-04-12.
- That generic run was evaluating `ETHUSDT`, `SOLUSDT`, `BNBUSDT`, not PEPE.
- The approved override that is now wired in is still `DOGEUSDT`, `XRPUSDT`, `SOLUSDT`, not PEPE.
- The validated PEPE edge exists in artifacts and coin profiles, but the generic live engine is not the same thing as a PEPE-specific hantang engine.

Conclusion:

The bot is not "refusing to trade in general". It is currently running the wrong universe and the wrong decision stack for the edge you want.

## What The Current Wiring Actually Does

### Runtime source of truth

`quant_binance/settings.py` loads settings in this order:

1. base config JSON
2. strategy profile override from env
3. `UNIVERSE_SYMBOLS` override from env
4. strategy override JSON from env path

Relevant code:

- [settings.py](../..//quant_binance/settings.py:392)
- [env.py](../..//quant_binance/env.py:41)

This matters because:

- base config starts from `ETHUSDT`, `SOLUSDT`, `BNBUSDT`
- `.env` currently selects `live-ultra-aggressive`
- the approved override file then replaces the universe with `DOGEUSDT`, `XRPUSDT`, `SOLUSDT`
- there is no PEPE in the active approved override

Relevant files:

- [.env](../../.env:1)
- [config.example.json](../../quant_binance/config.example.json:4)
- [strategy_override.approved.json](strategy_override.approved.json:1)

### The live supervisor path is generic, not PEPE-specialized

The supervisor script exports:

- `EXCHANGE=bitget`
- `STRATEGY_PROFILE=live-ultra-aggressive`
- `STRATEGY_OVERRIDE_PATH=$OUTPUT_BASE/artifacts/strategy_override.approved.json`
- `QUANT_BYPASS_POLICY_GUARDRAILS=1`

Relevant file:

- [scripts/quant_run_live_orders.sh](../../scripts/quant_run_live_orders.sh:97)

This means the main daemon is designed to run the approved generic override for `quant_runtime`, not a PEPE-only stage-1 engine.

## Why Positions Are Not Coming Out

## 1. The latest "no position" run is a cost-negative generic run

The latest generic overview shows:

- `ETHUSDT`: cost `38.03547 bps`, net edge `-35.60547 bps`
- `SOLUSDT`: cost `23.759728 bps`, net edge `-23.759728 bps`
- `BNBUSDT`: cost `38.03547 bps`, net edge `-36.772137 bps`

Relevant file:

- [overview.json](../output/paper-live-shell/latest/overview.json:25)

The matching supervisor log shows all 3 were blocked before submission:

- ETH: `DIRECTION_CONFLICT, EDGE_TOO_THIN, LIQUIDITY_TOO_WEAK, SCORE_TOO_LOW, SENTIMENT_CAUTION, SUPPORT_NOT_CONFIRMED`
- SOL: `DIRECTION_CONFLICT, LIQUIDITY_TOO_WEAK, SCORE_TOO_LOW, SENTIMENT_CAUTION, SUPPORT_NOT_CONFIRMED`
- BNB: `DIRECTION_CONFLICT, EDGE_TOO_THIN, LIQUIDITY_TOO_WEAK, SCORE_TOO_LOW`

Relevant file:

- [live_supervisor.log](../live_supervisor.log:249457)

So the immediate cause is:

- projected edge is already negative after modeled costs
- trend/direction was not clean enough
- liquidity/support gates also blocked

This is not a capital problem. The same summary shows enough futures balance to trade.

## 2. The generic engine is not watching the symbol family you validated

Your best verified edge is explicitly PEPE-based:

- strategy: `PEPE 15x margin50% TP150% SL3%`
- OOS PF `2.35`
- slippage 5bps ruin `5.8%`
- 1608 trades over 3 years

Relevant file:

- [final_verified_strategy.json](../output/final_verified_strategy.json:1)

But the currently wired approved override uses:

- universe: `DOGEUSDT`, `XRPUSDT`, `SOLUSDT`
- priority symbols: same
- major symbols: same

Relevant file:

- [strategy_override.approved.json](strategy_override.approved.json:21)

So even if the engine is healthy, it is not pointed at your top edge.

## 3. Coin profiles help execution and sizing, but they do not create a PEPE strategy by themselves

`coin_profiles.py` includes a strong PEPE profile with the comment:

- `3Y verified: 7d mom 15x margin50% TP150% SL3%`
- `OOS PF2.35`
- `MC ruin 1.8%`

Relevant file:

- [coin_profiles.py](../../quant_binance/strategy/coin_profiles.py:102)

But in the current architecture, coin profiles are mostly used for:

- EMA/ADX interpretation
- leverage selection
- stop/TP multiplier selection

They do **not** automatically transform the generic regime engine into a dedicated PEPE hantang signal engine.

This is why "PEPE is in coin profiles" and "the bot should therefore open PEPE positions" are not equivalent.

## 4. The cost model is large enough to kill marginal trades

Feature extraction currently estimates:

- `spread_bps` from top of book
- `probe_slippage_bps = spread_bps * 1.5`

Relevant file:

- [extractor.py](../../quant_binance/features/extractor.py:311)

Backtest/replay cost then uses:

- spread
- probe slippage
- taker fee twice

Relevant file:

- [comparison.py](../../quant_binance/backtest/comparison.py:26)

Cost calibration is also still thin for several symbols:

- ETH slippage samples: `3`
- BTC/SOL/XRP slippage samples: `0`

Relevant file:

- [cost_calibration.json](cost_calibration.json:1)

Implication:

If the engine's expected edge is only slightly positive before costs, it becomes cash very quickly after costs.

## 5. The generic engine already proves it *can* emit positions under another policy

A separate runtime wrapper exists for `conviction-sniper`:

- profile: `conviction-sniper`
- universe: `BTCUSDT,ETHUSDT,SOLUSDT`

Relevant file:

- [run_conviction_sniper.sh](../../scripts/run_conviction_sniper.sh:26)

That paper-live output shows actual futures positions:

- BTC short: cost `8.004354 bps`, net edge `12.617587 bps`
- ETH short: cost `8.145068 bps`, net edge `15.210069 bps`
- SOL short: cost `11.45658 bps`, net edge `19.617907 bps`

Relevant file:

- [overview.json](../output/conviction-sniper-v3.bak/output/paper-live-shell/latest/overview.json:27)

This is strong evidence that the problem is not "the whole bot architecture can't trade".
It is that the currently active generic path and the desired PEPE edge are misaligned.

## What Must Change If The Goal Is "Positions Must Appear In My Direction"

## 1. Split the engines

Do not try to make one generic runtime satisfy both goals:

- Stage 1: small-capital PEPE-style fat-tail betting
- Stage 2: broader live supervisor for larger capital and policy learning

Those are different systems.

Recommended split:

- Stage 1 bootstrap engine:
  - universe: `PEPEUSDT` only, or `PEPEUSDT,WIFUSDT`
  - objective: low-frequency, high-upside, long-hold fat-tail capture
  - top_n: `1`
  - exit philosophy: keep the validated all-or-nothing style
  - output base: separate from `quant_runtime`

- Stage 2 generic engine:
  - universe: broader set such as DOGE/XRP/SOL or majors
  - objective: later capital protection, policy evidence, more general operation
  - output base: keep `quant_runtime`

If you keep both ideas in one runtime, the generic policy logic will keep dominating symbol selection and you will continue getting "not the trade you actually wanted".

## 2. Make PEPE an actual runtime input, not just a research result

Right now PEPE exists as:

- a validated research artifact
- a coin profile

But not as:

- active runtime universe
- active priority symbol
- active approved override

If you want PEPE positions to appear, PEPE must be present in the live runtime's actual symbol set.

Minimum requirement for a Stage-1 PEPE engine:

- `UNIVERSE_SYMBOLS=PEPEUSDT`
- separate override file for PEPE Stage-1
- separate output directory
- separate launch script

Without this, the runtime cannot consistently emit PEPE positions because it is literally not centered on PEPE.

## 3. Do not force "always in market" behavior into the current quality-gated engine

The current regime logic intentionally rejects entries when:

- score is low
- direction is unclear
- liquidity is weak
- support is unconfirmed
- net edge is too thin after costs

Relevant file:

- [regime.py](../../quant_binance/strategy/regime.py:654)

Trying to force this engine into "market good or bad, always emit a position" will not produce your validated PEPE strategy.
It will produce a different strategy, and likely a worse one.

If you want near-always-on exposure, that must be a different strategy class, not just weaker gating on the current engine.

## What Maximizes Profit Per Position In This Repo

Based on the artifacts, per-position profit is maximized not by making the current generic engine looser everywhere, but by aligning runtime with the existing PEPE edge.

### A. Keep the validated exit philosophy

The approved override currently uses:

- `partial_take_profit_r = 999`
- `take_profit_roe_percent = 999`
- `portfolio_full_exit_only = true`

Relevant file:

- [strategy_override.approved.json](strategy_override.approved.json:62)

You already observed that tighter exits and winner-press templates underperformed in your own backtests.
So profit maximization here means preserving the fat-tail payoff structure, not adding frequent profit taking.

### B. Concentrate rather than diversify

The PEPE artifacts that won are not broad diversified moderate-return systems.
They are concentrated fat-tail systems.

That means the repo should reflect:

- one active symbol at a time
- one strategy family at a time
- capital concentration
- long hold tolerance

This is consistent with your stated goal.

### C. Do not confuse "more entries" with "more money"

For your objective, the right question is not:

- "How do I make the current bot produce more trades?"

It is:

- "How do I make the runtime produce the correct class of trades?"

The conviction-sniper example already proves that a different policy can create entries when the net edge survives costs.

So the path to more profit is not just lowering thresholds blindly.
It is aligning the live engine to the symbol + holding logic that your artifacts say actually works.

## Recommended Operating Blueprint

## Immediate operating decision

For current small capital:

- Use PEPE as primary Stage-1 symbol
- Optionally keep WIF as secondary research symbol
- Keep Stage-2 generic supervisor separate

## Recommended runtime structure

### Stage 1

- purpose: PEPE bootstrap / capital expansion
- universe: `PEPEUSDT`
- optional secondary candidate: `WIFUSDT`
- top_n: `1`
- dedicated output base, for example `quant_runtime_pepe_stage1`
- dedicated launch script, not the generic `quant_run_live_orders.sh`

### Stage 2

- purpose: broader live policy, evidence gathering, later capital protection
- separate output base
- generic supervisor remains acceptable here

## Validation order for any Stage-1 change

1. Candidate override only, not live-approved.
2. Realistic backtest with cost assumptions.
3. Path-based exit simulation for the exact hold/TP/SL structure.
4. Separate paper-live run for PEPE-only runtime.
5. Only then promote to live.

This avoids contaminating the generic runtime while you test the fat-tail engine.

## Specific Changes That Are Most Likely To Help

Ordered by expected value:

1. Create a separate PEPE Stage-1 runtime path.
2. Point Stage-1 universe at PEPE explicitly.
3. Keep `futures_top_n = 1`.
4. Preserve the validated non-tight exit structure.
5. Rebuild PEPE cost calibration with actual PEPE live/paper fills.

## Specific Changes That Are Most Likely To Hurt

1. Making the generic engine globally looser just to "force more positions".
2. Mixing PEPE bootstrap logic into the generic DOGE/XRP/SOL supervisor.
3. Tightening exits because it feels safer.
4. Assuming coin profile existence alone guarantees PEPE trade generation.

## Important local checkout caveats

### Margin mode

In this checkout, futures order payloads still show:

- `marginMode = "crossed"`

Relevant files:

- [live_order_adapter.py](../../quant_binance/execution/live_order_adapter.py:588)
- [bitget_rest.py](../../quant_binance/execution/bitget_rest.py:447)

If you already implemented isolated margin elsewhere, that change is not visible in this local tree yet.
So treat this report as a diagnosis of the current checkout, not a guarantee of another machine or branch.

### Git metadata

This directory is not currently a Git working tree from the local tool's point of view.
So the analysis above is based on files on disk, not branch history.

## External References

These were used only to support the execution/cost discussion:

- Freqtrade backtesting docs: https://docs.freqtrade.io/en/2024.11/backtesting/
- Bitget order cost guide: https://www.bitget.com/support/articles/12560603828198

Key takeaways from official docs:

- Freqtrade applies fee assumptions on entry and exit in backtests.
- Bitget states order cost directly affects actual PnL, especially in high-leverage or high-frequency setups.
- Bitget order cost includes transaction fee and possible funding fee.

## Final Conclusion

If the goal is:

- "I want positions to come out in the direction I care about"
- "I want each position to have maximum upside"

then the answer is not to keep hammering the current generic supervisor until it trades more.

The correct answer is:

1. stop treating the generic runtime as the PEPE strategy,
2. create a dedicated PEPE Stage-1 runtime,
3. keep its universe and exits aligned with the validated PEPE artifacts,
4. validate that runtime separately from the generic supervisor.

That is the shortest path from "no positions" to "the right positions".
