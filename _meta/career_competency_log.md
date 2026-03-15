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

### 2026-03-15 - Natural-language routing for local skill and repo selection
- Summary: Added a lightweight routing layer that maps Telegram/OpenClaw-style requests to the right local skill set, reference repo, and execution path.
- What was done: Inspected the current `.agents/skills` and `04. Tools/agent-stack` assets, created a markdown routing registry for seven practical intent classes, implemented a small CLI router that resolves skill paths plus repo metadata from the local manifest, documented usage in the agent-stack README, and verified the classifier with a minimal multi-intent self-check.
- Competency mapping: Data pipeline/system integration development, logical data structuring, generative AI architecture understanding, technical communication
- Skill sharpened next: Improve lightweight intent routing so new operational request patterns can be added without losing inspectability or overcomplicating the execution path.

### 2026-03-15 - Agent reference stack for Codex/OpenClaw
- Summary: Turned a loose set of agent/orchestration links into a local reference stack that can be queried directly from Codex and partially installed into OpenClaw.
- What was done: Created a tracked manifest of selected GitHub/web resources, added sync and Codex-launcher scripts, cloned the target repos into a stable local workspace, documented direct usage patterns, and validated Codex execution against a synced repo while starting OpenClaw installation for agency-agents.
- Competency mapping: Data pipeline/system integration development, generative AI architecture understanding, logical data structuring, technical communication
- Skill sharpened next: Tighten repeatable local-to-agent integration flows so external reference repos can become reusable internal tools faster.

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

### 2026-03-11 - Binance-to-Bitget exchange migration scaffold
- Summary: Started the exchange migration of the quant runtime from Binance to Bitget with a Bitget-first env and REST execution layer while keeping the highest-risk websocket/live-daemon gap explicit.
- What was done: Mapped Binance-specific integration points, added generic exchange/env resolution, implemented Bitget REST signing and request builders, rewired runtime/scripts to default to Bitget, converted order-test flow into Bitget payload preview without live credentials, and verified the migration slice with focused adapter/runtime tests.
- Competency mapping: Data pipeline/system integration development, logical data structuring, generative AI architecture understanding, technical communication
- Skill sharpened next: Finish exchange-normalized public websocket ingestion so the live daemon can move off Binance safely.

### 2026-03-12 - Bitget live-daemon websocket activation
- Summary: Finished the missing public-market-data layer that had been blocking the Bitget live daemon from starting and consuming exchange-native websocket payloads.
- What was done: Added a Bitget public websocket adapter that normalizes trade, ticker, mark-price, open-interest, and candle payloads into the runtime's existing live event contract; rewired the daemon to select Bitget websocket clients instead of hard-failing; allowed paper Bitget daemon startup without private credentials while still requiring env-backed credentials for live-order mode; and verified the slice with focused websocket and daemon tests.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Add exchange-realistic live capture fixtures so websocket translation stays correct as Bitget channel schemas evolve.

### 2026-03-12 - Bitget unilateral futures order contract fix
- Summary: Resolved the remaining Bitget live futures order-format mismatch by aligning the runtime with Bitget's one-way position-mode order contract.
- What was done: Traced the live daemon's order payload builders, confirmed from Bitget contract docs that one-way mode requires `side=buy|sell` with close intent carried by `reduceOnly`, removed the hedge-mode `open_long/open_short` mapping from the REST builder, added focused unilateral-mode payload assertions for both live adapter and REST builder paths, and verified the slice with targeted daemon and live-order tests.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Add a safe exchange-backed smoke probe that validates signed private-order payloads against the live venue without sending executable size.

### 2026-03-12 - Bitget crossed-balance execution cap fix
- Summary: Tightened the live Bitget futures execution path so order sizing respects the exchange's crossed executable balance instead of a broader account-available figure.
- What was done: Traced the session/live-order capital cap path, exposed Bitget `crossedMaxAvailable` as an execution-safe balance signal, wired daemon capital reporting and session capping to that executable balance, added focused session and Bitget migration regression tests, and verified the change with targeted unit tests plus a direct payload check against a recent failing live snapshot.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Add exchange-backed rejection-code fixtures so live balance semantics stay correct across venue/account-mode changes.

