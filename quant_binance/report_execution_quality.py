from __future__ import annotations

import argparse
from pathlib import Path

from quant_binance.execution_quality_report import build_execution_quality_report, write_execution_quality_report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an execution quality report for recent live runs.")
    parser.add_argument("--base-dir", default="quant_runtime")
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--output", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    report = build_execution_quality_report(base_dir=args.base_dir, lookback_days=args.lookback_days)
    output = Path(args.output) if args.output else Path(args.base_dir) / "artifacts" / "execution_quality_report.json"
    write_execution_quality_report(report=report, output_path=output)
    print(f"base_dir={report.base_dir}")
    print(f"report={output}")
    print(f"run_count={report.run_count}")
    print(f"live_order_count={report.live_order_count}")
    print(f"accepted_live_order_count={report.accepted_live_order_count}")
    print(f"estimated_live_acceptance_rate={report.estimated_live_acceptance_rate}")
    print("top_error_codes=")
    for row in report.top_error_codes:
        print(row)
    print("symbol_order_summary=")
    for row in report.symbol_order_summary[:10]:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
