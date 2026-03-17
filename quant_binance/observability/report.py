from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
import shutil

from quant_binance.models import DecisionIntent
from quant_binance.observability.log_store import _json_ready


def _active_exchange_futures_positions(
    live_positions: list[dict[str, object]] | tuple[dict[str, object], ...] | None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for position in live_positions or []:
        total = float(position.get("total") or position.get("available") or 0.0)
        if total <= 0.0:
            continue
        rows.append(dict(position))
    return rows


def _futures_position_sync_payload(
    *,
    open_futures_positions: list[dict[str, object]] | None,
    live_positions: list[dict[str, object]] | tuple[dict[str, object], ...] | None,
) -> dict[str, object]:
    paper_open_futures_positions = list(open_futures_positions or [])
    exchange_live_futures_positions = _active_exchange_futures_positions(live_positions)
    adopted_futures_positions = [
        dict(position)
        for position in paper_open_futures_positions
        if str(position.get("origin", "")).strip().lower() == "adopted"
        or bool(position.get("adopted_at"))
        or bool(position.get("adoption_source"))
    ]
    paper_symbols = {
        str(position.get("symbol", ""))
        for position in paper_open_futures_positions
        if str(position.get("symbol", ""))
    }
    exchange_symbols = {
        str(position.get("symbol", ""))
        for position in exchange_live_futures_positions
        if str(position.get("symbol", ""))
    }
    missing_in_paper = sorted(exchange_symbols - paper_symbols)
    missing_on_exchange = sorted(paper_symbols - exchange_symbols)
    mismatch_details = {
        "missing_in_paper": missing_in_paper,
        "missing_on_exchange": missing_on_exchange,
    }
    pending_external_futures_positions = [
        dict(position)
        for position in exchange_live_futures_positions
        if str(position.get("symbol", "")) in set(missing_in_paper)
    ]
    return {
        "paper_open_futures_positions": paper_open_futures_positions,
        "paper_open_futures_position_count": len(paper_open_futures_positions),
        "adopted_futures_positions": adopted_futures_positions,
        "adopted_futures_position_count": len(adopted_futures_positions),
        "exchange_live_futures_positions": exchange_live_futures_positions,
        "exchange_live_futures_position_count": len(exchange_live_futures_positions),
        "pending_external_futures_positions": pending_external_futures_positions,
        "pending_external_futures_position_count": len(pending_external_futures_positions),
        "futures_position_mismatch": bool(missing_in_paper or missing_on_exchange),
        "futures_position_mismatch_details": mismatch_details,
    }


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




def _aggregate_live_order_outcomes(live_orders: list[dict[str, object]] | tuple[dict[str, object], ...] | None) -> dict[str, object]:
    orders = list(live_orders or [])
    if not orders:
        return {
            "execution_outcome_counts": {},
            "accepted_live_order_count": 0,
            "rejected_live_order_count": 0,
            "avg_fill_ratio": 0.0,
            "avg_slippage_bps": 0.0,
            "avg_realized_edge_bps": 0.0,
            "avg_expected_edge_bps": 0.0,
            "realized_vs_expected_edge_gap_bps": 0.0,
            "execution_audit_by_symbol": [],
        }

    counts = Counter()
    accepted = 0
    rejected = 0
    fill_ratio_sum = 0.0
    slippage_values: list[float] = []
    realized_edge_values: list[float] = []
    expected_edge_values: list[float] = []
    by_symbol: dict[str, dict[str, float | int | str]] = defaultdict(
        lambda: {
            "symbol": "",
            "live_order_count": 0,
            "accepted_count": 0,
            "rejected_count": 0,
            "avg_fill_ratio": 0.0,
            "avg_slippage_bps": 0.0,
            "avg_realized_edge_bps": 0.0,
            "avg_expected_edge_bps": 0.0,
            "realized_vs_expected_edge_gap_bps": 0.0,
        }
    )
    fill_sums: dict[str, float] = defaultdict(float)
    slip_sums: dict[str, float] = defaultdict(float)
    slip_counts: dict[str, int] = defaultdict(int)
    realized_sums: dict[str, float] = defaultdict(float)
    realized_counts: dict[str, int] = defaultdict(int)
    expected_sums: dict[str, float] = defaultdict(float)

    for order in orders:
        status = str(order.get("fill_status") or ("accepted" if order.get("accepted") else "reject") or "unknown")
        symbol = str(order.get("symbol", ""))
        counts[status] += 1
        row = by_symbol[symbol]
        row["symbol"] = symbol
        row["live_order_count"] = int(row["live_order_count"]) + 1

        accepted_flag = bool(order.get("accepted", False))
        if accepted_flag:
            accepted += 1
            row["accepted_count"] = int(row["accepted_count"]) + 1
        else:
            rejected += 1
            row["rejected_count"] = int(row["rejected_count"]) + 1

        fill_ratio = float(order.get("fill_ratio", 0.0) or 0.0)
        fill_ratio_sum += fill_ratio
        fill_sums[symbol] += fill_ratio

        slippage = order.get("slippage_bps")
        if slippage is not None:
            slip = float(slippage or 0.0)
            slippage_values.append(slip)
            slip_sums[symbol] += slip
            slip_counts[symbol] += 1

        realized = order.get("realized_edge_bps")
        if realized is not None:
            realized_value = float(realized or 0.0)
            realized_edge_values.append(realized_value)
            realized_sums[symbol] += realized_value
            realized_counts[symbol] += 1

        expected = float(order.get("expected_net_edge_bps", order.get("net_expected_edge_bps", 0.0)) or 0.0)
        expected_edge_values.append(expected)
        expected_sums[symbol] += expected

    rows: list[dict[str, object]] = []
    for symbol, row in by_symbol.items():
        count = int(row["live_order_count"])
        expected_avg = expected_sums[symbol] / count if count else 0.0
        realized_avg = realized_sums[symbol] / realized_counts[symbol] if realized_counts[symbol] else 0.0
        row["avg_fill_ratio"] = round(fill_sums[symbol] / count, 6) if count else 0.0
        row["avg_slippage_bps"] = round(slip_sums[symbol] / slip_counts[symbol], 6) if slip_counts[symbol] else 0.0
        row["avg_realized_edge_bps"] = round(realized_avg, 6)
        row["avg_expected_edge_bps"] = round(expected_avg, 6)
        row["realized_vs_expected_edge_gap_bps"] = round(realized_avg - expected_avg, 6)
        rows.append(dict(row))
    rows.sort(key=lambda item: (float(item["realized_vs_expected_edge_gap_bps"]), float(item["avg_realized_edge_bps"])), reverse=True)

    avg_expected = sum(expected_edge_values) / len(expected_edge_values) if expected_edge_values else 0.0
    avg_realized = sum(realized_edge_values) / len(realized_edge_values) if realized_edge_values else 0.0
    return {
        "execution_outcome_counts": dict(sorted(counts.items())),
        "accepted_live_order_count": accepted,
        "rejected_live_order_count": rejected,
        "avg_fill_ratio": round(fill_ratio_sum / len(orders), 6),
        "avg_slippage_bps": round(sum(slippage_values) / len(slippage_values), 6) if slippage_values else 0.0,
        "avg_realized_edge_bps": round(avg_realized, 6),
        "avg_expected_edge_bps": round(avg_expected, 6),
        "realized_vs_expected_edge_gap_bps": round(avg_realized - avg_expected, 6),
        "execution_audit_by_symbol": rows,
    }

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
    telegram_alerts: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    live_positions: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    self_healing: dict[str, object] | None = None,
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
    futures_position_sync = _futures_position_sync_payload(
        open_futures_positions=open_futures_positions,
        live_positions=live_positions,
    )
    execution_outcomes = _aggregate_live_order_outcomes(live_orders)
    rejection_counts = Counter()
    for decision in decisions:
        for reason in decision.rejection_reasons:
            rejection_counts[reason] += 1
    recent_decisions = [
        {
            "symbol": decision.symbol,
            "candidate_mode": decision.candidate_mode,
            "mode": decision.final_mode,
            "side": decision.side,
            "score": round(decision.predictability_score, 2),
            "net_expected_edge_bps": round(decision.net_expected_edge_bps, 6),
            "estimated_round_trip_cost_bps": round(decision.estimated_round_trip_cost_bps, 6),
            "macro_trade_restraint": decision.macro_trade_restraint,
            "execution_quality_trade_restraint": decision.execution_quality_trade_restraint,
            "strategy_size_multiplier": round(decision.strategy_size_multiplier, 6),
            "entry_relaxations": list(decision.entry_relaxation_reasons[:4]),
            "size_boost_reasons": list(decision.size_boost_reasons[:4]),
            "reasons": list(decision.rejection_reasons[:4]),
        }
        for decision in list(decisions)[-5:]
    ]
    return {
        "decision_count": len(decisions),
        "modes": [decision.final_mode for decision in decisions],
        "symbols": sorted({decision.symbol for decision in decisions}),
        "observe_only_symbols": combined_observe_only,
        "open_spot_positions": list(open_spot_positions or []),
        "open_futures_positions": list(open_futures_positions or []),
        "live_positions": list(live_positions or []),
        **futures_position_sync,
        "closed_trades": list(closed_trades or []),
        "telegram_alerts": list(telegram_alerts or []),
        "recent_decisions": recent_decisions,
        "major_entry_relaxation_count": sum(1 for decision in decisions if decision.entry_relaxation_reasons),
        "major_size_boost_count": sum(1 for decision in decisions if decision.size_boost_reasons),
        "top_rejection_reasons": dict(rejection_counts.most_common(8)),
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
        **execution_outcomes,
        "account_snapshot": account_snapshot or {},
        "open_orders_snapshot": open_orders_snapshot or {},
        "capital_report": capital_report or {},
        "kill_switch": kill_switch_status or {"armed": False, "reasons": []},
        "self_healing": self_healing or {},
    }


def write_runtime_summary(path: str | Path, summary: dict[str, object]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(_json_ready(summary), indent=2, sort_keys=True), encoding="utf-8")
    latest_root = output_path.parent.parent / "latest"
    latest_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output_path, latest_root / "summary.json")