### 2026-03-12 - Capital adequacy recognized-balance regression coverage
- Summary: Added targeted regression coverage for recognized-asset adequacy versus execution-safe order caps across the live daemon and session paths.
- What was done: Verified that non-USDT spot assets are recognized conservatively via spot bid prices in daemon capital reporting, confirmed futures adequacy can rely on larger account equity fields while execution stays pinned to the smaller executable balance, tightened the spot execution-cap expectation so recognized assets do not bypass USDT execution limits, and ran the focused capital/execution test slice.
- Competency mapping: Data pipeline/system integration development, logical data structuring, data analysis and planning, technical communication
- Skill sharpened next: Add fixture coverage for unsupported spot assets and missing book prices so recognized-balance fallbacks stay conservative under partial market data.

### 2026-03-12 - Recognized asset valuation for adequacy and execution caps
- Summary: Extended the trading capital path so spot coin balances and futures equity fields contribute to adequacy checks without loosening execution-safe caps.
- What was done: Added normalized capital-input extraction for spot/futures snapshots, valued non-USDT spot assets conservatively from spot `*USDT` bid prices, promoted account-provided futures equity fields into adequacy checks while preserving USDT/executable-balance limits for actual order caps, and verified the slice with focused capital, daemon, session, and Bitget migration tests.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Add venue-specific collateral-transfer fixtures to distinguish recognized gross assets from immediately deployable margin across more account modes.

### 2026-03-12 - Bitget paper daemon runtime activation check
- Summary: Brought up the Bitget paper daemon against the live exchange endpoints and confirmed the runtime can seed market state, open websockets, and persist decision logs without submitting live orders.
- What was done: Verified Bitget credential readiness from the repo env path, launched the `live-paper-daemon` flow with network access, confirmed fresh runtime output under `quant_runtime/output/paper-live-shell/20260312-110339`, and inspected decision/event/test-order logs to verify ongoing market ingestion with zero live orders.
- Competency mapping: Data pipeline/system integration development, data analysis and planning, logical data structuring, technical communication
- Skill sharpened next: Add a lightweight runtime health probe so persisted `summary.state.json` stays in sync with the live daemon heartbeat stream.

### 2026-03-12 - Paper runtime profit-protection exit state machine
- Summary: Added paper-position state tracking so the live paper runtime can lock in gains instead of endlessly reissuing entry intents while profitable trades remain open.
- What was done: Introduced session-level paper position tracking with partial take-profit handling, post-TP stop protection, max-holding and signal/score/liquidity deterioration exits, suppressed duplicate order previews while a position is already open, surfaced open positions and closed trades in runtime summaries/state, and verified the behavior with focused session/runtime tests.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Extend the same exit-state contract to exchange-backed reduce-only exit orders so paper and live execution semantics stay aligned.

### 2026-03-13 - Conservative futures capital reallocation layer
- Summary: Added a runtime-only, conservative capital reallocation path that can replace one weak futures position when a much stronger new futures setup is otherwise blocked by slot or execution constraints.
- What was done: Extended session-level paper position metadata with entry/latest edge and leverage context, added a portfolio-focus-gated reallocation helper that ranks the weakest current futures position, requires strict score and post-switch net-edge advantages, applies a two-candle cooldown after replacement, and verified the behavior with focused session plus live-order/capital regression tests.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Add fresh live-position normalization so runtime-side replacement decisions can cross-check paper weakness against exchange-truth exposure without stale-state drift.

### 2026-03-13 - Conservative bounded multi-position futures reallocation
- Summary: Extended conservative futures capital reallocation from single-position replacement to a bounded weakest-first multi-replacement flow.
- What was done: Refactored the session reallocation path to rank weak futures positions, unlock slot and execution capacity only via the weakest-first prefix, cap replacements at two positions, aggregate switching costs conservatively across all replaced positions, reject the whole action if strict score/edge/incremental-pnl thresholds fail after aggregation, and verified the slice with focused session regressions for preserved single replacement, strict multi replacement, aggregated-threshold rejection, replacement-cap rejection, and cooldown continuity.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Add replay-backed calibration for the weakest-first selection thresholds so bounded replacement remains conservative under higher-position-count futures portfolios.

### 2026-03-15 - Loss-combo auto downgrade for live trading
- Summary: Added session-level risk suppression that automatically downgrades repeated losing symbol/direction/time-slot combinations before they can re-enter.
- What was done: Introduced config-backed combo loss thresholds, tagged closed trades with symbol-side-time-bucket keys, accumulated recent realized losses while excluding partial exits, applied combo-scoped prune/observe-only/cooldown rewrites before decision logging and paper/live entry handling, and verified the slice with focused plus full session regression tests.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Add runtime artifact views for active combo cooldowns so live risk state is easier to inspect without reading raw trade history.

