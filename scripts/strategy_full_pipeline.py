#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _run(command: list[str]) -> None:
    print(f"[run] {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full strategy candidate pipeline end-to-end.")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--fast-rotation", action="store_true")
    args = parser.parse_args()

    rotation_cmd = ["python3", "scripts/rotation_strategy_scan.py", "--workers", str(args.workers)]
    if args.fast_rotation:
        rotation_cmd.append("--fast")

    commands = [
        rotation_cmd,
        ["python3", "scripts/carry_basis_strategy_scan.py"],
        ["python3", "scripts/rotation_strategy_shortlist.py"],
        ["python3", "scripts/strategy_candidate_handoff.py"],
        ["python3", "scripts/strategy_candidate_ranker.py"],
        ["python3", "scripts/strategy_paper_queue.py"],
        ["python3", "scripts/strategy_execution_bundle.py"],
        ["python3", "scripts/strategy_runtime_gap_report.py"],
        ["python3", "scripts/carry_runtime_validation.py", "--override", "quant_runtime/artifacts/candidate_overrides/strategy_override.carry_top1.json"],
    ]

    for command in commands:
        _run(command)

    print("=" * 100)
    print("FULL STRATEGY PIPELINE COMPLETE")
    print("=" * 100)
    print("artifacts:")
    for path in (
        "quant_runtime/artifacts/rotation_strategy_scan.json",
        "quant_runtime/artifacts/carry_basis_strategy_scan.json",
        "quant_runtime/artifacts/rotation_strategy_shortlist.json",
        "quant_runtime/artifacts/strategy_candidate_handoff.json",
        "quant_runtime/artifacts/strategy_candidate_ranked.json",
        "quant_runtime/artifacts/strategy_paper_queue.json",
        "quant_runtime/artifacts/strategy_execution_bundle.json",
        "quant_runtime/artifacts/strategy_runtime_gap_report.md",
        "quant_runtime/artifacts/carry_runtime_validation.json",
    ):
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
