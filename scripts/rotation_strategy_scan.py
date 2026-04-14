#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import json
import math
import time
from dataclasses import dataclass
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import product
from pathlib import Path
from statistics import pstdev


DATA_DIR = Path(__file__).resolve().parent.parent / "quant_runtime" / "historical"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "quant_runtime" / "artifacts" / "rotation_strategy_scan.json"
CHECKPOINT_PATH = Path(__file__).resolve().parent.parent / "quant_runtime" / "artifacts" / "rotation_strategy_scan.checkpoint.json"
MAJORS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT")
ALT_EXCLUSIONS = {"BTCUSDT", "ETHUSDT", "BNBUSDT"}
ROUND_TRIP_COST_BPS = 14.0
_WORKER_CLOSES: dict[str, list[float]] = {}


@dataclass(frozen=True)
class RotationResult:
    universe: str
    score_mode: str
    lookback_hours: int
    rebalance_hours: int
    top_k: int
    require_positive: bool
    ema_filter: bool
    symbols: tuple[str, ...]
    rebalance_count: int
    average_turnover: float
    total_return_pct: float
    sharpe_like: float
    profit_factor: float
    max_drawdown_pct: float
    final_equity: float

    def as_dict(self) -> dict[str, object]:
        return {
            "universe": self.universe,
            "score_mode": self.score_mode,
            "lookback_hours": self.lookback_hours,
            "rebalance_hours": self.rebalance_hours,
            "top_k": self.top_k,
            "require_positive": self.require_positive,
            "ema_filter": self.ema_filter,
            "symbols": list(self.symbols),
            "rebalance_count": self.rebalance_count,
            "average_turnover": round(self.average_turnover, 6),
            "total_return_pct": round(self.total_return_pct, 4),
            "sharpe_like": round(self.sharpe_like, 4),
            "profit_factor": round(self.profit_factor, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "final_equity": round(self.final_equity, 6),
        }


def _load_symbol_rows(symbol: str) -> list[dict]:
    path = DATA_DIR / symbol / "1h.json"
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding="utf-8"))
    normalized = []
    for row in rows:
        normalized.append(
            {
                "open_time": int(row["open_time"]),
                "close": float(row["close_price"]),
            }
        )
    return normalized


def _discover_symbols() -> list[str]:
    symbols = []
    for path in sorted(DATA_DIR.glob("*/1h.json")):
        symbol = path.parent.name
        rows = _load_symbol_rows(symbol)
        if len(rows) >= 800:
            symbols.append(symbol)
    return symbols


def _align_hourly_closes(symbols: list[str]) -> tuple[list[int], dict[str, list[float]]]:
    series_by_symbol: dict[str, dict[int, float]] = {}
    common_times: set[int] | None = None
    for symbol in symbols:
        rows = _load_symbol_rows(symbol)
        if not rows:
            continue
        time_map = {row["open_time"]: row["close"] for row in rows}
        series_by_symbol[symbol] = time_map
        times = set(time_map)
        common_times = times if common_times is None else (common_times & times)
    if not common_times:
        return [], {}
    aligned_times = sorted(common_times)
    aligned = {symbol: [series_by_symbol[symbol][ts] for ts in aligned_times] for symbol in sorted(series_by_symbol)}
    return aligned_times, aligned


def _select_universe(name: str, available_symbols: list[str]) -> tuple[str, ...]:
    if name == "majors":
        picked = [symbol for symbol in MAJORS if symbol in available_symbols]
        return tuple(picked)
    alt_symbols = [symbol for symbol in available_symbols if symbol not in ALT_EXCLUSIONS]
    if name == "liquid_alts":
        return tuple(alt_symbols[:8])
    if name == "mixed":
        combined = [symbol for symbol in MAJORS if symbol in available_symbols]
        combined.extend(symbol for symbol in alt_symbols if symbol not in combined)
        return tuple(combined[:10])
    raise ValueError(f"unknown universe: {name}")


def _score_symbol(
    closes: list[float],
    index: int,
    *,
    lookback_hours: int,
    score_mode: str,
    ema_filter: bool,
) -> float | None:
    if index < lookback_hours or index < 48:
        return None
    current = closes[index]
    past = closes[index - lookback_hours]
    if past <= 0:
        return None
    ret = current / past - 1.0
    if ema_filter:
        ema_window = closes[index - 47 : index + 1]
        ema_value = sum(ema_window) / len(ema_window)
        if current < ema_value:
            return None
    if score_mode == "return":
        return ret
    returns = []
    for pos in range(index - lookback_hours + 1, index + 1):
        prev = closes[pos - 1]
        curr = closes[pos]
        if prev > 0:
            returns.append(curr / prev - 1.0)
    vol = pstdev(returns) if len(returns) > 1 else 0.0
    return ret / max(vol, 1e-6)


