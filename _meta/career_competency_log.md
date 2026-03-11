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
