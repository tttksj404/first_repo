#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


SCAN_PATH = Path(__file__).resolve().parent.parent / "quant_runtime" / "artifacts" / "rotation_strategy_scan.json"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "quant_runtime" / "artifacts" / "rotation_strategy_shortlist.json"


def _load_rows() -> list[dict]:
    payload = json.loads(SCAN_PATH.read_text(encoding="utf-8"))
    rows = list(payload.get("all_results") or payload.get("top_results") or [])
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Filter practical rotation candidates from the full scan output.")
    parser.add_argument("--max-mdd", type=float, default=52.0)
    parser.add_argument("--min-pf", type=float, default=1.05)
    parser.add_argument("--min-sharpe", type=float, default=1.20)
    parser.add_argument("--max-turnover", type=float, default=0.95)
    parser.add_argument("--min-return", type=float, default=0.0)
    parser.add_argument("--prefer-universe", default="majors")
    args = parser.parse_args()

    rows = _load_rows()
    practical: list[dict] = []
    for row in rows:
        if args.prefer_universe and row.get("universe") != args.prefer_universe:
            continue
        if float(row.get("max_drawdown_pct", 999.0)) > args.max_mdd:
            continue
        if float(row.get("profit_factor", 0.0)) < args.min_pf:
            continue
        if float(row.get("sharpe_like", 0.0)) < args.min_sharpe:
            continue
        if float(row.get("average_turnover", 999.0)) > args.max_turnover:
            continue
        if float(row.get("total_return_pct", -999.0)) <= args.min_return:
            continue
        if int(row.get("rebalance_hours", 0)) not in {24, 4}:
            continue
        practical.append(row)
    practical.sort(
        key=lambda row: (
            float(row.get("sharpe_like", 0.0)),
            float(row.get("total_return_pct", 0.0)),
            float(row.get("profit_factor", 0.0)),
        ),
        reverse=True,
    )
    payload = {
        "generated_by": "rotation_strategy_shortlist",
        "source": str(SCAN_PATH),
        "filters": {
            "prefer_universe": args.prefer_universe,
            "max_mdd": args.max_mdd,
            "min_pf": args.min_pf,
            "min_sharpe": args.min_sharpe,
            "max_turnover": args.max_turnover,
            "min_return": args.min_return,
        },
        "candidate_count": len(practical),
        "candidates": practical[:20],
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=" * 100)
    print("ROTATION SHORTLIST")
    print("=" * 100)
    print(f"source={SCAN_PATH}")
    print(f"saved={OUTPUT_PATH}")
    print(f"candidate_count={len(practical)}")
    print()
    for row in practical[:10]:
        print(
            f"{row['universe']:<8} lookback={row['lookback_hours']:>3}h rebalance={row['rebalance_hours']:>2}h "
            f"top_k={row['top_k']} score={row['score_mode']:<15} pos={int(bool(row['require_positive']))} ema={int(bool(row['ema_filter']))} "
            f"return={float(row['total_return_pct']):+7.2f}% PF={float(row['profit_factor']):>5.2f} "
            f"MDD={float(row['max_drawdown_pct']):>6.2f}% Sharpe={float(row['sharpe_like']):>5.2f} "
            f"turnover={float(row['average_turnover']):>5.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