### 2026-03-14 - Runtime failure alerting through OpenClaw Telegram fallback
- Summary: Hardened the live trading runtime so crashes, unhealthy restarts, and stop events can notify the operator through the same Telegram path used by OpenClaw.
- What was done: Extended Telegram notification resolution to fall back to OpenClaw `allowFrom` credentials when repo env allowlists are missing, enriched runtime alert payloads with health reasons, exit codes, and latest order-error context, added duplicate-alert suppression, updated the live supervisor script to emit start/unhealthy/exit/stopped alerts, verified with focused unit tests, and confirmed an end-to-end Telegram test message reached the configured private chat.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Keep closing the gap between runtime observability and operator actionability by turning repeated failure signatures into structured recovery recommendations.

### 2026-03-14 - Unrealized PnL-based live profit protection refinement
- Summary: Improved live futures exit logic so profit-taking reflects actual unrealized dollars and portfolio-level locked-in gains, not only ROE percentages.
- What was done: Added position-level unrealized PnL trailing exits and portfolio-level unrealized profit lock thresholds to the live position risk config, integrated them into session evaluation without removing the existing ROE protections, validated the new behavior with focused session regressions, and restarted the live trading runtime on the updated logic.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Calibrate account-level profit protection against longer live samples so portfolio locks preserve gains without cutting strong trends too early.

### 2026-03-14 - Performance-driven symbol pruning and stronger futures sizing
- Summary: Shifted the strategy toward better expected profitability by tightening weak futures sizing and wiring performance-report findings into approved runtime overrides.
- What was done: Increased the gap between weak and strong futures sizing in the `live-ultra-aggressive` profile, changed strong setup sizing from a flat bump to a signal-strength-proportional multiplier, extended strategy proposal generation so pruning/demotion recommendations can become runtime overrides, validated the updated proposal/profile behavior with focused tests, and restarted the live runtime on the revised configuration.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Convert sparse live-trade evidence into more stable pruning thresholds so the auto-pruning layer becomes selective without overreacting to small samples.

### 2026-03-14 - Weekly validation reporting for strategy evidence
- Summary: Added a weekly validation layer so strategy changes can be judged with a consistent report and explicit prune/keep/promote criteria instead of ad hoc interpretation.
- What was done: Implemented a weekly validation report builder and CLI, aggregated recent run-level realized PnL, trade counts, regime summaries, and symbol summaries, embedded an operational criteria table for prune/observe-only/keep/promote decisions, added regression coverage, and wired the validation report into the auto-research cycle.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Enrich weekly validation with longer lookback expectancy and rejection-pressure trends so operational thresholds become more statistically reliable.

### 2026-03-14 - Single-file runtime overview and faster flush path
- Summary: Simplified runtime observability so the live bot’s current state can be checked from one compact file instead of chasing multiple summary artifacts.
- What was done: Added `overview.json` generation alongside existing summary/state files, reduced flush cadence for the live session path, updated the status script to prefer the compact overview file, verified overview serialization and runtime/session behavior with focused tests, and restarted the live runtime so the new overview path is active.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Keep collapsing noisy operational state into concise views without losing the evidence needed for debugging and trading decisions.

### 2026-03-14 - Major-priority reallocation and winner pyramiding for futures
- Summary: Added a safer capital concentration layer so strong major futures signals can displace weaker non-major positions more easily, and winning major positions can add once instead of stalling at the initial size.
- What was done: Extended futures exposure settings with major-symbol reallocation relaxations and controlled pyramid parameters, implemented major-aware reallocation target prioritization and threshold relaxation, added same-symbol winner pyramiding for profitable futures positions with capped add counts and reduced add sizing, verified the new behavior with focused session and profile tests, and restarted the live runtime on the updated logic.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Measure whether concentrated major exposure improves realized expectancy without increasing churn or drawdown too much.

### 2026-03-14 - Live decision-stall hardening for Bitget runtime
- Summary: Hardened the live Bitget trading daemon against decision-generation stalls by removing websocket subscription overload, correcting liveness timing semantics, and adding a wall-clock decision fallback that no longer depends solely on closed-candle websocket delivery.
- What was done: Identified that Bitget live connections were exceeding recommended channel density and receiving unstable subsets of 5m candle streams, sharded Bitget websocket subscriptions into smaller per-connection/per-message batches, changed self-healing to track decision emission time in wall-clock time instead of stale market-bar timestamps, lowered recommended stall timeout for faster recovery, added a session-level scheduled decision boundary fallback so heartbeats alone can still advance decisions across 5-minute boundaries, and verified the behavior with focused websocket/daemon/session/self-healing regression tests.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Add exchange-capture fixtures or a long-run smoke harness that proves boundary-fallback decisions continue across multiple real Bitget live intervals without manual observation.

