from __future__ import annotations

import argparse
from pathlib import Path

from quant_binance.ai_provider import normalize_provider, provider_choices, run_provider_prompt


TASK_PROMPTS = {
    "status-check": "Review the latest quant_runtime summary/state/log files in this repository and answer concisely in Korean: 1) is the daemon alive, 2) are events arriving, 3) are live orders happening, 4) what is the main blocker right now.",
    "capital-report": "Read the latest capital report/state in this repository and answer concisely in Korean: 1) spot available balance, 2) futures available balance, 3) whether spot trading is allowed, 4) whether futures trading is allowed, 5) minimum and recommended capital.",
    "latest-run-review": "Inspect the latest quant_runtime run artifacts and summarize in Korean: current operating state, recent decisions, kill-switch state, and whether there are obvious runtime issues. Keep it concise.",
    "strategy-review": "Review the current quant_binance strategy implementation and summarize in Korean: 1) what quantitative signals it uses, 2) whether it is currently conservative or aggressive, 3) the top 3 risks or limitations.",
}


def run_named_task(
    *,
    provider: str,
    task: str,
    root: str | Path,
    model: str | None = None,
    timeout: int = 180,
) -> str:
    if task not in TASK_PROMPTS:
        raise ValueError(f"unknown task: {task}")
    return run_provider_prompt(
        provider=provider,
        prompt=TASK_PROMPTS[task],
        root=root,
        model=model,
        timeout=timeout,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a named quant AI review task with a selectable provider/model.")
    parser.add_argument("--provider", choices=provider_choices(), default="codex")
    parser.add_argument("--task", choices=tuple(TASK_PROMPTS), required=True)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--model", default="")
    parser.add_argument("--timeout", type=int, default=180)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    text = run_named_task(
        provider=normalize_provider(args.provider),
        task=args.task,
        root=args.root,
        model=args.model or None,
        timeout=args.timeout,
    )
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
