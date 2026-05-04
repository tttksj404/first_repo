#!/usr/bin/env python3
"""Build a long/short scorecard for the read-only paper50 monitor.

This is local-only. It reads paper50 decision and counterfactual artifacts and
does not contact an exchange or place/test/cancel orders.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_BASE = Path("quant_runtime_paper50")
DEFAULT_DECISIONS = DEFAULT_OUTPUT_BASE / "forensics" / "decisions.jsonl"
DEFAULT_COUNTERFACTUAL = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_counterfactual_latest.json"
DEFAULT_FUTURES_OUTCOMES = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_futures_signal_outcomes_latest.json"
DEFAULT_OUTPUT = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_side_scorecard_latest.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _trend_side(row: dict[str, Any]) -> str:
    direction = int(_safe_float(row.get("trend_direction"), 0.0))
    if direction > 0:
        return "long"
    if direction < 0:
        return "short"
    return "flat"


def _horizon_value(row: dict[str, Any], horizon: int) -> float | None:
    value = dict(row.get("forward_net_returns_bps") or {}).get(f"net_ret{horizon}_bps")
    if value is None:
        return None
    return _safe_float(value)


def _accepted_outcome_summary(futures_outcomes: dict[str, Any], *, side: str, horizon: int) -> dict[str, Any]:
    entries = [
        row
        for row in list(futures_outcomes.get("entries") or [])
        if str(row.get("side") or "").lower() == side and bool(row.get("is_executable"))
    ]
    values = [value for row in entries if (value := _horizon_value(row, horizon)) is not None]
    return {
        "count": len(entries),
        "net_return_count": len(values),
        "avg_net_bps": round(sum(values) / len(values), 6) if values else None,
        "positive_count": sum(1 for value in values if value > 0.0),
        "negative_count": sum(1 for value in values if value < 0.0),
        "best_net_bps": round(max(values), 6) if values else None,
        "worst_net_bps": round(min(values), 6) if values else None,
        "symbols": dict(Counter(str(row.get("symbol") or "") for row in entries)),
    }


def _side_decision_summary(decisions: list[dict[str, Any]], *, side: str) -> dict[str, Any]:
    rows = [row for row in decisions if _trend_side(row) == side]
    accepted = [
        row
        for row in rows
        if str(row.get("final_mode") or "").lower() == "futures"
        and str(row.get("side") or "").lower() == side
        and _safe_float(row.get("order_intent_notional_usd")) > 0.0
    ]
    reasons: Counter[str] = Counter()
    for row in rows:
        reasons.update(str(item) for item in list(row.get("rejection_reasons") or []))
    return {
        "candidate_count": len(rows),
        "accepted_futures_count": len(accepted),
        "cash_block_count": len(rows) - len(accepted),
        "symbol_counts": dict(Counter(str(row.get("symbol") or "") for row in rows)),
        "top_rejection_reasons": dict(reasons.most_common(12)),
    }


def _side_counterfactual_summary(counterfactual: dict[str, Any], *, side: str) -> dict[str, Any]:
    side_summary = dict((counterfactual.get("side_summaries") or {}).get(side) or {})
    possible_entries = list(side_summary.get("recent_possible_missed_entries") or [])
    if not side_summary:
        possible_entries = [
            row for row in list(counterfactual.get("possible_missed_entries") or [])
            if str(row.get("direction") or "").lower() == side
        ]
        side_summary = {
            "decision_count": 0,
            "label_counts": {},
            "possible_missed_entry_count": len(possible_entries),
            "avg_net_after_cost_bps": None,
            "best_net_after_cost_bps": None,
            "worst_net_after_cost_bps": None,
        }
    return {
        "decision_count": int(side_summary.get("decision_count") or 0),
        "label_counts": dict(side_summary.get("label_counts") or {}),
        "possible_missed_entry_count": int(side_summary.get("possible_missed_entry_count") or 0),
        "avg_net_after_cost_bps": side_summary.get("avg_net_after_cost_bps"),
        "best_net_after_cost_bps": side_summary.get("best_net_after_cost_bps"),
        "worst_net_after_cost_bps": side_summary.get("worst_net_after_cost_bps"),
        "recent_possible_missed_entries": possible_entries[-5:],
    }


def _recommendation(
    *,
    side: str,
    decision_summary: dict[str, Any],
    counterfactual_summary: dict[str, Any],
    accepted_summary: dict[str, Any],
) -> str:
    accepted_count = int(accepted_summary.get("count") or 0)
    avg_accepted = accepted_summary.get("avg_net_bps")
    possible_count = int(counterfactual_summary.get("possible_missed_entry_count") or 0)
    cf_decisions = int(counterfactual_summary.get("decision_count") or 0)
    possible_rate = (possible_count / cf_decisions) if cf_decisions else 0.0
    if accepted_count > 0 and avg_accepted is not None and float(avg_accepted) < 0.0:
        return f"hold_{side}_gates_accepted_signal_lost"
    if possible_count >= 2 and possible_rate >= 0.08:
        return f"test_one_step_{side}_relaxation_in_paper_only"
    if possible_count >= 1:
        return f"watch_{side}_misses_before_relaxing"
    if int(decision_summary.get("candidate_count") or 0) == 0:
        return f"collect_more_{side}_candidates"
    return f"hold_{side}_gates"


def build_scorecard(
    *,
    decisions: list[dict[str, Any]],
    counterfactual: dict[str, Any],
    futures_outcomes: dict[str, Any],
    horizon: int = 15,
) -> dict[str, Any]:
    sides: dict[str, Any] = {}
    for side in ("long", "short"):
        decision_summary = _side_decision_summary(decisions, side=side)
        cf_summary = _side_counterfactual_summary(counterfactual, side=side)
        accepted_summary = _accepted_outcome_summary(futures_outcomes, side=side, horizon=horizon)
        sides[side] = {
            "decisions": decision_summary,
            "counterfactual": cf_summary,
            "accepted_outcomes": accepted_summary,
            "recommendation": _recommendation(
                side=side,
                decision_summary=decision_summary,
                counterfactual_summary=cf_summary,
                accepted_summary=accepted_summary,
            ),
        }

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "paper50_long_short_scorecard",
        "fallback_semantics": {
            "long_failure_enters_short": False,
            "summary": "The runtime chooses one directional futures plan per snapshot; short is used only when the effective direction is bearish, not as a fallback after a rejected long.",
        },
        "horizon_minutes": horizon,
        "sides": sides,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions-path", default=str(DEFAULT_DECISIONS))
    parser.add_argument("--counterfactual", default=str(DEFAULT_COUNTERFACTUAL))
    parser.add_argument("--futures-outcomes", default=str(DEFAULT_FUTURES_OUTCOMES))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--horizon", type=int, default=15)
    args = parser.parse_args()

    payload = build_scorecard(
        decisions=_load_jsonl(Path(args.decisions_path)),
        counterfactual=_read_json(Path(args.counterfactual)),
        futures_outcomes=_read_json(Path(args.futures_outcomes)),
        horizon=max(args.horizon, 1),
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