### 2026-03-14 - Live responsiveness and futures slot-policy tuning
- Summary: Improved reaction speed without changing the core strategy shape, then removed a live futures slot-policy bottleneck that was blocking otherwise valid futures candidates from reaching the order path.
- What was done: Added 1m/5m intraday bias as a lightweight assist to the existing 1h/4h trend engine, cached macro and altcoin input loads to avoid per-cycle file churn, extended live seeding/subscriptions to include 1m bars, verified the changes with focused exchange/input/data/session/profile tests, then confirmed from live runtime artifacts that futures candidates were still being rejected by slot policy and relaxed the ultra-aggressive futures slot ceiling to match the intended live profile.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Distinguish bootstrap-only candidate generation from actual post-boundary executable orders in runtime reporting so live verification is faster and less ambiguous.

### 2026-03-14 - Strategy trustworthiness reporting layer
- Summary: Added a lightweight reporting layer that turns live runtime artifacts into symbol-level expectancy, regime-level performance, and walk-forward style evidence for strategy review.
- What was done: Implemented reusable performance report builders over closed-trade and decision logs, added a CLI to emit per-run strategy evidence, included symbol pruning suggestions and walk-forward windows, validated with focused report tests, and generated a real report from the latest runtime artifacts for objective strategy review.
- Competency mapping: Data analysis and optimization, logical data structuring, data pipeline/system integration development, technical communication
- Skill sharpened next: Add promotion rules that consume the new expectancy and walk-forward outputs before approving future live strategy overrides.

### 2026-03-13 - Futures reallocation observability and exchange-synced exception gating
- Summary: Made futures reallocation decisions auditable and introduced a narrowly gated path for replacing clearly weak exchange-synced futures positions.
- What was done: Added compact skip/execute logging for blocked futures reallocation attempts with candidate strength, protected-target reasons, cooldown context, and switching-cost metrics; relaxed the blanket exchange-synced exclusion into an age-plus-loss exceptional gate layered on top of the existing score, edge, switching-cost, cooldown, and replacement-cap checks; and verified the behavior with focused session regressions for skip visibility, ordinary synced protection, strict synced replacement, and neighboring reallocation flows.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Turn reallocation audit logs into replay summaries so live skip patterns can be calibrated against realized replacement quality.

### 2026-03-13 - Conservative futures profit-protection retrace exits
- Summary: Added a conservative futures-only profit-protection layer so live and paper positions can trim earlier when meaningful ROE gains start to retrace.
- What was done: Extended session trade state with peak ROE tracking, added an additive futures retrace guard that arms after meaningful ROE, trims half on a conservative giveback while preserving the existing direct partial-take-profit and stop logic, mirrored the behavior across exchange-backed live positions and paper positions, and verified it with focused session plus live-order regression tests for trigger and no-noise cases.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Replay the new ROE-retrace thresholds across recent futures runs to calibrate how often the protection trims profitable trends too early versus meaningfully reducing giveback.

### 2026-03-13 - Bitget live futures runtime stabilization
- Summary: Hardened Bitget live futures order submission and made paper/exchange futures reconciliation converge more conservatively under noisy exchange snapshots.
- What was done: Tightened unilateral-mode fallback detection so only position-mode errors trigger alternate payload retries, expanded the retry sequence across one-way-compatible Bitget futures payload variants, removed immediate paper cleanup on a single missing live snapshot, required a longer confirmed exchange absence before deleting paper futures positions, and verified the path with focused Bitget migration, live-order, and session regression tests.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, generative AI architecture understanding, technical communication
- Skill sharpened next: Add replay-backed reconciliation telemetry so live snapshot churn can be measured per symbol and the conservative absence threshold can be tuned from evidence instead of static defaults.

### 2026-03-13 - Conservative self-healing ops layer for live quant runtime
- Summary: Added a bounded self-healing operations layer that classifies common runtime failures, applies only conservative recovery playbooks, and surfaces the result through the existing ops/report path.
- What was done: Implemented runtime issue classification for stalled daemon loops, persistent futures paper/exchange mismatches, and known Bitget live-order compatibility failures; wired safe recoveries into the existing session and shell flow via websocket restart budgeting, mismatch reconciliation reuse, and bounded live-order cooldown escalation; exposed self-healing state in runtime summary/state plus Telegram/report/status output; and verified the path with focused self-healing, session, ops, daemon, and Bitget regression tests.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, generative AI architecture understanding, technical communication
- Skill sharpened next: Add replay-backed measurements for stall windows and Bitget cooldown tripwires so conservative recovery thresholds can be tuned from observed runtime frequencies instead of fixed defaults.

