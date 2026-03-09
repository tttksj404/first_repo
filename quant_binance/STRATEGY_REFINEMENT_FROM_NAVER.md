# Strategy Refinement From Naver Crawl

## Scope

This note summarizes what can be extracted from the crawled Naver premium content and how it should influence the trading system.

The goal is not to copy discretionary commentary verbatim. The goal is to extract only repeatable, quantifiable rules.

## Source Pages Used

Primary pages judged useful:

- [07-premium-contents](/Users/tttksj/first_repo/quant_runtime/artifacts/openclaw_naver_strategy_crawl/pages/07-premium-contents/content.md)
- [08-premium-contents](/Users/tttksj/first_repo/quant_runtime/artifacts/openclaw_naver_strategy_crawl/pages/08-premium-contents/content.md)
- [12-premium-contents](/Users/tttksj/first_repo/quant_runtime/artifacts/openclaw_naver_strategy_crawl/pages/12-premium-contents/content.md)
- [13-premium-contents](/Users/tttksj/first_repo/quant_runtime/artifacts/openclaw_naver_strategy_crawl/pages/13-premium-contents/content.md)
- [15-premium-contents](/Users/tttksj/first_repo/quant_runtime/artifacts/openclaw_naver_strategy_crawl/pages/15-premium-contents/content.md)
- [22-premium-contents](/Users/tttksj/first_repo/quant_runtime/artifacts/openclaw_naver_strategy_crawl/pages/22-premium-contents/content.md)
- [23-premium-contents](/Users/tttksj/first_repo/quant_runtime/artifacts/openclaw_naver_strategy_crawl/pages/23-premium-contents/content.md)

Useful themes extracted:

- long-horizon BTC regime assessment
- support/resistance-aware spot accumulation
- sentiment-state interpretation
- macro liquidity filter
- valuation overlay using network security / hash-rate framing

## Adopt

These ideas are worth adopting into the system.

### 1. Cash Reserve Rule

Observed rule:

- keep at least `30%` cash in uncertain macro periods
- do not fully deploy into risk assets

Why it is useful:

- this is simple
- risk reducing
- explainable
- robust across regimes

Recommended quant implementation:

- `macro_risk_high -> min_cash_reserve_fraction = 0.30`
- `macro_risk_normal -> min_cash_reserve_fraction = 0.15`
- execution must refuse new spot/futures entries that breach reserve

### 2. Support-Only Spot DCA

Observed rule:

- accumulate on support
- avoid buying directly into resistance
- examples mentioned: `20d EMA`, trendline support, `Fibonacci 0.5`

Why it is useful:

- this is more precise than naive periodic DCA
- aligns with current system's preference for explainable entries

Recommended quant implementation:

- only allow spot DCA when price is within a defined band of:
  - `20 EMA`
  - local trendline support approximation
  - recent swing retracement `0.5` to `0.618`
- disallow spot adds when price is within a defined band of:
  - `50 EMA` resistance
  - prior local high / channel top

### 3. Macro Liquidity Filter

Observed rule:

- watch `10Y yield`, `oil`, labor weakness, inflation pressure
- liquidity matters more than narrative
- risk assets should be sized down when macro pressure rises

Why it is useful:

- this is consistent with the current regime-switching architecture
- it explains why to stay in `cash` even when local price action looks attractive

Recommended quant implementation:

- create a macro regime:
  - `macro_risk_high`
  - `macro_neutral`
  - `macro_liquidity_supportive`
- macro regime affects:
  - futures eligibility
  - spot DCA intensity
  - cash reserve floor

### 4. Sentiment-State Overlay

Observed rule:

- interpret combinations of futures/spot flow or custom sentiment indicators as:
  - rising risk-on
  - bottom formation
  - bearish transition

Why it is useful:

- it fits naturally as a regime overlay, not as a standalone trigger

Recommended quant implementation:

- use sentiment only as:
  - mode downgrade / upgrade filter
  - size multiplier
- do not let sentiment alone open a position

### 5. Valuation Overlay

Observed rule:

- `Bitcoin Yardstick` style framing
- compare market value to hash-rate / security strength

Why it is useful:

- better suited to medium / long-horizon bias than short-term trade timing

Recommended quant implementation:

- valuation overlay should only affect:
  - long-term BTC bias
  - willingness to hold spot
  - willingness to add on weakness
- it should not trigger short-term intraday entries by itself

## Reject

These ideas should not be copied directly.

### 1. Fixed Price Targets

Examples:

- `99k~105k` take-profit zone
- `70k` buy zone

Reason to reject:

- temporally unstable
- tied to one historical context
- not robust enough as a permanent system rule

### 2. Pure Narrative Probability Calls

Examples:

- scenario probabilities stated without formal estimator

Reason to reject:

- subjective
- hard to backtest
- easy to overfit in hindsight

### 3. Manual “Feel” Adjustments

Examples:

- comments like "this feels like the right time"
- “this time is different” caution without a measurable filter

Reason to reject:

- not reproducible
- not appropriate for autonomous execution

## Hold

These are useful ideas but should be added only after more data plumbing exists.

### 1. External Macro Data

- 10Y yield
- oil
- Truflation
- TGA
- Fed balance sheet
- MMF

Current status:

- not yet wired into the codebase

### 2. Custom Sentiment Indicator

Current status:

- article describes cases
- raw data source and exact formula are not yet present

### 3. Hash-Rate Valuation Overlay

Current status:

- concept is useful
- on-chain / valuation data source not yet wired

## Recommended Next Changes

### High Priority

1. Add `cash_reserve_fraction` logic to live execution.
2. Add support/resistance-aware spot DCA filter.
3. Split spot and futures sizing/risk budgets more explicitly.
4. Add macro filter interface, even if initially stubbed.

### Medium Priority

1. Add external macro collector jobs.
2. Add valuation overlay for BTC long-bias only.
3. Add article-derived sentiment regime once raw source is formalized.

## Bottom Line

The crawled material is useful.

It is not useful because it provides exact reusable price targets.
It is useful because it reinforces a better structure:

- preserve cash
- buy support, not resistance
- respect macro liquidity
- treat sentiment as an overlay
- treat valuation as long-horizon bias, not short-term signal

That structure can improve the current system if converted into measurable filters.
