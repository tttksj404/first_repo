"""Canonical launcher for the live trading stack.

Brings up components together:
  1. daemon_supervisor.py     -- spawns + auto-restarts the trading daemon
  2. monitor_daemon_health    -- writes health snapshots for observability
  3. position_safety_guardian -- optional (enable with STACK_ENABLE_GUARDIAN=1)

Refuses to start if any selected component (or a raw daemon) is already running.

This is the ONLY supported way to start live trading. Do NOT run
`python -m quant_binance.runtime --mode live-auto-trade-daemon` directly:
that bypasses the supervisor (and optionally guardian), which means a daemon crash
leaves positions abandoned (the 2026-04-15 PEPE incident).

To stop everything: python scripts/stop_live_trading.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


BASE_COMPONENTS = [
    {
        "name": "supervisor",
        "script": "scripts/daemon_supervisor.py",
        "stop_file": "scripts/_supervisor_stop",
        "match_substr": "daemon_supervisor.py",
    },
    {
        "name": "monitor",
        "script": "scripts/monitor_daemon_health.py",
        "stop_file": None,  # monitor self-exits after MONITOR_MINUTES
        "match_substr": "monitor_daemon_health.py",
    },
]

GUARDIAN_COMPONENT = {
    "name": "guardian",
    "script": "scripts/position_safety_guardian.py",
    "stop_file": "scripts/_safety_guardian_stop",
    "match_substr": "position_safety_guardian.py",
}

DAEMON_MATCH_SUBSTRS = (
    "live-auto-trade-daemon",
    "quant_binance.runtime",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _powershell(cmd: str) -> str:
    """Run a PowerShell command and return stdout."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout or ""


def _running_python_processes() -> list[dict[str, str]]:
    """Return list of {pid, cmdline} for every running python.exe."""
    out = _powershell(
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Select-Object ProcessId, CommandLine | "
        "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }"
    )
    rows: list[dict[str, str]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        pid_str, _, cmdline = line.partition("|")
        rows.append({"pid": pid_str.strip(), "cmdline": cmdline.strip()})
    return rows


def _is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _selected_components() -> list[dict[str, str]]:
    components = list(BASE_COMPONENTS)
    if _is_truthy(os.environ.get("STACK_ENABLE_GUARDIAN")):
        components.append(dict(GUARDIAN_COMPONENT))
    return components


def _detect_existing(project_root: Path, components: list[dict[str, str]]) -> list[tuple[str, str, str]]:
    """Return list of (name, pid, cmdline) for any stack component already running."""
    found: list[tuple[str, str, str]] = []
    procs = _running_python_processes()
    for proc in procs:
        cmd = proc["cmdline"]
        for comp in components:
            if comp["match_substr"] in cmd:
                found.append((comp["name"], proc["pid"], cmd))
        if any(s in cmd for s in DAEMON_MATCH_SUBSTRS):
            found.append(("raw-daemon", proc["pid"], cmd))
    return found


def _clear_stop_files(project_root: Path, components: list[dict[str, str]]) -> None:
    for comp in components:
        if not comp["stop_file"]:
            continue
        p = project_root / comp["stop_file"]
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def _launch(project_root: Path, script_rel: str) -> str:
    script_path = (project_root / script_rel).as_posix()
    cmd = (
        f"Start-Process -FilePath 'python' -ArgumentList '-u','{script_rel}' "
        f"-WorkingDirectory '{str(project_root)}' -WindowStyle Hidden -PassThru | "
        f"Select-Object -ExpandProperty Id"
    )
    out = _powershell(cmd).strip()
    return out


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    components = _selected_components()
    guardian_enabled = any(c["name"] == "guardian" for c in components)
    bypass_policy_guardrails = _is_truthy(os.environ.get("STACK_BYPASS_POLICY_GUARDRAILS", "1"))
    bypass_execution_quality_edge_guard = _is_truthy(
        os.environ.get("STACK_DISABLE_EXECUTION_QUALITY_EDGE_GUARD", "1")
    )
    if bypass_policy_guardrails:
        os.environ["QUANT_BYPASS_POLICY_GUARDRAILS"] = "1"
    else:
        os.environ.pop("QUANT_BYPASS_POLICY_GUARDRAILS", None)
    if bypass_execution_quality_edge_guard:
        os.environ["QUANT_DISABLE_EXECUTION_QUALITY_EDGE_GUARD"] = "1"
    else:
        os.environ.pop("QUANT_DISABLE_EXECUTION_QUALITY_EDGE_GUARD", None)

    print(f"[{_now_iso()}] start_live_trading: scanning for existing processes...")
    existing = _detect_existing(project_root, components)
    if existing:
        print(f"[{_now_iso()}] REFUSING TO START: stack components already running:")
        for name, pid, cmd in existing:
            print(f"  - {name} pid={pid} :: {cmd[:160]}")
        print()
        print("Stop them first:  python scripts/stop_live_trading.py")
        return 2

    _clear_stop_files(project_root, components)

    pid_log = project_root / "quant_runtime" / "_stack_launch.log"
    pid_log.parent.mkdir(parents=True, exist_ok=True)
    with pid_log.open("a", encoding="utf-8") as f:
        f.write(f"\n=== launch @ {_now_iso()} ===\n")
        for comp in components:
            pid = _launch(project_root, comp["script"])
            line = f"[{_now_iso()}] started {comp['name']} pid={pid}"
            print(line)
            f.write(line + "\n")
            time.sleep(0.5)

    print()
    print(f"[{_now_iso()}] policy_guardrail_bypass={bypass_policy_guardrails} (set STACK_BYPASS_POLICY_GUARDRAILS=0 to enforce)")
    print(
        f"[{_now_iso()}] execution_quality_edge_guard_bypass={bypass_execution_quality_edge_guard} "
        "(set STACK_DISABLE_EXECUTION_QUALITY_EDGE_GUARD=0 to enforce)"
    )
    print(f"[{_now_iso()}] guardian_enabled={guardian_enabled} (set STACK_ENABLE_GUARDIAN=1 to enable)")
    print(f"[{_now_iso()}] stack up. observe with:")
    print("  Get-Content -Wait quant_runtime/_supervisor.log")
    if guardian_enabled:
        print("  Get-Content -Wait quant_runtime/_safety_guardian.log")
    print("  Get-Content quant_runtime/_monitor_status.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