### 2026-03-13 - Runtime self-healing propagation and restart-state recovery
- Summary: Stabilized live runtime reporting so self-healing state survives into ops surfaces and restart cycles no longer drop the paper futures shadow state.
- What was done: Tightened status/report artifact selection to prefer the canonical latest snapshot, replaced ambiguous missing self-healing prints with an explicit unavailable marker, persisted reconciliation counters in runtime state, added daemon startup hydration from the latest runtime snapshot to rebuild live-backed paper futures positions conservatively after restart, and verified the behavior with focused ops, session, daemon, and self-healing regression coverage.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, generative AI architecture understanding, technical communication
- Skill sharpened next: Extend the restart hydration path with replay-backed validation against stale snapshots so recovery stays conservative even after longer daemon downtime.

### 2026-03-13 - Live futures undercount root-cause tracing
- Summary: Traced why paper futures counts can remain below exchange live futures counts even after repeated restore and reconciliation events in the live runtime.
- What was done: Followed the end-to-end lifecycle from daemon startup restore through account sync, mismatch counters, reconciliation writes, flush persistence, and later paper-position management; correlated runtime artifacts with session code to prove reconciled placeholders were being closed again by normal paper exit logic; and narrowed the fix to a conservative guard around strategy exits for reconstructed live-only placeholders.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Add one replay-style regression that asserts reconciled live-only placeholders survive at least one flush cycle without being auto-closed by synthetic paper exit rules.

### 2026-03-13 - Missing market-state runtime self-healing classification
- Summary: Promoted the remaining live unknown-style `missing market state for symbol=...` fault into a known conservative self-healing category.
- What was done: Added a dedicated missing-market-state runtime classification, converted the market-store miss into a typed exception, caught that fault in the live session payload loop so the daemon skips the unsafe payload instead of crashing, exposed the affected symbols through self-healing reporting, and verified the behavior with focused classification, session, shell, live, and daemon regression tests.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, generative AI architecture understanding, technical communication
- Skill sharpened next: Add a lightweight runtime metric for how often symbol-state misses happen per stream so market-state seeding gaps can be prioritized from live evidence instead of anecdotal logs.

### 2026-03-13 - Strategy benchmark harness with baseline comparisons
- Summary: Added a conservative evaluation path to compare the live strategy against simple interpretable baselines on the same paper-live fixture.
- What was done: Reused the existing paper-session trade-management path to run the current strategy plus directional-hold, simple momentum, and simple mean-reversion baselines under identical equity/capacity settings; computed compact comparison metrics such as realized and mark-to-market PnL, return, drawdown, hit rate, turnover, and long/short counts; added a CLI and shell entrypoint; and verified the framework with focused comparison, runtime, and session tests.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, generative AI architecture understanding, technical communication
- Skill sharpened next: Add fixture curation and parameter-sweep automation so baseline sensitivity can be compared across multiple replay windows instead of a single scenario.

### 2026-03-13 - Recent local-data preparation for strategy baseline comparisons
- Summary: Extended the comparison harness so it can build a conservative recent-data benchmark from local runtime artifacts instead of only toy fixtures.
- What was done: Scanned timestamped paper-live runtime outputs for the best recent run with both decision traces and convertible local market history, reconstructed comparison-ready `PaperLiveCycle` fixtures from local 5m candle logs plus conservative synthetic microstructure fields, preserved richer optional state in the fixture loader, added a recent-data CLI/shell entrypoint that runs the comparison with the recorded current-strategy decision trace against the same reconstructed market slice, and verified the path with focused preparation/conversion and comparison regression tests plus a real recent-data run.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, generative AI architecture understanding, technical communication
- Skill sharpened next: Add denser live market-state capture so future recent-data comparisons can replace conservative spread/depth/funding approximations with higher-fidelity replay inputs.

### 2026-03-13 - Futures proactive ROE partial take-profit layering
- Summary: Added a conservative staged ROE-based take-profit layer for futures positions without removing the existing retrace-based profit protection.
- What was done: Extended exit-rule config and session state to track proactive ROE thresholds separately from legacy R-multiple and retrace partials, added conservative staged trims for paper and live futures positions while preventing same-threshold retriggers and same-tick multi-partial stacking, preserved retrace coexistence, and verified the behavior with focused session regressions plus a full session test-file run.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, generative AI architecture understanding, technical communication
- Skill sharpened next: Replay the 10% and 14% ROE stages across recent futures runs to measure whether the added early locking meaningfully reduces giveback without cutting strong trends too aggressively.

