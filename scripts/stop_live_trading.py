"""Graceful stop for the live trading stack started by start_live_trading.py.

Order:
  1. Touch supervisor and guardian stop-files so they exit cleanly on next loop tick.
  2. Wait briefly for graceful exit.
  3. Force-kill any lingering python processes that match the stack components
     OR a raw `python -m quant_binance.runtime --mode live-auto-trade-daemon`.

This does NOT close open Bitget positions. If a position is open, decide
explicitly whether to close it (e.g., scripts/close_doge_short_oneshot.py
pattern, or close manually on Bitget).
"""
from __future__ import annotations

import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


STOP_FILES = (
    "scripts/_supervisor_stop",
    "scripts/_safety_guardian_stop",
)

MATCH_SUBSTRS = (
    "daemon_supervisor.py",
    "position_safety_guardian.py",
    "monitor_daemon_health.py",
    "live-auto-trade-daemon",
    "quant_binance.runtime",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _powershell(cmd: str) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout or ""


def _running_python_processes() -> list[tuple[str, str]]:
    out = _powershell(
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Select-Object ProcessId, CommandLine | "
        "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }"
    )
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        pid_str, _, cmdline = line.partition("|")
        rows.append((pid_str.strip(), cmdline.strip()))
    return rows


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]

    print(f"[{_now_iso()}] touching stop files for graceful exit...")
    for rel in STOP_FILES:
        p = project_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("stop", encoding="utf-8")
        print(f"  touched {rel}")

    print(f"[{_now_iso()}] waiting 6s for graceful exit...")
    time.sleep(6)

    survivors: list[tuple[str, str]] = []
    for pid, cmd in _running_python_processes():
        if any(s in cmd for s in MATCH_SUBSTRS):
            survivors.append((pid, cmd))

    if not survivors:
        print(f"[{_now_iso()}] all stack processes exited gracefully.")
        return 0

    print(f"[{_now_iso()}] force-killing survivors:")
    for pid, cmd in survivors:
        print(f"  kill pid={pid} :: {cmd[:160]}")
        _powershell(f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue")

    time.sleep(1)
    remaining = [
        (pid, cmd) for pid, cmd in _running_python_processes() if any(s in cmd for s in MATCH_SUBSTRS)
    ]
    if remaining:
        print(f"[{_now_iso()}] WARNING: {len(remaining)} processes still alive:")
        for pid, cmd in remaining:
            print(f"  pid={pid} :: {cmd[:160]}")
        return 3
    print(f"[{_now_iso()}] stack stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
