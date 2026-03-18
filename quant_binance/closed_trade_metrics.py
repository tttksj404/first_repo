from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json


@dataclass(frozen=True)
class ClosedTradeAggregate:
    closed_trade_count: int
    realized_pnl_usd: float
    exit_reason_counts: dict[str, int]
    symbol_performance: list[dict[str, object]]
    by_symbol: dict[str, dict[str, object]]


def load_closed_trades_jsonl(path: str | Path) -> list[dict[str, Any]]:
    trade_path = Path(path)
    if not trade_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in trade_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def aggregate_closed_trades(closed_trades: list[dict[str, object]] | tuple[dict[str, object], ...] | None) -> ClosedTradeAggregate:
    trades = list(closed_trades or [])
    by_symbol_raw: dict[str, dict[str, float | int | str]] = defaultdict(
        lambda: {
            "symbol": "",
            "market": "",
            "trade_count": 0,
            "realized_pnl_usd_estimate": 0.0,
            "average_return_bps_estimate": 0.0,
            "win_count": 0,
            "loss_count": 0,
        }
    )
    return_sums: dict[str, float] = defaultdict(float)
    exit_reasons = Counter()
    total_realized = 0.0

    for trade in trades:
        symbol = str(trade.get("symbol", "") or "")
        if not symbol:
            continue
        market = str(trade.get("market", "") or "")
        pnl = float(trade.get("realized_pnl_usd_estimate", 0.0) or 0.0)
        bps = float(trade.get("realized_return_bps_estimate", 0.0) or 0.0)
        reason = str(trade.get("exit_reason", "") or "")
        row = by_symbol_raw[symbol]
        row["symbol"] = symbol
        row["market"] = market
        row["trade_count"] = int(row["trade_count"]) + 1
        row["realized_pnl_usd_estimate"] = float(row["realized_pnl_usd_estimate"]) + pnl
        return_sums[symbol] += bps
        total_realized += pnl
        if pnl > 0.0:
            row["win_count"] = int(row["win_count"]) + 1
        elif pnl < 0.0:
            row["loss_count"] = int(row["loss_count"]) + 1
        if reason:
            exit_reasons[reason] += 1

    symbol_rows: list[dict[str, object]] = []
    by_symbol: dict[str, dict[str, object]] = {}
    for symbol, row in by_symbol_raw.items():
        count = int(row["trade_count"])
        realized = round(float(row["realized_pnl_usd_estimate"]), 6)
        avg_bps = round(return_sums[symbol] / count, 6) if count else 0.0
        item = {
            "symbol": row["symbol"],
            "market": row["market"],
            "trade_count": count,
            "win_count": int(row["win_count"]),
            "loss_count": int(row["loss_count"]),
            "realized_pnl_usd_estimate": realized,
            "average_return_bps_estimate": avg_bps,
        }
        symbol_rows.append(item)
        by_symbol[symbol] = item

    symbol_rows.sort(key=lambda item: (-float(item["realized_pnl_usd_estimate"]), str(item["symbol"])))
    return ClosedTradeAggregate(
        closed_trade_count=len(trades),
        realized_pnl_usd=round(total_realized, 6),
        exit_reason_counts=dict(sorted(exit_reasons.items())),
        symbol_performance=symbol_rows,
        by_symbol=by_symbol,
    )