### 2026-03-13 - Live futures proactive partial take-profit path debugging
- Summary: Traced the live ROE-triggered futures partial take-profit path to a concrete Bitget close-order compatibility failure and added a conservative recovery path.
- What was done: Followed the live BTC futures path from ROE evaluation into `_close_live_position`, validated from runtime artifacts that the proactive branch fired and hit Bitget `22002` on the partial close, added scoped alternate-payload retries for Bitget proactive partial closes before classifying the attempt as already closed, and covered the live path with focused regressions for both one-way-mode compatibility errors and the observed `22002` failure mode.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Add exchange-response telemetry that distinguishes true already-closed races from payload-shape mismatches so live order fallbacks can be tuned from production evidence.

### 2026-03-13 - Bitget proactive partial-close position-mode compatibility fix
- Summary: Corrected the remaining Bitget live futures proactive partial-close incompatibility by aligning the close payload with the exchange position mode instead of assuming one-way semantics.
- What was done: Traced the proactive TP path from live ROE evaluation into the session close helper, separated Bitget hedge-mode closes (`tradeSide=close` with same-direction `side`) from one-way closes (`reduceOnly=YES` with opposite-direction `side`), kept a conservative fallback ladder plus safe `22002` handling, and verified the repo-side behavior with focused session and Bitget regression suites while documenting that sandbox DNS blocked fresh live exchange confirmation.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication, generative AI architecture understanding
- Skill sharpened next: Capture live Bitget request/response telemetry outside the sandbox so the remaining position-mode assumptions can be validated against real exchange snapshots instead of mocked retries alone.

### 2026-03-13 - Bitget market-state and websocket subscription mismatch tracing
- Summary: Traced the live Bitget daemon’s market-store seeding, runtime symbol filtering, and websocket subscription wiring to verify whether unknown-state symbols can still reach the runtime.
- What was done: Followed the daemon from REST seeding into `_stateful_runtime_symbols`, confirmed eligibility is computed only for already-seeded symbols, verified Bitget websocket subscriptions are built from that filtered runtime symbol set, and mapped the fallback self-healing path that skips unexpected payloads when market state is still missing.
- Competency mapping: Data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Add a direct regression around runtime-symbol filtering so subscription-state coupling stays explicit as exchange-universe wiring changes.

### 2026-03-13 - Live decision-loop runtime health repair
- Summary: Repaired the Bitget live daemon’s runtime symbol selection and websocket keepalive behavior to remove a repeated degraded-state trigger from the live decision loop.
- What was done: Filtered live websocket subscriptions down to symbols that were successfully seeded into market state, added a guard for empty seeded universes, switched Bitget websocket transport to watchdog-friendly keepalive settings that avoid library-side ping-timeout churn, and locked both behaviors with focused daemon and websocket regressions.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Validate the deployed daemon after restart with before/after runtime snapshots so recovery work is tied directly to live evidence instead of repo-only verification.

### 2026-03-13 - Live Bitget stop-loss close recovery for trading runtime
- Summary: Fixed the Bitget live futures close path so hedge-mode stop-loss exits use position-mode-aware payloads instead of the generic close builder that left losing live positions stuck open.
- What was done: Traced the live daemon from fresh runtime state and logs into the session close helper, confirmed XRP remained open while repeated `22002 No position to close` errors were logged, switched all Bitget live closes to reuse the existing position-mode candidate ladder, added full-close hedge-mode and `22002` retry regressions, and verified the broader session/runtime recovery suites locally while documenting that sandbox DNS blocked a real exchange restart.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Add live exchange replay or captured REST fixtures so daemon restart validation can be performed when external network access is unavailable.

### 2026-03-13 - Runtime startup failure visibility for live recovery
- Summary: Removed a false-healthy runtime state during daemon restart failures by persisting explicit startup-failure artifacts into the live `latest/` snapshot.
- What was done: Reproduced pre-flush daemon crashes on Bitget REST seeding, patched the daemon to write failed summary/state payloads before re-raising startup exceptions, verified status/report scripts now surface the exact blocker instead of stale health, and added a regression covering startup-failure persistence.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Capture real exchange connectivity diagnostics alongside runtime artifacts so external transport blockers can be distinguished immediately from in-process runtime defects.