def _simulate_rotation(
    closes_by_symbol: dict[str, list[float]],
    *,
    lookback_hours: int,
    rebalance_hours: int,
    top_k: int,
    score_mode: str,
    require_positive: bool,
    ema_filter: bool,
) -> tuple[float, list[float], list[float], int]:
    equity = 1.0
    current_weights = {symbol: 0.0 for symbol in closes_by_symbol}
    hourly_returns: list[float] = []
    turnovers: list[float] = []
    rebalance_count = 0
    symbols = list(closes_by_symbol)
    length = min(len(closes) for closes in closes_by_symbol.values())
    for index in range(lookback_hours, length - 1):
        if (index - lookback_hours) % rebalance_hours == 0:
            scored: list[tuple[str, float]] = []
            for symbol in symbols:
                score = _score_symbol(
                    closes_by_symbol[symbol],
                    index,
                    lookback_hours=lookback_hours,
                    score_mode=score_mode,
                    ema_filter=ema_filter,
                )
                if score is None:
                    continue
                if require_positive and score <= 0:
                    continue
                scored.append((symbol, score))
            scored.sort(key=lambda item: item[1], reverse=True)
            selected = [symbol for symbol, _ in scored[:top_k]]
            new_weights = {symbol: 0.0 for symbol in symbols}
            if selected:
                weight = 1.0 / len(selected)
                for symbol in selected:
                    new_weights[symbol] = weight
            turnover = sum(abs(new_weights[symbol] - current_weights[symbol]) for symbol in symbols)
            cost = turnover * (ROUND_TRIP_COST_BPS / 10000.0)
            equity *= max(1.0 - cost, 0.0)
            turnovers.append(turnover)
            current_weights = new_weights
            rebalance_count += 1
        step_return = 0.0
        for symbol, weight in current_weights.items():
            if weight <= 0:
                continue
            current = closes_by_symbol[symbol][index]
            nxt = closes_by_symbol[symbol][index + 1]
            if current > 0:
                step_return += weight * (nxt / current - 1.0)
        equity *= 1.0 + step_return
        hourly_returns.append(step_return)
    return equity, hourly_returns, turnovers, rebalance_count


def _worker_init(closes_by_symbol: dict[str, list[float]]) -> None:
    global _WORKER_CLOSES
    _WORKER_CLOSES = closes_by_symbol


def _evaluate_combo_worker(params: tuple[int, int, int, str, bool, bool]) -> dict[str, object] | None:
    lookback_hours, rebalance_hours, top_k, score_mode, require_positive, ema_filter = params
    closes_by_symbol = _WORKER_CLOSES
    if top_k > len(closes_by_symbol):
        return None
    final_equity, hourly_returns, turnovers, rebalance_count = _simulate_rotation(
        closes_by_symbol,
        lookback_hours=lookback_hours,
        rebalance_hours=rebalance_hours,
        top_k=top_k,
        score_mode=score_mode,
        require_positive=require_positive,
        ema_filter=ema_filter,
    )
    if not hourly_returns:
        return None
    equity_curve = []
    running = 1.0
    for value in hourly_returns:
        running *= 1.0 + value
        equity_curve.append(running)
    mean_hourly = sum(hourly_returns) / len(hourly_returns)
    vol_hourly = pstdev(hourly_returns) if len(hourly_returns) > 1 else 0.0
    sharpe_like = mean_hourly / max(vol_hourly, 1e-9) * math.sqrt(24 * 365)
    return {
        "lookback_hours": lookback_hours,
        "rebalance_hours": rebalance_hours,
        "top_k": top_k,
        "score_mode": score_mode,
        "require_positive": require_positive,
        "ema_filter": ema_filter,
        "rebalance_count": rebalance_count,
        "average_turnover": (sum(turnovers) / len(turnovers)) if turnovers else 0.0,
        "total_return_pct": (final_equity - 1.0) * 100.0,
        "sharpe_like": sharpe_like,
        "profit_factor": _profit_factor(hourly_returns),
        "max_drawdown_pct": _max_drawdown_pct(equity_curve),
        "final_equity": final_equity,
    }


