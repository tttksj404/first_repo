# Single-User Operations

## Assumption

This setup is optimized for one local operator.

It favors:

- simple local commands
- JSON artifacts on disk
- Binance `order/test` before any real order path
- paper-live and replay verification before longer runs

## Workspace Layout

Initialize a local working area:

```python
from quant_binance.bootstrap import initialize_workspace

layout = initialize_workspace("quant_runtime")
print(layout.output_root)
```

This creates:

```text
quant_runtime/
  output/
    replay/
    paper-live/
    paper-live-test-order/
    paper-live-shell/
  artifacts/
  oracle/
  manifests/
```

## Recommended Order

1. `env-check`
2. `replay`
3. `paper-live`
4. `paper-live-shell`
5. `paper-live-test-order`

Do not skip directly to a live order path.

## Commands

Before any Binance `order/test` run, set credentials in either your shell or the repository root `.env`.

Example:

```env
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
STRATEGY_PROFILE=aggressive_alt
AUTO_STRATEGY_SWITCH=1
AUTO_STRATEGY_CALM_PROFILE=aggressive_alt
AUTO_STRATEGY_FAST_PROFILE=scalp_ultra
AUTO_STRATEGY_MIN_HOLD_CYCLES=3
UNIVERSE_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT
MACRO_INPUTS_PATH=quant_binance/examples/macro_inputs.sample.json
ALTCOIN_INPUTS_PATH=quant_binance/examples/altcoin_inputs.sample.json
```

`STRATEGY_PROFILE` can be switched per market state (for example `aggressive_alt` for broader swing entries, `alpha_max` for higher-throughput risk-on entries, `scalp_ultra` for faster short-horizon entries).
If `AUTO_STRATEGY_SWITCH=1`, runtime auto-switches between calm/fast profiles using 1h return and volatility-penalty hysteresis (`AUTO_STRATEGY_*` env vars).
If `UNIVERSE_SYMBOLS` is set, it overrides the default `universe` in config.
Use this to mirror the symbols you enabled in Binance symbol whitelist.
If `MACRO_INPUTS_PATH` or `MACRO_INPUTS_JSON` is set, macro regime inputs are loaded and applied before regime selection.
If `ALTCOIN_INPUTS_PATH` or `ALTCOIN_INPUTS_JSON` is set, altcoin intelligence inputs are loaded for non-BTC/ETH symbols and affect edge estimation and regime gating.

Environment readiness:

```bash
python3 -m quant_binance.runtime --mode env-check
```

Replay:

```bash
python3 -m quant_binance.runtime \
  --mode replay \
  --fixture tests/replay_fixture.json \
  --output quant_runtime/output/replay/latest/summary.json
```

Paper-live fixture run:

```bash
python3 -m quant_binance.runtime \
  --mode paper-live \
  --fixture tests/paper_live_fixture.json \
  --output quant_runtime/output/paper-live/latest/summary.json
```

Event-driven paper shell:

```bash
python3 -m quant_binance.runtime \
  --mode paper-live-shell \
  --fixture tests/paper_live_fixture.json \
  --output quant_runtime/output/paper-live-shell/latest/summary.json \
  --max-retries 3
```

Binance `order/test` validation:

```bash
BINANCE_API_KEY=... BINANCE_API_SECRET=... \
python3 -m quant_binance.runtime \
  --mode paper-live-test-order \
  --fixture tests/paper_live_fixture.json \
  --output quant_runtime/output/paper-live-test-order/latest/summary.json
```

Single-user shortcut scripts:

```bash
sh scripts/quant_init_workspace.sh quant_runtime
sh scripts/quant_env_check.sh
sh scripts/quant_replay.sh quant_binance/examples/replay_fixture.sample.json
sh scripts/quant_paper_live_shell.sh quant_binance/examples/paper_live_fixture.sample.json
sh scripts/quant_smoke_all.sh quant_runtime
sh scripts/quant_run_forever.sh quant_runtime
sh scripts/quant_run_live_orders.sh quant_runtime
sh scripts/quant_status.sh quant_runtime
sh scripts/quant_report.sh quant_runtime
sh scripts/quant_stop.sh
sh scripts/quant_remote_command.sh status
sh scripts/openclaw_setup_telegram.sh
sh scripts/quant_extract_naver_article.sh 'https://naver.me/IxKJQmc9' quant_runtime/artifacts/naver_strategy.md
sh scripts/quant_extract_naver_openclaw.sh 'https://naver.me/IxKJQmc9' quant_runtime/artifacts/openclaw_naver_strategy.md
```

`quant_smoke_all.sh` runs the recommended local smoke path and includes `paper-live-test-order` only when Binance API env vars are present.

`quant_run_forever.sh` starts the long-running live paper daemon mode for single-user local operation.

`quant_run_live_orders.sh` starts the long-running daemon with actual live order submission enabled.

`quant_status.sh` prints the latest saved state so you can tell whether the loop is still alive.

`quant_report.sh` prints a concise runtime summary suitable for relaying over Telegram.

`quant_stop.sh` stops the active daemon processes.

`quant_extract_naver_article.sh` tries to reuse your local Chrome profile and crawl a Naver page plus same-domain internal links into a markdown index, per-page markdown files, screenshots, and downloadable images when available.

`quant_extract_naver_openclaw.sh` uses OpenClaw browser commands to walk same-domain internal links and save per-page markdown files and downloaded images.

`quant_remote_command.sh` is the single bridge command for OpenClaw/Telegram remote control.

See [REMOTE.md](/Users/tttksj/first_repo/quant_binance/REMOTE.md) for the Telegram remote-control workflow.

## What To Watch

- `summary.json`
- `summary.state.json`
- `kill_switch`
- `tested_order_count`
- `account_snapshot`
- `open_orders_snapshot`

If `kill_switch.armed = true`, stop and inspect the latest state/report before continuing.

## Practical Notes

- Keep API keys `trade only` and disable withdrawals.
- Use `order/test` and small paper loops first.
- Treat output folders as disposable run logs, not as a database.
- If you change config thresholds, keep the previous output directories for comparison.
