from __future__ import annotations

import json
from pathlib import Path

from quant_binance.models import DecisionIntent


def build_runtime_summary(
    *,
    decisions: list[DecisionIntent] | tuple[DecisionIntent, ...],
    tested_orders: list[dict[str, object]] | None = None,
    live_orders: list[dict[str, object]] | None = None,
    account_snapshot: dict[str, object] | None = None,
    open_orders_snapshot: dict[str, object] | None = None,
    capital_report: dict[str, object] | None = None,
    kill_switch_status: dict[str, object] | None = None,
    observe_only_symbols: list[str] | tuple[str, ...] | None = None,
) -> dict[str, object]:
    derived_observe_only = {
        decision.symbol
        for decision in decisions
        if "OBSERVE_ONLY_SYMBOL" in decision.rejection_reasons
    }
    combined_observe_only = sorted(set(observe_only_symbols or []).union(derived_observe_only))
    return {
        "decision_count": len(decisions),
        "modes": [decision.final_mode for decision in decisions],
        "symbols": sorted({decision.symbol for decision in decisions}),
        "observe_only_symbols": combined_observe_only,
        "tested_order_count": len(tested_orders or []),
        "tested_orders": tested_orders or [],
        "live_order_count": len(live_orders or []),
        "live_orders": live_orders or [],
        "account_snapshot": account_snapshot or {},
        "open_orders_snapshot": open_orders_snapshot or {},
        "capital_report": capital_report or {},
        "kill_switch": kill_switch_status or {"armed": False, "reasons": []},
    }


def write_runtime_summary(path: str | Path, summary: dict[str, object]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
