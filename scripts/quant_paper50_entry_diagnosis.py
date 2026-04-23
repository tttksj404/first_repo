#!/usr/bin/env python3
"""Diagnose whether paper50 entry filters are too narrow or too broad.

This consumes local paper50 artifacts only. It does not contact an exchange and
does not place, test, cancel, or modify orders.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_BASE = Path("quant_runtime_paper50")
DEFAULT_COUNTERFACTUAL = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_counterfactual_latest.json"
DEFAULT_OVERVIEW = DEFAULT_OUTPUT_BASE / "output" / "paper-live-shell" / "latest" / "overview.json"
DEFAULT_FILTERS = DEFAULT_OUTPUT_BASE / "paper50_multi_symbol_filters.json"
DEFAULT_OUTPUT = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_entry_diagnosis_latest.json"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _label_counts(counterfactual: dict[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for summary in dict(counterfactual.get("symbol_summaries") or {}).values():
        counts.update(dict(summary.get("label_counts") or {}))
    return counts


def _recent_mode_counts(overview: dict[str, Any]) -> Counter[str]:
    recent = list(overview.get("recent_decisions") or [])
    return Counter(str(row.get("mode") or "unknown").lower() for row in recent)


def _recent_cash_ratio(overview: dict[str, Any]) -> float | None:
    recent = list(overview.get("recent_decisions") or [])
    if not recent:
        return None
    mode_counts = _recent_mode_counts(overview)
    return round(mode_counts.get("cash", 0) / len(recent), 6)


def _recent_futures_symbols(overview: dict[str, Any]) -> list[str]:
    symbols = {
        str(row.get("symbol") or "").upper()
        for row in list(overview.get("recent_decisions") or [])
        if str(row.get("mode") or "").lower() == "futures"
    }
    return sorted(symbol for symbol in symbols if symbol)


def _load_decision_rows(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _current_entry_activity(overview: dict[str, Any], decision_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = decision_rows or list(overview.get("recent_decisions") or [])
    futures_rows = [
        row
        for row in rows
        if str(row.get("final_mode") or row.get("mode") or "").lower() == "futures"
        and str(row.get("side") or "").lower() in {"long", "short"}
        and not bool(row.get("rejected", False))
    ]
    executable_rows = [row for row in futures_rows if _safe_float(row.get("order_intent_notional_usd")) > 0.0]
    zero_notional_rows = [row for row in futures_rows if _safe_float(row.get("order_intent_notional_usd")) <= 0.0]
    return {
        "sample_count": len(rows),
        "futures_signal_count": len(futures_rows),
        "executable_futures_count": len(executable_rows),
        "zero_notional_futures_count": len(zero_notional_rows),
        "futures_symbols": sorted({str(row.get("symbol") or "").upper() for row in futures_rows if row.get("symbol")}),
        "executable_futures_symbols": sorted(
            {str(row.get("symbol") or "").upper() for row in executable_rows if row.get("symbol")}
        ),
    }


def _symbol_profile(filters: dict[str, Any], symbol: str) -> dict[str, Any]:
    profile = dict((filters.get("symbol_filter_profiles") or {}).get(symbol) or {})
    fields = (
        "min_predictability_score",
        "min_liquidity_score",
        "min_volume_confirmation",
        "min_net_edge_bps",
        "min_edge_to_cost",
        "min_expected_profit_multiplier",
        "max_stop_distance_bps",
    )
    return {field: profile[field] for field in fields if field in profile}


def _symbol_verdict(
    symbol: str,
    summary: dict[str, Any],
    filters: dict[str, Any],
    *,
    min_symbol_decisions: int,
    miss_rate_threshold: float,
) -> dict[str, Any]:
    decision_count = _safe_int(summary.get("decision_count"))
    label_counts = dict(summary.get("label_counts") or {})
    possible = _safe_int(label_counts.get("possible_missed_entry"))
    watch = _safe_int(label_counts.get("watch_marginal_miss"))
    confirmed = _safe_int(label_counts.get("confirmed_block"))
    valid = _safe_int(label_counts.get("valid_block"))
    miss_rate = possible / decision_count if decision_count else 0.0
    broadening_risk_rate = (confirmed + valid) / decision_count if decision_count else 0.0

    if decision_count < min_symbol_decisions:
        verdict = "insufficient_data"
        action = "collect_more_forward_outcomes"
    elif possible >= 2 and miss_rate >= miss_rate_threshold:
        verdict = "too_conservative"
        action = "relax_symbol_filters_one_step"
    elif possible >= 1 or watch >= 3:
        verdict = "mildly_conservative"
        action = "watch_then_relax_if_repeated"
    elif broadening_risk_rate >= 0.65:
        verdict = "do_not_broaden"
        action = "hold_or_tighten_if_orders_appear"
    else:
        verdict = "balanced_or_unclear"
        action = "keep_collecting"

    return {
        "symbol": symbol,
        "decision_count": decision_count,
        "label_counts": label_counts,
        "miss_rate": round(miss_rate, 6),
        "broadening_risk_rate": round(broadening_risk_rate, 6),
        "avg_net_after_cost_bps": summary.get("avg_net_after_cost_bps"),
        "best_net_after_cost_bps": summary.get("best_net_after_cost_bps"),
        "worst_net_after_cost_bps": summary.get("worst_net_after_cost_bps"),
        "counterfactual_verdict": summary.get("verdict"),
        "posture": verdict,
        "recommended_action": action,
        "current_profile": _symbol_profile(filters, symbol),
    }


def build_diagnosis(
    *,
    counterfactual: dict[str, Any],
    overview: dict[str, Any],
    filters: dict[str, Any],
    decision_rows: list[dict[str, Any]] | None = None,
    min_decisions: int = 60,
    min_symbol_decisions: int = 10,
    miss_rate_threshold: float = 0.08,
) -> dict[str, Any]:
    label_counts = _label_counts(counterfactual)
    evaluated_decisions = _safe_int(counterfactual.get("decision_count"))
    runtime_decisions = _safe_int(overview.get("decision_count"))
    possible = _safe_int(counterfactual.get("possible_missed_entry_count"))
    watch = _safe_int(label_counts.get("watch_marginal_miss"))
    confirmed = _safe_int(label_counts.get("confirmed_block"))
    valid = _safe_int(label_counts.get("valid_block"))
    live_orders = _safe_int(overview.get("live_order_count"))
    tested_orders = _safe_int(overview.get("tested_order_count"))
    order_count = live_orders + tested_orders
    possible_rate = possible / evaluated_decisions if evaluated_decisions else 0.0
    broadening_risk_rate = (confirmed + valid) / evaluated_decisions if evaluated_decisions else 0.0
    recent_cash_ratio = _recent_cash_ratio(overview)
    recent_decisions = list(overview.get("recent_decisions") or [])
    recent_mode_counts = _recent_mode_counts(overview)
    recent_futures_count = _safe_int(recent_mode_counts.get("futures"))
    recent_futures_ratio = recent_futures_count / len(recent_decisions) if recent_decisions else 0.0
    recent_futures_symbols = _recent_futures_symbols(overview)
    paper_pnl = _safe_float(overview.get("realized_pnl_usd_estimate")) + _safe_float(overview.get("unrealized_pnl_usd_estimate"))
    entry_activity = _current_entry_activity(overview, decision_rows or [])
    executable_futures_count = _safe_int(entry_activity.get("executable_futures_count"))

    if executable_futures_count > 0 and paper_pnl < 0.0:
        posture = "too_broad_risk"
        entry_width = "possibly_too_wide"
    elif executable_futures_count > 0 or order_count > 0:
        posture = "active_entries_pending_outcome"
        entry_width = "not_too_narrow_now"
    elif _safe_int(entry_activity.get("futures_signal_count")) > 0:
        posture = "signals_pending_sizing"
        entry_width = "signal_open_but_not_executable"
    elif evaluated_decisions < min_decisions:
        posture = "insufficient_data"
        entry_width = "unknown"
    elif order_count == 0 and possible >= 2 and possible_rate >= miss_rate_threshold:
        posture = "too_conservative"
        entry_width = "too_narrow"
    elif broadening_risk_rate >= 0.75 and possible == 0:
        posture = "selective_not_broad"
        entry_width = "not_too_wide"
    else:
        posture = "balanced_or_unclear"
        entry_width = "unclear"

    symbol_summaries = dict(counterfactual.get("symbol_summaries") or {})
    symbol_diagnostics = [
        _symbol_verdict(
            symbol,
            dict(summary),
            filters,
            min_symbol_decisions=min_symbol_decisions,
            miss_rate_threshold=miss_rate_threshold,
        )
        for symbol, summary in sorted(symbol_summaries.items())
    ]
    priority_symbols = [
        row["symbol"]
        for row in sorted(
            symbol_diagnostics,
            key=lambda item: (item["posture"] != "too_conservative", -float(item["miss_rate"])),
        )
        if row["posture"] in {"too_conservative", "mildly_conservative"}
    ]

    recommendations: list[str] = []
    if posture == "active_entries_pending_outcome":
        recommendations.append("Do not loosen further until these live-paper entries have forward-return evidence.")
    elif posture == "too_conservative":
        recommendations.append("Keep broad strategy gates intact, but relax only repeated symbol-level blockers by one bounded step.")
    if broadening_risk_rate >= 0.45:
        recommendations.append("Do not loosen all symbols at once; many blocked candidates still look correctly rejected.")
    if order_count == 0:
        recommendations.append("Continue paper-only testing until at least one post-adjustment order or another forward-return window appears.")

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "paper50_entry_width_diagnosis",
        "posture": posture,
        "entry_width": entry_width,
        "evaluated_decision_count": evaluated_decisions,
        "runtime_decision_count": runtime_decisions,
        "live_order_count": live_orders,
        "tested_order_count": tested_orders,
        "recent_cash_ratio": recent_cash_ratio,
        "recent_futures_ratio": round(recent_futures_ratio, 6),
        "recent_futures_symbols": recent_futures_symbols,
        "recent_mode_counts": dict(recent_mode_counts),
        "entry_activity": entry_activity,
        "possible_missed_entry_count": possible,
        "watch_marginal_miss_count": watch,
        "confirmed_or_valid_block_count": confirmed + valid,
        "possible_missed_rate": round(possible_rate, 6),
        "broadening_risk_rate": round(broadening_risk_rate, 6),
        "label_counts": dict(label_counts),
        "priority_symbols": priority_symbols,
        "symbol_diagnostics": symbol_diagnostics,
        "recommendations": recommendations,
        "source_times": {
            "counterfactual_generated_at": counterfactual.get("generated_at"),
            "overview_updated_at": overview.get("updated_at"),
            "last_decision_timestamp": overview.get("last_decision_timestamp"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counterfactual", default=str(DEFAULT_COUNTERFACTUAL))
    parser.add_argument("--overview", default=str(DEFAULT_OVERVIEW))
    parser.add_argument("--filters", default=str(DEFAULT_FILTERS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--decisions-path", action="append", default=[])
    parser.add_argument("--min-decisions", type=int, default=60)
    parser.add_argument("--min-symbol-decisions", type=int, default=10)
    parser.add_argument("--miss-rate-threshold", type=float, default=0.08)
    args = parser.parse_args()

    diagnosis = build_diagnosis(
        counterfactual=_read_json(Path(args.counterfactual)),
        overview=_read_json(Path(args.overview)),
        filters=_read_json(Path(args.filters)),
        decision_rows=_load_decision_rows([Path(path) for path in args.decisions_path]),
        min_decisions=max(args.min_decisions, 1),
        min_symbol_decisions=max(args.min_symbol_decisions, 1),
        miss_rate_threshold=max(args.miss_rate_threshold, 0.0),
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(diagnosis, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(diagnosis, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
