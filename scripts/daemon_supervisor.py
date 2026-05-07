"""External supervisor: auto-restarts live-auto-trade-daemon on any exit.

Handles STALL_RECOVERY_LIMIT_EXCEEDED and any other crashes by spawning a
fresh daemon process. Writes parent heartbeat to quant_runtime/_supervisor.log.
Stops when scripts/_supervisor_stop exists (touch-file).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# Bypass persisted symbol-lifecycle policy guardrails. The override
# (strategy_override.approved.json) pins the gambling universe to
# PEPE/DOGE/XRP/SOL, but prior sessions' policy_state.json records
# recommended_action="hold" on those same symbols (a blocking lifecycle
# action — see quant_binance/runtime_universe.py:8). Without this
# bypass, _apply_persisted_runtime_policy_guards marks all 4 as
# observe_only, eligible_symbols ends up empty, and every closed
# decision kline gets dropped as INELIGIBLE_SYMBOL — 0 decisions ever fire.
# Verified 2026-04-15 on PID 8600: 35937/35937 klines dropped.
# NOTE: keep empty by default for safer behavior. If you really need to bypass
# persisted runtime guardrails, export QUANT_BYPASS_POLICY_GUARDRAILS=1 before
# starting the supervisor.
# Keep live scope single-symbol by default unless STACK_UNIVERSE_SYMBOLS overrides it.
DEFAULT_LOCKED_UNIVERSE = "PEPEUSDT"
DAEMON_ENV_OVERRIDES: dict[str, str] = {}


DAEMON_CMD = [
    sys.executable,
    "-m",
    "quant_binance.runtime",
    "--mode",
    "live-auto-trade-daemon",
    "--exchange",
    "bitget",
    "--output-base",
    "quant_runtime",
    "--max-retries",
    "999999",
    "--sync-interval-seconds",
    "60",
    "--insecure-ssl",
    "--equity-usd",
    "40",
    "--ack-live-risk",
    "I_UNDERSTAND_LIVE_TRADING",
]


def _log(msg: str, log_path: Path) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    runtime = root / "quant_runtime"
    supervisor_log = runtime / "_supervisor.log"
    stop_file = root / "scripts" / "_supervisor_stop"

    max_restarts_per_hour = 30  # safety: avoid tight crash loops
    restart_times: list[float] = []

    while True:
        if stop_file.exists():
            _log("stop file present; exiting", supervisor_log)
            return 0

        now_s = time.time()
        restart_times = [t for t in restart_times if now_s - t < 3600]
        if len(restart_times) >= max_restarts_per_hour:
            _log(f"rate-limit: {len(restart_times)} restarts in last hour, sleeping 600s", supervisor_log)
            time.sleep(600)
            continue

        stdout_path = runtime / "_live_auto_trade_live_restart.log"
        stderr_path = runtime / "_live_auto_trade_live_restart.err.log"
        # Append mode so log history accumulates across restarts
        stdout_f = stdout_path.open("a", encoding="utf-8", buffering=1)
        stderr_f = stderr_path.open("a", encoding="utf-8", buffering=1)

        _log(f"spawning daemon (restart #{len(restart_times) + 1} in last hour)", supervisor_log)
        stdout_f.write(f"\n=== supervisor spawn @ {datetime.now(timezone.utc).isoformat(timespec='seconds')} ===\n")
        stderr_f.write(f"\n=== supervisor spawn @ {datetime.now(timezone.utc).isoformat(timespec='seconds')} ===\n")
        try:
            child_env = os.environ.copy()
            child_env.update(DAEMON_ENV_OVERRIDES)
            locked_universe = str(child_env.get("STACK_UNIVERSE_SYMBOLS", DEFAULT_LOCKED_UNIVERSE)).strip()
            if locked_universe:
                child_env["UNIVERSE_SYMBOLS"] = locked_universe
                _log(f"live universe locked: {locked_universe}", supervisor_log)
            if _truthy(child_env.get("QUANT_BYPASS_POLICY_GUARDRAILS")):
                _log("runtime policy guardrail bypass ENABLED (QUANT_BYPASS_POLICY_GUARDRAILS=1)", supervisor_log)
            else:
                child_env.pop("QUANT_BYPASS_POLICY_GUARDRAILS", None)
                _log("runtime policy guardrail bypass disabled (default safe mode)", supervisor_log)
            proc = subprocess.Popen(
                DAEMON_CMD,
                cwd=str(root),
                stdout=stdout_f,
                stderr=stderr_f,
                env=child_env,
            )
        except Exception as exc:
            _log(f"spawn failed: {exc}", supervisor_log)
            stdout_f.close()
            stderr_f.close()
            time.sleep(10)
            continue

        restart_times.append(now_s)
        _log(f"daemon pid={proc.pid} started", supervisor_log)

        # Wait for daemon to exit
        exit_code = proc.wait()
        stdout_f.close()
        stderr_f.close()
        _log(f"daemon pid={proc.pid} exited with code {exit_code}; restarting in 5s", supervisor_log)
        time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