### 2026-03-13 - Failed-start retention for live runtime recovery
- Summary: Preserved last-known-good runtime evidence during daemon startup failures by deferring housekeeping until after the first successful flush.
- What was done: Moved live runtime run-pruning to occur only after startup completes its initial flush, added a regression proving failed starts no longer delete previous run directories, and re-verified daemon/self-healing recovery coverage with focused `unittest` runs.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Validate the retained-run behavior against a real failed exchange start so operator tooling can compare the failed current run with the preserved prior healthy run side by side.

### 2026-03-14 - Heartbeat-only live decision stall recovery
- Summary: Fixed the live runtime so heartbeat traffic can no longer mask a stalled decision stream.
- What was done: Traced the split between payload heartbeats and decision emission, identified closed decision-interval kline filtering as the reason heartbeats kept advancing while decisions stayed flat, added separate decision-progress tracking to self-healing, covered the heartbeat-only stall path with focused regressions, and verified a controlled shell restart advances `decision_count` again after the stall.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Capture live exchange event traces per channel so future decision stalls can be tied to a specific upstream feed instead of inferred from aggregate heartbeat behavior.

### 2026-03-14 - Overnight live runtime operational recovery loop
- Summary: Reduced Bitget live-runtime order-path failures and restart instability, then narrowed the remaining blocker to abnormal post-bootstrap decision accumulation.
- What was done: Quantized Bitget protection trigger prices to exchange scale, refreshed account/capital state around live-order activity to reduce stale-balance rejects, added restart cutoffs for historical decision timestamps plus monitor-driven scheduled decision checks, validated the changes with focused runtime/order recovery and stall regressions, and used repeated live daemon restarts plus state/log observation to isolate the remaining non-normal decision-count growth after clean boundaries.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication, generative AI architecture understanding
- Skill sharpened next: Add live decision-boundary telemetry that records why each increment was emitted so abnormal post-bootstrap growth can be distinguished immediately from healthy real-time progression.

### 2026-03-14 - Live runtime transport blocker isolation
- Summary: Tightened live-runtime recovery evidence by turning opaque exchange transport failures into explicit DNS/target diagnostics and re-running the startup path to confirm the remaining blocker is environmental.
- What was done: Reproduced clean daemon restart failure after stopping the prior live process, confirmed outbound exchange host resolution fails from the current runtime environment, added REST transport error messages that include the target URL/host and DNS-resolution classification, covered the behavior with focused unittests, and re-ran the live daemon to verify the same external blocker remains with concrete evidence.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Add a preflight connectivity probe to the live-runtime operator workflow so external DNS/network blockers are surfaced before any restart displaces a healthy running daemon.

### 2026-03-14 - Bootstrap-to-live decision continuation fix
- Summary: Removed a bootstrap timestamp bug that could consume the first real live decision boundary and make post-restart decision generation look stalled.
- What was done: Traced the daemon path from seeded market state into `run_bootstrap_cycle`, changed bootstrap timing to use the latest seeded closed decision-interval kline instead of the next wall-clock boundary, clamped bootstrap state freshness to that boundary, added focused daemon regressions that reproduce the pre-fix duplicate-drop behavior and confirm the first live close is now retained, and attempted a real live restart before documenting the DNS block in this sandbox.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Persist per-symbol bootstrap/live handoff telemetry so future decision stalls can be proven from runtime state without reconstructing the boundary sequence from tests.

### 2026-03-14 - Live daemon stall-timing stabilization
- Summary: Stopped the live daemon from self-restarting before the first legitimate post-bootstrap decision boundary, then isolated the remaining restart blocker to exchange DNS/network access in the current environment.
- What was done: Reproduced heartbeats-without-decisions on the live runtime, patched self-healing to track decision progress against the later of emission time and decision boundary time, added a regression for future-dated bootstrap decisions, re-verified stall/recovery suites with focused `unittest` runs, confirmed the pre-existing live run advanced from `decision_count=9` to `34` at the `2026-03-14T00:30:00Z` boundary, and proved fresh restarts now fail only because `api.bitget.com` DNS resolution is blocked in this sandbox.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Add a restart preflight that checks exchange DNS/connectivity before replacing a healthy live daemon.

### 2026-03-14 - Major strong-entry notional floor
- Summary: Raised the minimum entry size specifically for strong major futures setups so high-conviction BTC/ETH/SOL signals no longer degrade into low-impact live orders.
- What was done: Added `major_strong_min_entry_notional_usd` to futures exposure settings, enforced it inside live order capping only for objectively strong major futures decisions, added focused session/profile regressions for both bump-up and reject cases, and restarted the live runtime to confirm the updated profile and major-only universe are active.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Compare post-change realized expectancy for strong major entries versus pre-change runs and tune the floor with live evidence instead of static thresholds.

