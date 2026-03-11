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
3. On each completed `5m` decision boundary, calculate `predictability_score` and directional state.
4. Select `futures`, `spot`, or `cash`.
5. Apply sizing and portfolio risk checks.
6. Submit or skip orders.
7. Reconcile broker state and persist decision logs.

## Run Modes

- `replay`: run frozen snapshot fixtures through the deterministic strategy path
- `paper-live`: run paper cycles from prebuilt fixture objects
- `paper-live-test-order`: generate decisions and validate them against Binance `order/test`
- `paper-live-shell`: run the event-driven paper shell with reconnect/backoff and periodic flush
- `env-check`: verify required Binance API environment variables are present

## Output Convention

Runtime summaries and state files should be written under:

```text
output/<mode>/<run-id>/
  summary.json
  summary.state.json
```

`quant_binance.paths.prepare_run_paths()` creates this structure automatically.

## Smoke Examples

```bash
python3 -m quant_binance.runtime --mode env-check
python3 -m quant_binance.runtime --mode replay --fixture tests/replay_fixture.json --output output/replay/latest/summary.json
python3 -m quant_binance.runtime --mode paper-live-shell --fixture tests/paper_live_fixture.json --output output/paper-live-shell/latest/summary.json
```

Single-user helper scripts:

```bash
sh scripts/quant_env_check.sh
sh scripts/quant_replay.sh tests/replay_fixture.json
sh scripts/quant_paper_live_shell.sh tests/paper_live_fixture.json
sh scripts/quant_test_order.sh tests/paper_live_fixture.json
sh scripts/quant_run_forever.sh quant_runtime
sh scripts/quant_run_live_orders.sh quant_runtime
```

See [OPERATIONS.md](/Users/tttksj/first_repo/quant_binance/OPERATIONS.md) for the recommended local workflow.
See [STRATEGY_REFINEMENT_FROM_NAVER.md](/Users/tttksj/first_repo/quant_binance/STRATEGY_REFINEMENT_FROM_NAVER.md) for rules extracted from crawled premium content and how they should influence the system.
See [ALTCOIN_INTELLIGENCE.md](/Users/tttksj/first_repo/quant_binance/ALTCOIN_INTELLIGENCE.md) for the external altcoin-intelligence mapping.

For local single-user usage, `quant_binance.env` checks shell environment first and then repository-root `.env` / `.env.local`.
If `STRATEGY_PROFILE` is set (for example `aggressive_alt`, `alpha_max`, or `scalp_ultra`), that profile is deep-merged on top of the base config before runtime starts.
If `AUTO_STRATEGY_SWITCH=1`, runtime can auto-switch between a calm and a fast profile (`AUTO_STRATEGY_CALM_PROFILE`, `AUTO_STRATEGY_FAST_PROFILE`) using volatility/return hysteresis gates.
If `UNIVERSE_SYMBOLS` is set, it overrides the configured local trading universe.
The Naver extraction helper saves markdown, screenshot, and downloaded article-body images when available.
If `MACRO_INPUTS_PATH` or `MACRO_INPUTS_JSON` is set, macro regime inputs are loaded and applied before regime selection.
If `ALTCOIN_INPUTS_PATH` or `ALTCOIN_INPUTS_JSON` is set, altcoin intelligence inputs are loaded for non-BTC/ETH symbols before final scoring and regime selection.

## Required Design Rules

- Strategy logic must be shared across backtest, paper, and live modes.
- Exchange adapters may differ by mode, but decision logic may not.
- Every skipped trade must log a reason code.
- Every live order must be linked to the feature snapshot that produced it.
- Futures execution must be impossible if a hard gate fails.
- Every strategy call must consume the same immutable snapshot schema regardless of mode.
- Config changes must be versioned so decision replay can reproduce prior trades exactly.
- Backtest, paper, and live-sim entrypoints must emit the same decision payload and `decision_hash` for the same frozen snapshot input.

## Implementation Order

1. Settings and config loading
2. Market data adapters
3. Feature calculations
4. Regime scorer
5. Risk checks
6. Paper broker adapter
7. Replay/backtest harness
8. Live execution adapter
