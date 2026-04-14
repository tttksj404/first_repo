#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import product
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent.parent / "quant_runtime" / "historical"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "quant_runtime" / "artifacts" / "carry_basis_strategy_scan.json"
ROUND_TRIP_COST_BPS = 14.0


@dataclass(frozen=True)
class CarryTrade:
    symbol: str
    side: str
    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    price_pnl_bps: float
    funding_pnl_bps: float
    gross_pnl_bps: float
    net_pnl_bps: float
    exit_reason: str


@dataclass(frozen=True)
class CarryResult:
    symbol: str
    funding_threshold: float
    basis_threshold_bps: float
    hold_hours: int
    stop_bps: float
    tp_bps: float
    exit_mode: str
    trades: int
    win_rate: float
    profit_factor: float
    total_return_bps: float
    avg_trade_bps: float
    max_drawdown_bps: float
    avg_funding_capture_bps: float
    positive_folds: int = 0
    stressed_profit_factor: float = 0.0
    stressed_total_return_bps: float = 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "funding_threshold": self.funding_threshold,
            "basis_threshold_bps": self.basis_threshold_bps,
            "hold_hours": self.hold_hours,
            "stop_bps": self.stop_bps,
            "tp_bps": self.tp_bps,
            "exit_mode": self.exit_mode,
            "trades": self.trades,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 4),
            "total_return_bps": round(self.total_return_bps, 2),
            "avg_trade_bps": round(self.avg_trade_bps, 2),
            "max_drawdown_bps": round(self.max_drawdown_bps, 2),
            "avg_funding_capture_bps": round(self.avg_funding_capture_bps, 2),
            "positive_folds": self.positive_folds,
            "stressed_profit_factor": round(self.stressed_profit_factor, 4),
            "stressed_total_return_bps": round(self.stressed_total_return_bps, 2),
        }


def _load_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _discover_symbols() -> list[str]:
    symbols = []
    for symbol_dir in sorted(DATA_DIR.iterdir()):
        if not symbol_dir.is_dir():
            continue
        if (symbol_dir / "1h.json").exists() and (symbol_dir / "spot_1h.json").exists() and (symbol_dir / "funding_rates.json").exists():
            symbols.append(symbol_dir.name)
    return symbols


def _build_symbol_bundle(symbol: str) -> tuple[list[dict], dict[int, float]]:
    futures_rows = _load_json(DATA_DIR / symbol / "1h.json")
    spot_rows = _load_json(DATA_DIR / symbol / "spot_1h.json")
    funding_rows = _load_json(DATA_DIR / symbol / "funding_rates.json")
    if not futures_rows or not spot_rows or not funding_rows:
        return [], {}
    spot_map = {int(row["open_time"]): float(row["close_price"]) for row in spot_rows}
    aligned = []
    for row in futures_rows:
        ts = int(row["open_time"])
        spot_close = spot_map.get(ts)
        if spot_close is None or spot_close <= 0:
            continue
        futures_close = float(row["close_price"])
        aligned.append(
            {
                "open_time": ts,
                "open": float(row["open_price"]),
                "high": float(row["high_price"]),
                "low": float(row["low_price"]),
                "close": futures_close,
                "spot_close": spot_close,
                "basis_bps": (futures_close / spot_close - 1.0) * 10000.0,
            }
        )
    funding_map = {int(row["funding_time"]): float(row["funding_rate"]) for row in funding_rows}
    return aligned, funding_map


def _event_funding_pnl_bps(side: str, funding_rate: float) -> float:
    direction = 1.0 if side == "long" else -1.0
    return -direction * funding_rate * 10000.0


def _max_drawdown_bps(pnls: list[float]) -> float:
    running = 0.0
    peak = 0.0
    worst = 0.0
    for pnl in pnls:
        running += pnl
        peak = max(peak, running)
        worst = min(worst, running - peak)
    return abs(worst)


