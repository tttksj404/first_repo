# Career Competency Log

This file stores only the conversations and work that materially connect to the user's target data/AI role competencies. It is intentionally selective.

## Target competencies

- Data analysis, planning, design, cleansing, optimization
- Data pipeline and system integration development
- Broader data support work such as business insight generation or customer segmentation
- Capability growth in:
  - Data extraction, processing, and integration development
  - Logical data structuring
  - Generative AI technology and architecture understanding
  - Technical communication

## Entry template

### YYYY-MM-DD - Topic
- Summary:
- What was done:
- Competency mapping:
- Skill sharpened next:

## Entries

### 2026-03-09 - Career competency tracking setup
- Summary: Defined a selective logging rule so only materially relevant conversations are captured against target data/AI job competencies.
- What was done: Added repository-level instructions to append relevant work summaries and initialized this tracking file with a stable format.
- Competency mapping: Logical data structuring, technical communication
- Skill sharpened next: Keep translating concrete tasks into capability language without overstating relevance.

### 2026-03-10 - Quant futures profile refinement
- Summary: Refined a live crypto strategy profile to increase qualified futures entries while preserving hard structural risk blocks and evidence-based exposure control.
- What was done: Mapped current gating and sizing logic against crawled strategy notes, introduced a config-backed futures exposure layer for reduced-size soft entries and stronger-setup scaling, validated with targeted unit and replay/config tests, and documented the behavioral evidence.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Tighten the link between regime evidence, exposure budgeting, and live execution-state accounting.

### 2026-03-11 - Futures activity bottleneck tuning
- Summary: Analyzed live paper-trading decision logs to identify why futures candidates kept collapsing back to cash/spot, then tightened the active profile toward smaller but more frequent futures entries.
- What was done: Counted dominant futures rejection reasons from recent runtime logs, converted selected soft futures blockers into reduced-size entry behavior, raised the active futures slot limit, pinned the paper-live launcher to the active profile, and verified the revised behavior with focused unit tests.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Improve log-to-strategy feedback loops so live rejection patterns translate into targeted profile changes faster.

### 2026-03-11 - Live decision-loop stall fix
- Summary: Debugged a live quant runtime stall where post-bootstrap heartbeats continued but no new decisions were emitted.
- What was done: Traced the daemon/runtime/session path, matched live event logs against Binance closed-kline timestamp semantics, fixed the live trigger to normalize real closed-candle boundaries and restrict decisions to the configured decision interval stream, then verified with focused runtime/session/order tests.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Build stronger exchange-payload realism into test fixtures so live/runtime boundary bugs surface before deployment.

### 2026-03-11 - Live decision-loop verification and observability
- Summary: Verified that post-bootstrap closed `5m` candles are continuing to produce live decisions on current `HEAD`, then added state-level counters so future runtime artifacts show exactly where any closed-candle drops occur.
- What was done: Compared older and current paper-live-shell artifacts, confirmed the latest run advanced from bootstrap-only decisions to additional `00:30` and `00:35` live decisions, added `live_decision_loop` counters/drop reasons to runtime state, and added regression coverage for bootstrap-to-live continuation plus closed-kline accounting.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Add low-noise production telemetry that separates transport-level event arrival from strategy-level gating in long-running live systems.

### 2026-03-11 - Down-market futures short activation and leverage tuning
- Summary: Reworked the live Binance futures decision path so strong bearish setups can survive cautionary market states, size through leverage more intelligently on small balances, and still respect liquidity and instability guardrails.
- What was done: Traced the current short-activation bottlenecks across regime gating, fallback futures scoring, sizing, leverage selection, live-order execution, and session-level capital capping; added a bearish caution override for structurally strong shorts, replaced long-only futures flow bias with directional flow alignment, made futures sizing and cash-reserve checks leverage-aware, raised only the active profile leverage targets, and verified the path with focused bearish/leverage unit tests.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Add direct session-cap tests so leverage selection and executable notional caps stay aligned as the live risk model evolves.

### 2026-03-11 - Live order runtime execution unblock attempt
- Summary: Attempted end-to-end live order execution and converted multiple runtime crashes into explicit, actionable blockers.
- What was done: Ran `live-auto-trade-daemon` with Bitget env, fixed runtime/daemon `exchange` argument mismatch, synced settings schema with current config fields, added missing housekeeping module, and re-ran to isolate final blockers (`bitget` daemon unsupported, `binance` requires BINANCE_API_KEY/SECRET).
- Competency mapping: Data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Close exchange-specific runtime gaps by separating exchange-agnostic daemon flow from exchange adapters/credential paths.

