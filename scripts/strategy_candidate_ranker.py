#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ARTIFACTS = Path(__file__).resolve().parent.parent / "quant_runtime" / "artifacts"
HANDOFF_PATH = ARTIFACTS / "strategy_candidate_handoff.json"
OUTPUT_JSON = ARTIFACTS / "strategy_candidate_ranked.json"
OUTPUT_MD = ARTIFACTS / "strategy_candidate_ranked.md"


def _load_payload() -> dict:
    return json.loads(HANDOFF_PATH.read_text(encoding="utf-8"))


def _rotation_score(row: dict) -> float:
    total_return = float(row.get("total_return_pct", 0.0))
    sharpe = float(row.get("sharpe_like", 0.0))
    pf = float(row.get("profit_factor", 0.0))
    mdd = float(row.get("max_drawdown_pct", 100.0))
    turnover = float(row.get("average_turnover", 1.0))
    score = (
        min(total_return / 100.0, 2.0) * 25.0
        + min(sharpe, 3.0) * 20.0
        + min(max(pf - 1.0, 0.0), 0.25) * 120.0
        - min(mdd, 80.0) * 0.65
        - turnover * 18.0
    )
    if bool(row.get("require_positive")):
        score += 4.0
    if bool(row.get("ema_filter")):
        score += 3.0
    if int(row.get("rebalance_hours", 0)) == 4:
        score += 2.0
    return round(score, 4)


def _carry_score(row: dict) -> float:
    total_bps = float(row.get("total_return_bps", 0.0))
    pf = float(row.get("profit_factor", 0.0))
    stressed_total = float(row.get("stressed_total_return_bps", 0.0))
    stressed_pf = float(row.get("stressed_profit_factor", 0.0))
    folds = int(row.get("positive_folds", 0))
    trades = int(row.get("trades", 0))
    mdd = float(row.get("max_drawdown_bps", 0.0))
    score = (
        min(total_bps / 100.0, 8.0) * 8.0
        + min(max(pf - 1.0, 0.0), 6.0) * 8.0
        + min(stressed_total / 100.0, 8.0) * 6.0
        + min(max(stressed_pf - 1.0, 0.0), 5.0) * 6.0
        + folds * 8.0
        + min(trades, 30) * 0.5
        - min(mdd / 100.0, 8.0) * 4.0
    )
    return round(score, 4)


def main() -> int:
    payload = _load_payload()
    ranked: list[dict] = []

    for row in payload.get("rotation_candidates", []):
        ranked.append(
            {
                "family": "rotation",
                "summary": (
                    f"majors lookback={row['lookback_hours']}h rebalance={row['rebalance_hours']}h "
                    f"top_k={row['top_k']} score={row['score_mode']} pos={row['require_positive']} ema={row['ema_filter']}"
                ),
                "score": _rotation_score(row),
                "metrics": row,
            }
        )
    for row in payload.get("carry_candidates", []):
        ranked.append(
            {
                "family": "carry",
                "summary": (
                    f"{row['symbol']} funding>={row['funding_threshold']:.5f} basis>={row['basis_threshold_bps']:.1f}bps "
                    f"hold={row['hold_hours']}h stop={row['stop_bps']:.0f} tp={row['tp_bps']:.0f}"
                ),
                "score": _carry_score(row),
                "metrics": row,
            }
        )

    ranked.sort(key=lambda row: row["score"], reverse=True)
    output = {
        "generated_by": "strategy_candidate_ranker",
        "source": str(HANDOFF_PATH),
        "ranked_candidates": ranked,
    }
    OUTPUT_JSON.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = ["# Strategy Candidate Ranking", ""]
    for index, row in enumerate(ranked[:10], start=1):
        metrics = row["metrics"]
        if row["family"] == "rotation":
            lines.append(
                f"{index}. [rotation] {row['summary']} | score={row['score']:.2f} "
                f"| return={float(metrics['total_return_pct']):+.2f}% PF={float(metrics['profit_factor']):.2f} "
                f"MDD={float(metrics['max_drawdown_pct']):.2f}% Sharpe={float(metrics['sharpe_like']):.2f}"
            )
        else:
            lines.append(
                f"{index}. [carry] {row['summary']} | score={row['score']:.2f} "
                f"| total={float(metrics['total_return_bps']):+.1f}bps PF={float(metrics['profit_factor']):.2f} "
                f"WF={int(metrics.get('positive_folds', 0))}/4 stress24={float(metrics.get('stressed_total_return_bps', 0.0)):+.1f}bps"
            )
    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 100)
    print("STRATEGY CANDIDATE RANKING")
    print("=" * 100)
    print(f"saved_json={OUTPUT_JSON}")
    print(f"saved_md={OUTPUT_MD}")
    for row in ranked[:10]:
        print(f"{row['family']:<8} score={row['score']:>6.2f} {row['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
