# OpenClaw Remote Control

## Goal

Use OpenClaw over Telegram to trigger local control commands on this desktop.

The recommended commands are mapped to one local bridge script:

```bash
sh scripts/quant_remote_command.sh <command>
```

Supported commands:

- `start`
- `start-live`
- `status`
- `report`
- `stop`
- `smoke`
- `extract`

## Telegram Setup

Set your bot token in the environment or `.env.local`:

```env
TELEGRAM_BOT_TOKEN=123456:ABC...
```

Then run:

```bash
sh scripts/openclaw_setup_telegram.sh
sh scripts/quant_telegram_bridge.sh
```

Optional allowlist:

```env
TELEGRAM_CHAT_ID_ALLOWLIST=123456789
```

## Suggested Remote Workflow

From Telegram via OpenClaw:

- `/status` to check if the daemon is alive
- `/report` to get a concise summary
- `/start` for paper mode
- `/startlive` only when you explicitly want live orders
- `/stop` to stop all active daemon processes
- `/smoke` to run smoke checks
- `/extract` to trigger the article crawler
- `/codex status-check`
- `/codex capital-report`
- `/codex latest-run-review`
- `/codex strategy-review`
- `/gemini status-check`
- `/gemini capital-report`
- `/gemini latest-run-review`
- `/gemini strategy-review`

## Safety

- Treat `start-live` as real-money control.
- Prefer `status` and `report` before `start-live`.
- Keep withdrawals disabled on Binance.