### 2026-03-14 - Empirical live cost calibration
- Summary: Added a live cost-calibration path that turns recent Bitget fills into an empirical fee/slippage calibration artifact and feeds it back into feature scoring.
- What was done: Implemented a cost calibration module, persisted recent Bitget fill-derived fee estimates to `quant_runtime/artifacts/cost_calibration.json`, wired the daemon to refresh the artifact before runtime startup, added feature/scorer support for empirical fee and slippage overrides, extended live-order logs with order/reference metadata for future slippage learning, and verified the path with focused unit tests plus a healthy live restart.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, technical communication, generative AI architecture understanding
- Skill sharpened next: Backfill slippage samples by correlating new live order references with Bitget fill history so empirical slippage moves from zero-sample fallback to per-symbol estimates.

### 2026-03-14 - Bitget TPSL deduplication for live positions
- Summary: Stopped duplicate reserved exit plans from piling up on the same live futures position by reconciling old Bitget TPSL plans before continuing runtime management.
- What was done: Added Bitget pending-plan and cancel-plan API support, implemented per-symbol/per-side TPSL reconciliation in live position management, verified it with focused session and Bitget migration tests, and confirmed a real BTC futures plan set dropped from four live plans to one profit plus one loss plan after restart.
- Competency mapping: Data pipeline/system integration development, data analysis and optimization, logical data structuring, technical communication
- Skill sharpened next: Extend the same reconciliation to other plan families if the exchange starts returning extra trigger-order variants beyond profit/loss plan pairs.

### 2026-03-14 - Partial-exit simplification for live futures
- Summary: Reduced churn from overlapping partial-exit rules by introducing partial-exit cooldowns, single-mode protection behavior, and larger major-position partial sizes only in the live ultra-aggressive profile.
- What was done: Added live-position risk settings for partial-exit minimum interval and major partial-exit fraction, enforced mode-aware partial-exit gating in session management, kept the defaults neutral outside the live ultra-aggressive profile, and verified the behavior with focused session/profile regressions before restarting the live daemon.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Measure whether partial-exit count per 24h and per-symbol realized expectancy improve after the cooldown/mode gating is live for a full trading window.

### 2026-03-15 - Overnight futures loss/churn mitigation
- Summary: Tightened the runtime around the actual overnight loss patterns by making major-position exits less trigger-happy, adding longer post-loss cooldowns, and making mismatch cleanup more conservative for majors.
- What was done: Added major-specific reentry cooldown, stronger confirmation/min-holding requirements before reversal exits, longer cooldown after realized major losses, and a higher missing-on-exchange cleanup threshold for major symbols; re-ran targeted session/profile suites and restarted the live runtime with the updated profile.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Compare overnight realized PnL and close-count-by-reason after this change set to verify that the churn-heavy exit reasons materially decline.

### 2026-03-15 - Medium-tier major futures sizing
- Summary: Added a middle sizing tier for BTC/ETH/SOL so medium-strength major futures signals can be sized above baseline without being treated like the strongest setups.
- What was done: Introduced settings-driven medium-tier major sizing and cap-relaxation controls, wired the tier into live decision capping while preserving the existing strong-major path, adjusted profile expectations, and re-verified session/profile behavior with focused unittests before checking the live runtime state.
- Competency mapping: Data analysis and optimization, data pipeline/system integration development, logical data structuring, technical communication
- Skill sharpened next: Compare the number and expectancy of medium-tier major entries versus strong-tier entries to see whether the new middle tier improves capital efficiency without raising churn too much.

### 2026-03-15 - Natural-language routing and semi-auto dispatch for agent workflows
- Summary: Turned a loose set of skills and reference repos into a reusable routing layer so broad Telegram/OpenClaw requests can be mapped to the right skill, local reference, and Codex handoff path with less manual judgment each time.
- What was done: Added an intent registry, local router, semi-automatic dispatcher, reusable reference stack scripts, and then wired the repo guidance (`AGENTS.md`, `BOOTSTRAP.md`) to treat that dispatcher as the default heuristic for broad requests.
- Competency mapping: Data pipeline/system integration development, logical data structuring, generative AI architecture understanding, technical communication
- Skill sharpened next: Close the loop by capturing actual dispatch outcomes and using them to improve routing rules from real request history.
