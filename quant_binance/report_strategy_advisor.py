from __future__ import annotations

import argparse
from pathlib import Path

from quant_binance.strategy_advisor import generate_strategy_advisor_report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a Korean strategy advisor report from runtime, performance, and macro context.")
    parser.add_argument("--base-dir", default="quant_runtime")
    parser.add_argument("--provider", choices=("codex", "gemini", "prepare"), default="codex")
    parser.add_argument("--mode", choices=("advisor", "suggestion"), default="advisor")
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--send-telegram", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    result = generate_strategy_advisor_report(
        base_dir=args.base_dir,
        provider=args.provider,
        mode=args.mode,
        lookback_days=args.lookback_days,
        send_telegram=args.send_telegram,
    )
    print(f"context={result['context_path']}")
    print(f"prompt={result['prompt_path']}")
    print(f"report={result['report_path']}")
    print(f"summary={result['summary_path']}")
    if result.get("telegram") is not None:
        print(f"telegram={result['telegram']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
