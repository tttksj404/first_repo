#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ARTIFACTS = Path(__file__).resolve().parent.parent / "quant_runtime" / "artifacts"
RANKED_PATH = ARTIFACTS / "strategy_candidate_ranked.json"
OUTPUT_JSON = ARTIFACTS / "strategy_paper_queue.json"
OUTPUT_MD = ARTIFACTS / "strategy_paper_queue.md"


def _load_ranked() -> list[dict]:
    payload = json.loads(RANKED_PATH.read_text(encoding="utf-8"))
    return list(payload.get("ranked_candidates") or [])


def _queue_entry(index: int, row: dict) -> dict:
    family = row["family"]
    metrics = row["metrics"]
    if family == "rotation":
        return {
            "priority": index,
            "family": family,
            "label": row["summary"],
            "paper_goal": "recent-comparison 재검증 후 majors 전용 paper 모니터링 여부 판단",
            "commands": [
                "python3 scripts/rotation_strategy_scan.py --workers 4",
                "python3 scripts/rotation_strategy_shortlist.py",
                "python3 scripts/strategy_candidate_ranker.py",
                "sh scripts/run_strategy_candidate_paper.sh start quant_runtime/artifacts/candidate_overrides/rotation_review_top1.json",
            ],
            "notes": {
                "lookback_hours": metrics["lookback_hours"],
                "rebalance_hours": metrics["rebalance_hours"],
                "top_k": metrics["top_k"],
                "score_mode": metrics["score_mode"],
                "max_drawdown_pct": metrics["max_drawdown_pct"],
            },
        }
    symbol = metrics["symbol"]
    return {
        "priority": index,
        "family": family,
        "label": row["summary"],
        "paper_goal": "carry/basis 가설을 최근 구간과 paper shell 감시 대상으로 우선 검증",
        "commands": [
            "python3 scripts/carry_basis_strategy_scan.py",
            f"sh scripts/run_strategy_candidate_paper.sh start quant_runtime/artifacts/candidate_overrides/strategy_override.carry_top{min(index,3)}.json",
            f"sh scripts/run_strategy_candidate_paper.sh status quant_runtime/artifacts/candidate_overrides/strategy_override.carry_top{min(index,3)}.json",
            f"sh scripts/run_strategy_candidate_paper.sh report quant_runtime/artifacts/candidate_overrides/strategy_override.carry_top{min(index,3)}.json",
        ],
        "notes": {
            "symbol": symbol,
            "funding_threshold": metrics["funding_threshold"],
            "basis_threshold_bps": metrics["basis_threshold_bps"],
            "hold_hours": metrics["hold_hours"],
            "positive_folds": metrics.get("positive_folds", 0),
            "stressed_total_return_bps": metrics.get("stressed_total_return_bps", 0.0),
        },
    }


def main() -> int:
    ranked = _load_ranked()
    top_rows: list[dict] = []
    top_carry = next((row for row in ranked if row["family"] == "carry"), None)
    top_rotation = next((row for row in ranked if row["family"] == "rotation"), None)
    if top_carry is not None:
        top_rows.append(top_carry)
    if top_rotation is not None and top_rotation not in top_rows:
        top_rows.append(top_rotation)
    for row in ranked:
        if row in top_rows:
            continue
        top_rows.append(row)
        if len(top_rows) >= 6:
            break
    queue = [_queue_entry(index, row) for index, row in enumerate(top_rows, start=1)]
    payload = {
        "generated_by": "strategy_paper_queue",
        "source": str(RANKED_PATH),
        "queue": queue,
    }
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = ["# Strategy Paper Queue", ""]
    for item in queue:
        lines.append(f"## Priority {item['priority']}: {item['family']} — {item['label']}")
        lines.append(f"- Goal: {item['paper_goal']}")
        for command in item["commands"]:
            lines.append(f"- Command: `{command}`")
        lines.append(f"- Notes: `{json.dumps(item['notes'], ensure_ascii=False)}`")
        lines.append("")
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print("=" * 100)
    print("STRATEGY PAPER QUEUE")
    print("=" * 100)
    print(f"saved_json={OUTPUT_JSON}")
    print(f"saved_md={OUTPUT_MD}")
    print(f"queued={len(queue)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
