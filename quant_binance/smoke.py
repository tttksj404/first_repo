from __future__ import annotations

from pathlib import Path
from typing import Any

from quant_binance.paths import prepare_run_paths
from quant_binance.runtime import (
    run_paper_live_mode,
    run_paper_live_shell_mode,
    run_paper_live_test_order_mode,
    run_replay_mode,
)


def run_smoke(
    *,
    mode: str,
    config_path: str | Path,
    fixture_path: str | Path,
    output_base_dir: str | Path,
    equity_usd: float = 10000.0,
    capacity_usd: float = 5000.0,
    client: Any | None = None,
    run_id: str | None = None,
) -> dict[str, object]:
    paths = prepare_run_paths(base_dir=output_base_dir, mode=mode, run_id=run_id)
    if mode == "replay":
        summary = run_replay_mode(
            config_path=config_path,
            fixture_path=fixture_path,
            equity_usd=equity_usd,
            capacity_usd=capacity_usd,
        )
    elif mode == "paper-live":
        summary = run_paper_live_mode(
            config_path=config_path,
            fixture_path=fixture_path,
            equity_usd=equity_usd,
            capacity_usd=capacity_usd,
        )
    elif mode == "paper-live-shell":
        summary = run_paper_live_shell_mode(
            config_path=config_path,
            fixture_path=fixture_path,
            equity_usd=equity_usd,
            capacity_usd=capacity_usd,
            output_path=paths.summary_path,
            max_retries=3,
        )
    elif mode == "paper-live-test-order":
        summary = run_paper_live_test_order_mode(
            config_path=config_path,
            fixture_path=fixture_path,
            equity_usd=equity_usd,
            capacity_usd=capacity_usd,
            client=client,
        )
    else:
        raise ValueError(f"unsupported smoke mode: {mode}")

    if not paths.summary_path.exists():
        from quant_binance.observability.report import write_runtime_summary

        write_runtime_summary(paths.summary_path, summary)
    if not paths.state_path.exists():
        from quant_binance.observability.runtime_state import write_runtime_state

        write_runtime_state(
            paths.state_path,
            {
                "mode": mode,
                "decision_count": summary.get("decision_count", 0),
                "tested_order_count": summary.get("tested_order_count", 0),
            },
        )
    return {"paths": paths, "summary": summary}