def _profit_factor(pnls: list[float]) -> float:
    gains = sum(value for value in pnls if value > 0)
    losses = abs(sum(value for value in pnls if value < 0))
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def _backtest_bundle(
    symbol: str,
    bundle: list[dict],
    funding_map: dict[int, float],
    *,
    funding_threshold: float,
    basis_threshold_bps: float,
    hold_hours: int,
    stop_bps: float,
    tp_bps: float,
    exit_mode: str,
) -> list[CarryTrade]:
    trades: list[CarryTrade] = []
    if len(bundle) < hold_hours + 2:
        return trades
    index_by_time = {row["open_time"]: idx for idx, row in enumerate(bundle)}
    funding_times = sorted(ts for ts in funding_map if ts in index_by_time)
    cooldown_until_idx = -1
    for event_time in funding_times:
        entry_signal_idx = index_by_time[event_time]
        if entry_signal_idx <= cooldown_until_idx or entry_signal_idx + 1 >= len(bundle):
            continue
        funding_rate = funding_map[event_time]
        if abs(funding_rate) < funding_threshold:
            continue
        signal_row = bundle[entry_signal_idx]
        basis_bps = signal_row["basis_bps"]
        if funding_rate > 0 and basis_bps < basis_threshold_bps:
            continue
        if funding_rate < 0 and basis_bps > -basis_threshold_bps:
            continue
        side = "short" if funding_rate > 0 else "long"
        entry_idx = entry_signal_idx + 1
        entry_row = bundle[entry_idx]
        entry_price = entry_row["open"]
        stop_price = entry_price * (1.0 - stop_bps / 10000.0) if side == "long" else entry_price * (1.0 + stop_bps / 10000.0)
        tp_price = entry_price * (1.0 + tp_bps / 10000.0) if side == "long" else entry_price * (1.0 - tp_bps / 10000.0)
        exit_idx = min(entry_idx + hold_hours, len(bundle) - 1)
        exit_reason = "time"
        for idx in range(entry_idx, min(entry_idx + hold_hours, len(bundle) - 1) + 1):
            row = bundle[idx]
            if side == "long":
                if row["low"] <= stop_price:
                    exit_idx = idx
                    exit_reason = "stop"
                    break
                if row["high"] >= tp_price:
                    exit_idx = idx
                    exit_reason = "tp"
                    break
            else:
                if row["high"] >= stop_price:
                    exit_idx = idx
                    exit_reason = "stop"
                    break
                if row["low"] <= tp_price:
                    exit_idx = idx
                    exit_reason = "tp"
                    break
            if exit_mode == "basis_revert" and abs(row["basis_bps"]) <= max(2.0, basis_threshold_bps * 0.25):
                exit_idx = idx
                exit_reason = "basis_revert"
                break
        exit_row = bundle[exit_idx]
        if exit_reason == "stop":
            exit_price = stop_price
        elif exit_reason == "tp":
            exit_price = tp_price
        else:
            exit_price = exit_row["close"]
        if side == "long":
            price_pnl_bps = (exit_price / entry_price - 1.0) * 10000.0
        else:
            price_pnl_bps = (entry_price / exit_price - 1.0) * 10000.0
        funding_pnl_bps = 0.0
        for funding_time_inner, funding_rate_inner in funding_map.items():
            if entry_row["open_time"] < funding_time_inner <= exit_row["open_time"]:
                funding_pnl_bps += _event_funding_pnl_bps(side, funding_rate_inner)
        gross_pnl_bps = price_pnl_bps + funding_pnl_bps
        net_pnl_bps = gross_pnl_bps - ROUND_TRIP_COST_BPS
        trades.append(
            CarryTrade(
                symbol=symbol,
                side=side,
                entry_time=entry_row["open_time"],
                exit_time=exit_row["open_time"],
                entry_price=entry_price,
                exit_price=exit_price,
                price_pnl_bps=price_pnl_bps,
                funding_pnl_bps=funding_pnl_bps,
                gross_pnl_bps=gross_pnl_bps,
                net_pnl_bps=net_pnl_bps,
                exit_reason=exit_reason,
            )
        )
        cooldown_until_idx = exit_idx
    return trades


def _repriced_trade_pnls(trades: list[CarryTrade], *, round_trip_cost_bps: float) -> list[float]:
    return [trade.gross_pnl_bps - round_trip_cost_bps for trade in trades]


