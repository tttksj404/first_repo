from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RemoteCommand:
    action: str
    mode: str
    description: str
    script: str


REMOTE_COMMANDS: dict[str, RemoteCommand] = {
    "start": RemoteCommand(
        action="start",
        mode="live",
        description="Start long-running live auto-trading daemon",
        script="sh scripts/quant_run_live_orders.sh quant_runtime",
    ),
    "start-live": RemoteCommand(
        action="start-live",
        mode="live",
        description="Start long-running live auto-trading daemon",
        script="sh scripts/quant_run_live_orders.sh quant_runtime",
    ),
    "status": RemoteCommand(
        action="status",
        mode="read",
        description="Show latest runtime state",
        script="sh scripts/quant_status.sh quant_runtime",
    ),
    "report": RemoteCommand(
        action="report",
        mode="read",
        description="Show latest runtime summary",
        script="sh scripts/quant_report.sh quant_runtime",
    ),
    "stop": RemoteCommand(
        action="stop",
        mode="control",
        description="Stop active daemon processes",
        script="sh scripts/quant_stop.sh",
    ),
    "smoke": RemoteCommand(
        action="smoke",
        mode="verify",
        description="Run smoke checks",
        script="sh scripts/quant_smoke_all.sh quant_runtime",
    ),
    "extract": RemoteCommand(
        action="extract",
        mode="crawler",
        description="Run OpenClaw Naver crawler",
        script="sh scripts/quant_extract_naver_openclaw.sh 'https://naver.me/IxKJQmc9' quant_runtime/artifacts/openclaw_naver_strategy.md",
    ),
}


def resolve_remote_command(raw: str) -> RemoteCommand:
    key = raw.strip().lower()
    if key not in REMOTE_COMMANDS:
        raise KeyError(key)
    return REMOTE_COMMANDS[key]