### 2026-03-11 - Aggressive alt-futures profile rollout on Bitget runtime
- Summary: Expanded live trading scope from majors to a broader altcoin universe and loosened entry conditions while preserving existing risk management structure.
- What was done: Added `aggressive_alt` strategy profile in config, enabled it via `.env.bitget`, expanded universe to nine symbols, restarted live daemon, and verified increased futures/alt decision flow from runtime logs.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Align exchange-specific order semantics (position mode and side schema) with live execution adapters to convert accepted decisions into filled orders.

### 2026-03-11 - Ultra-scalp profile addition for adaptive execution
- Summary: Added and validated a dedicated ultra-short-horizon strategy profile so runtime behavior can be switched by market state without code changes.
- What was done: Introduced `scalp_ultra` profile parameters (1-minute decision cadence, shorter edge/holding horizons, higher leverage envelope, relaxed entry and priority-symbol futures settings), verified settings loading with `STRATEGY_PROFILE=scalp_ultra`, and documented profile switching in operations docs.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Add objective market-state triggers to automate profile switching instead of relying on manual environment toggles.

### 2026-03-11 - Live auto profile switching between swing and scalp modes
- Summary: Implemented runtime profile auto-switching so the live engine can move between calm and fast strategies without manual restarts.
- What was done: Added explicit profile loading API, introduced an `AutoProfileSwitcher` with hysteresis/min-hold controls, wired dynamic settings reload into the live daemon/session (including leverage adapter updates and symbol eligibility refresh), added unit tests for switch behavior, enabled switch env vars in `.env.bitget`, and relaunched the Bitget live daemon with switcher activation verified in logs.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Replace static thresholds with data-driven regime classifiers to reduce manual tuning and profile thrash risk.

### 2026-03-11 - Profile switch threshold tuning from live fill pattern
- Summary: Tuned auto-switch thresholds using recent live decision/fill artifacts so fast-mode activation aligns better with observed executable conditions.
- What was done: Aggregated latest `paper-live-shell` decision and live-order logs, measured accepted-order volatility range against overall distribution, lowered return-based trigger scale to match actual 1h return magnitudes, tightened volatility hysteresis around fill-zone levels, reduced min-hold cycles for faster adaptation, fixed switch-cycle accounting so hold budgets are consumed per decision interval (not per symbol), updated `.env.bitget`, and restarted the live Bitget daemon.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Add persistent switch-event telemetry to evaluate threshold precision and avoid overfitting on small fill samples.

### 2026-03-11 - Risk-on profile rollout with soft-risk futures override
- Summary: Shifted the runtime from conservative entry suppression to a risk-on profile while preserving hard risk blocks.
- What was done: Added `alpha_max` strategy profile, changed live calm profile to `alpha_max`, implemented soft-risk-only futures override logic (retain hard blockers like direction/macro/structural alt risk), added targeted unit tests for override behavior, validated profile loading, compared same-snapshot mode outcomes (`aggressive_alt` vs `alpha_max`), and relaunched live runtime to confirm futures route activation.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Build automatic size backoff/retry on exchange balance-limit rejects so aggressive profiles keep execution continuity.

### 2026-03-11 - Bitget live fill recovery via margin-aware execution fallback
- Summary: Converted live futures rejection loops into executable orders by hardening the Bitget order path against leverage/balance mismatches.
- What was done: Added balance-aware futures notional capping in the live order adapter, handled Bitget leverage-update margin errors (`40893`) with conservative fallback sizing, implemented repeated size backoff for balance rejects (`40762`) in the Bitget REST client, added regression tests, and validated in live logs with accepted futures orders.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Add symbol-level minimum-order-aware fallback so backoff can converge directly to exchange-valid minimum quantities without terminal rejects.

### 2026-03-12 - Bitget futures live-order validation hardening
- Summary: Reduced repeated Bitget futures execution failures by aligning live sizing with crossed-margin openable balance semantics and tightening retry/cooldown behavior for invalid orders.
- What was done: Updated Bitget account parsing to treat `crossedMaxAvailable` as authoritative for crossed-mode openable balance, propagated effective balance into live sizing, prevented zero-available fallback from sending full-size orders, strengthened per-symbol notional downscaling after balance errors, expanded cooldown/fingerprint suppression to `45110`, and validated with focused unit tests plus short live daemon reruns.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Add exchange-account-state-aware symbol selection so futures intents automatically avoid symbols blocked by per-market minimums and openable-margin constraints.
