from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from quant_binance.models import DecisionIntent
from quant_binance.observability.log_store import _json_ready


def _aggregate_closed_trades(closed_trades: list[dict[str, object]] | tuple[dict[str, object], ...]) -> tuple[list[dict[str, object]], dict[str, int], float]:
    by_symbol: dict[str, dict[str, float | int | str]] = defaultdict(
        lambda: {
            "symbol": "",
            "market": "",
            "trade_count": 0,
            "realized_pnl_usd_estimate": 0.0,
            "average_return_bps_estimate": 0.0,
        }
    )
    return_sums: dict[str, float] = defaultdict(float)
    exit_reasons = Counter()
    total_realized = 0.0
    for trade in closed_trades:
        symbol = str(trade.get("symbol", ""))
        market = str(trade.get("market", ""))
        pnl = float(trade.get("realized_pnl_usd_estimate", 0.0))
        bps = float(trade.get("realized_return_bps_estimate", 0.0))
        reason = str(trade.get("exit_reason", ""))
        row = by_symbol[symbol]
        row["symbol"] = symbol
        row["market"] = market
        row["trade_count"] = int(row["trade_count"]) + 1
        row["realized_pnl_usd_estimate"] = float(row["realized_pnl_usd_estimate"]) + pnl
        return_sums[symbol] += bps
        total_realized += pnl
        if reason:
            exit_reasons[reason] += 1
    rows: list[dict[str, object]] = []
    for symbol, row in by_symbol.items():
        count = int(row["trade_count"])
        rows.append(
            {
                "symbol": row["symbol"],
                "market": row["market"],
                "trade_count": count,
                "realized_pnl_usd_estimate": round(float(row["realized_pnl_usd_estimate"]), 6),
                "average_return_bps_estimate": round(return_sums[symbol] / count, 6) if count else 0.0,
            }
        )
    rows.sort(key=lambda item: (-float(item["realized_pnl_usd_estimate"]), str(item["symbol"])))
    return rows, dict(sorted(exit_reasons.items())), round(total_realized, 6)


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
    open_spot_positions: list[dict[str, object]] | None = None,
    open_futures_positions: list[dict[str, object]] | None = None,
    closed_trades: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
) -> dict[str, object]:
    derived_observe_only = {
        decision.symbol
        for decision in decisions
        if "OBSERVE_ONLY_SYMBOL" in decision.rejection_reasons
    }
    combined_observe_only = sorted(set(observe_only_symbols or []).union(derived_observe_only))
    symbol_performance, exit_reason_counts, realized_total = _aggregate_closed_trades(closed_trades or [])
    unrealized_spot_total = round(
        sum(float(position.get("unrealized_pnl_usd_estimate", 0.0)) for position in (open_spot_positions or [])),
        6,
    )
    unrealized_futures_total = round(
        sum(float(position.get("unrealized_pnl_usd_estimate", 0.0)) for position in (open_futures_positions or [])),
        6,
    )
    return {
        "decision_count": len(decisions),
        "modes": [decision.final_mode for decision in decisions],
        "symbols": sorted({decision.symbol for decision in decisions}),
        "observe_only_symbols": combined_observe_only,
        "open_spot_positions": list(open_spot_positions or []),
        "open_futures_positions": list(open_futures_positions or []),
        "closed_trades": list(closed_trades or []),
        "exit_reason_counts": exit_reason_counts,
        "symbol_performance": symbol_performance,
        "realized_pnl_usd_estimate": realized_total,
        "unrealized_pnl_usd_estimate": round(unrealized_spot_total + unrealized_futures_total, 6),
        "unrealized_spot_pnl_usd_estimate": unrealized_spot_total,
        "unrealized_futures_pnl_usd_estimate": unrealized_futures_total,
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
    output_path.write_text(json.dumps(_json_ready(summary), indent=2, sort_keys=True), encoding="utf-8")