def _walk_forward_positive_folds(trades: list[CarryTrade], *, round_trip_cost_bps: float, folds: int = 4) -> int:
    if len(trades) < folds:
        return 0
    ordered = sorted(trades, key=lambda trade: trade.entry_time)
    fold_size = max(1, len(ordered) // folds)
    positive = 0
    for fold_index in range(folds):
        start = fold_index * fold_size
        end = len(ordered) if fold_index == folds - 1 else min(len(ordered), (fold_index + 1) * fold_size)
        subset = ordered[start:end]
        if not subset:
            continue
        pnl = sum(trade.gross_pnl_bps - round_trip_cost_bps for trade in subset)
        if pnl > 0:
            positive += 1
    return positive


def main() -> int:
    raw_rows: list[tuple[CarryResult, list[CarryTrade]]] = []
    symbols = _discover_symbols()
    for symbol in symbols:
        bundle, funding_map = _build_symbol_bundle(symbol)
        if not bundle:
            continue
        for funding_threshold, basis_threshold_bps, hold_hours, stop_bps, tp_bps, exit_mode in product(
            (0.00005, 0.0001, 0.00015),
            (5.0, 10.0, 20.0),
            (8, 16, 24),
            (60.0, 100.0),
            (80.0, 160.0),
            ("time", "basis_revert"),
        ):
            trades = _backtest_bundle(
                symbol,
                bundle,
                funding_map,
                funding_threshold=funding_threshold,
                basis_threshold_bps=basis_threshold_bps,
                hold_hours=hold_hours,
                stop_bps=stop_bps,
                tp_bps=tp_bps,
                exit_mode=exit_mode,
            )
            if not trades:
                continue
            pnls = [trade.net_pnl_bps for trade in trades]
            wins = sum(1 for value in pnls if value > 0)
            avg_funding_capture = sum(trade.funding_pnl_bps for trade in trades) / len(trades)
            raw_rows.append((
                CarryResult(
                    symbol=symbol,
                    funding_threshold=funding_threshold,
                    basis_threshold_bps=basis_threshold_bps,
                    hold_hours=hold_hours,
                    stop_bps=stop_bps,
                    tp_bps=tp_bps,
                    exit_mode=exit_mode,
                    trades=len(trades),
                    win_rate=wins / len(trades),
                    profit_factor=_profit_factor(pnls),
                    total_return_bps=sum(pnls),
                    avg_trade_bps=sum(pnls) / len(pnls),
                    max_drawdown_bps=_max_drawdown_bps(pnls),
                    avg_funding_capture_bps=avg_funding_capture,
                ),
                trades,
            ))
    raw_rows.sort(key=lambda item: (item[0].total_return_bps, item[0].profit_factor, item[0].avg_trade_bps), reverse=True)
    validated_top_results: list[dict[str, object]] = []
    for base_result, trades in raw_rows[:20]:
        stressed_pnls = _repriced_trade_pnls(trades, round_trip_cost_bps=24.0)
        stressed_pf = _profit_factor(stressed_pnls)
        stressed_total = sum(stressed_pnls)
        positive_folds = _walk_forward_positive_folds(trades, round_trip_cost_bps=ROUND_TRIP_COST_BPS)
        enriched = CarryResult(
            symbol=base_result.symbol,
            funding_threshold=base_result.funding_threshold,
            basis_threshold_bps=base_result.basis_threshold_bps,
            hold_hours=base_result.hold_hours,
            stop_bps=base_result.stop_bps,
            tp_bps=base_result.tp_bps,
            exit_mode=base_result.exit_mode,
            trades=base_result.trades,
            win_rate=base_result.win_rate,
            profit_factor=base_result.profit_factor,
            total_return_bps=base_result.total_return_bps,
            avg_trade_bps=base_result.avg_trade_bps,
            max_drawdown_bps=base_result.max_drawdown_bps,
            avg_funding_capture_bps=base_result.avg_funding_capture_bps,
            positive_folds=positive_folds,
            stressed_profit_factor=stressed_pf,
            stressed_total_return_bps=stressed_total,
        )
        trade_summary = [
            {
                "entry_time": trade.entry_time,
                "exit_time": trade.exit_time,
                "side": trade.side,
                "gross_pnl_bps": round(trade.gross_pnl_bps, 2),
                "net_pnl_bps": round(trade.net_pnl_bps, 2),
                "exit_reason": trade.exit_reason,
            }
            for trade in trades[:5]
        ]
        validated_payload = {
            **enriched.as_dict(),
            "cost_stress": {
                "baseline_bps": ROUND_TRIP_COST_BPS,
                "stress_bps": 24.0,
            },
            "sample_trades": trade_summary,
        }
        validated_top_results.append(validated_payload)
    results: list[dict[str, object]] = []
    for index, (row, trades) in enumerate(raw_rows[:30]):
        if index < len(validated_top_results):
            results.append(validated_top_results[index])
            continue
        fallback = row.as_dict()
        fallback["cost_stress"] = {
            "baseline_bps": ROUND_TRIP_COST_BPS,
            "stress_bps": 24.0,
        }
        fallback["sample_trades"] = [
            {
                "entry_time": trade.entry_time,
                "exit_time": trade.exit_time,
                "side": trade.side,
                "gross_pnl_bps": round(trade.gross_pnl_bps, 2),
                "net_pnl_bps": round(trade.net_pnl_bps, 2),
                "exit_reason": trade.exit_reason,
            }
            for trade in trades[:3]
        ]
        results.append(fallback)
    payload = {
        "generated_by": "carry_basis_strategy_scan",
        "symbols_tested": symbols,
        "combo_count": len(raw_rows),
        "top_results": results,
        "validated_top_results": validated_top_results,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=" * 100)
    print("CARRY / BASIS STRATEGY SCAN")
    print("=" * 100)
    print(f"symbols tested: {', '.join(symbols)}")
    print(f"combos tested: {len(raw_rows)}")
    print(f"saved: {OUTPUT_PATH}")
    print()
    for item, _ in raw_rows[:15]:
        positive_folds = _walk_forward_positive_folds(_, round_trip_cost_bps=ROUND_TRIP_COST_BPS)
        stressed_total = sum(_repriced_trade_pnls(_, round_trip_cost_bps=24.0))
        print(
            f"{item.symbol:<10} funding>={item.funding_threshold:>7.5f} basis>={item.basis_threshold_bps:>5.1f}bps "
            f"hold={item.hold_hours:>2}h stop={item.stop_bps:>5.0f} tp={item.tp_bps:>5.0f} "
            f"exit={item.exit_mode:<11} n={item.trades:>3} WR={item.win_rate*100:>5.1f}% "
            f"PF={item.profit_factor:>5.2f} total={item.total_return_bps:+8.1f}bps "
            f"MDD={item.max_drawdown_bps:>7.1f} funding={item.avg_funding_capture_bps:+6.1f} "
            f"WF={positive_folds}/4 stress24={stressed_total:+7.1f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