def _profit_factor(returns: list[float]) -> float:
    gains = sum(value for value in returns if value > 0)
    losses = abs(sum(value for value in returns if value < 0))
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def _max_drawdown_pct(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return abs(worst) * 100.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan cross-sectional crypto rotation strategies on cached 1h data.")
    parser.add_argument("--fast", action="store_true", help="Run a reduced combo set for quick validation.")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1), help="Parallel worker count for combo evaluation.")
    args = parser.parse_args()

    if args.fast:
        lookbacks = (24, 168)
        rebalances = (24,)
        top_ks = (1, 2)
        score_modes = ("return", "return_over_vol")
        require_positive_values = (True,)
        ema_filters = (False, True)
    else:
        lookbacks = (24, 72, 168)
        rebalances = (4, 24)
        top_ks = (1, 2, 3)
        score_modes = ("return", "return_over_vol")
        require_positive_values = (False, True)
        ema_filters = (False, True)

    available_symbols = _discover_symbols()
    results: list[RotationResult] = []
    combo_counter = 0
    started_at = time.time()
    checkpoint_payload: dict[str, object] = {
        "generated_by": "rotation_strategy_scan",
        "profile": "fast" if args.fast else "full",
        "workers": args.workers,
        "symbols_available": available_symbols,
        "universe_results": {},
    }
    for universe_name in ("majors", "liquid_alts", "mixed"):
        universe_symbols = list(_select_universe(universe_name, available_symbols))
        if len(universe_symbols) < 2:
            continue
        _, closes_by_symbol = _align_hourly_closes(universe_symbols)
        if len(closes_by_symbol) < 2:
            continue
        combo_params = list(product(
            lookbacks,
            rebalances,
            top_ks,
            score_modes,
            require_positive_values,
            ema_filters,
        ))
        universe_rows: list[dict[str, object]] = []
        with ProcessPoolExecutor(
            max_workers=max(1, args.workers),
            initializer=_worker_init,
            initargs=(closes_by_symbol,),
        ) as executor:
            future_map = {executor.submit(_evaluate_combo_worker, params): params for params in combo_params}
            completed = 0
            for future in as_completed(future_map):
                payload = future.result()
                completed += 1
                combo_counter += 1
                if payload is None:
                    continue
                universe_rows.append(payload)
                results.append(
                    RotationResult(
                        universe=universe_name,
                        score_mode=str(payload["score_mode"]),
                        lookback_hours=int(payload["lookback_hours"]),
                        rebalance_hours=int(payload["rebalance_hours"]),
                        top_k=int(payload["top_k"]),
                        require_positive=bool(payload["require_positive"]),
                        ema_filter=bool(payload["ema_filter"]),
                        symbols=tuple(closes_by_symbol),
                        rebalance_count=int(payload["rebalance_count"]),
                        average_turnover=float(payload["average_turnover"]),
                        total_return_pct=float(payload["total_return_pct"]),
                        sharpe_like=float(payload["sharpe_like"]),
                        profit_factor=float(payload["profit_factor"]),
                        max_drawdown_pct=float(payload["max_drawdown_pct"]),
                        final_equity=float(payload["final_equity"]),
                    )
                )
                if completed % 10 == 0 or completed == len(combo_params):
                    print(f"[progress] universe={universe_name} completed={completed}/{len(combo_params)} total={combo_counter}", flush=True)
        universe_rows.sort(key=lambda item: (float(item["total_return_pct"]), float(item["sharpe_like"]), float(item["profit_factor"])), reverse=True)
        checkpoint_payload["universe_results"][universe_name] = {
            "symbols": sorted(closes_by_symbol),
            "combo_count": len(universe_rows),
            "top_results": universe_rows[:10],
        }
        CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CHECKPOINT_PATH.write_text(json.dumps(checkpoint_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    results.sort(key=lambda item: (item.total_return_pct, item.sharpe_like, item.profit_factor), reverse=True)
    payload = {
        "generated_by": "rotation_strategy_scan",
        "profile": "fast" if args.fast else "full",
        "workers": args.workers,
        "top_results": [item.as_dict() for item in results[:30]],
        "all_results": [item.as_dict() for item in results],
        "universes_tested": ["majors", "liquid_alts", "mixed"],
        "symbols_available": available_symbols,
        "combo_count": len(results),
        "runtime_seconds": round(time.time() - started_at, 3),
        "checkpoint_path": str(CHECKPOINT_PATH),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=" * 100)
    print("ROTATION STRATEGY SCAN")
    print("=" * 100)
    print(f"available symbols: {', '.join(available_symbols)}")
    print(f"combos tested: {len(results)}")
    print(f"saved: {OUTPUT_PATH}")
    print()
    for item in results[:15]:
        print(
            f"{item.universe:<12} score={item.score_mode:<15} lookback={item.lookback_hours:>3}h "
            f"rebalance={item.rebalance_hours:>2}h top_k={item.top_k} positive={int(item.require_positive)} "
            f"ema={int(item.ema_filter)} return={item.total_return_pct:+7.2f}% "
            f"PF={item.profit_factor:>5.2f} MDD={item.max_drawdown_pct:>6.2f}% Sharpe={item.sharpe_like:>6.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
