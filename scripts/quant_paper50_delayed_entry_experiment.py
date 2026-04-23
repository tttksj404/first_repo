#!/usr/bin/env python3
"""Compare immediate futures entries with delayed paper-only entry variants.

This script is read-only: it evaluates historical paper50 decision logs against
Bitget public futures candles and writes a diagnostic artifact. It does not
place, test, cancel, or modify orders.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_binance.execution.client_factory import build_exchange_rest_client
from scripts.quant_paper50_entry_outcomes import _load_jsonl, _parse_timestamp, _safe_float


DEFAULT_OUTPUT = Path("quant_runtime_paper50/artifacts/paper50_delayed_entry_experiment_latest.json")


def _close_at_or_before(bars: list[dict[str, Any]], target_ms: int) -> float | None:
    candidates = [bar for bar in bars if int(bar.get("open_time") or 0) <= target_ms]
    if not candidates:
        return None
    close = _safe_float(candidates[-1].get("close_price"))
    return close or None


def _futures_signals(rows: list[dict[str, Any]], *, min_age_minutes: int) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(minutes=max(min_age_minutes, 0))
    signals: list[dict[str, Any]] = []
    for row in rows:
        try:
            timestamp = _parse_timestamp(str(row.get("timestamp") or ""))
        except Exception:
            continue
        if timestamp > cutoff:
            continue
        if bool(row.get("rejected")):
            continue
        if str(row.get("final_mode") or "").lower() != "futures":
            continue
        if str(row.get("side") or "").lower() not in {"long", "short"}:
            continue
        signals.append(row)
    return signals


def _edge_to_cost(row: dict[str, Any]) -> float:
    cost = _safe_float(row.get("estimated_round_trip_cost_bps"))
    if cost <= 0.0:
        return 999.0
    return _safe_float(row.get("net_expected_edge_bps")) / cost


def _composite_rank(row: dict[str, Any]) -> float:
    return (
        _safe_float(row.get("predictability_score"))
        + _safe_float(row.get("net_expected_edge_bps")) * 0.35
        + _safe_float(row.get("volume_confirmation")) * 12.0
        + _safe_float(row.get("liquidity_score")) * 8.0
        + _edge_to_cost(row) * 2.0
    )


def _evaluate_signal(
    client: Any,
    row: dict[str, Any],
    *,
    delay_minutes: int,
    horizons: list[int],
) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "").upper()
    side = str(row.get("side") or "").lower()
    sign = 1.0 if side == "long" else -1.0
    timestamp = _parse_timestamp(str(row.get("timestamp") or ""))
    start_ms = int(timestamp.timestamp() * 1000)
    max_horizon = max(horizons)
    end_time = timestamp + timedelta(minutes=delay_minutes + max_horizon + 1)
    bars = sorted(
        client.get_klines(
            market="futures",
            symbol=symbol,
            interval="1m",
            limit=max(30, delay_minutes + max_horizon + 5),
            start_time=start_ms,
            end_time=int(end_time.timestamp() * 1000),
        ),
        key=lambda item: int(item.get("open_time") or 0),
    )
    reference_price = _safe_float(row.get("reference_price"))
    cost_bps = _safe_float(row.get("estimated_round_trip_cost_bps"))
    if reference_price <= 0.0 or not bars:
        raise RuntimeError(f"missing price data for {symbol} {timestamp.isoformat()}")

    delay_price = _close_at_or_before(bars, start_ms + delay_minutes * 60_000)
    immediate: dict[str, float | None] = {}
    delayed: dict[str, float | None] = {}
    for minutes in horizons:
        immediate_close = _close_at_or_before(bars, start_ms + minutes * 60_000)
        immediate_raw = (
            None
            if immediate_close is None
            else sign * ((immediate_close / reference_price) - 1.0) * 10000.0
        )
        immediate[f"net_ret{minutes}_bps"] = None if immediate_raw is None else round(immediate_raw - cost_bps, 6)
        delayed_close = (
            None
            if delay_price is None
            else _close_at_or_before(bars, start_ms + (delay_minutes + minutes) * 60_000)
        )
        delayed_raw = (
            None
            if delayed_close is None or delay_price is None or delay_price <= 0.0
            else sign * ((delayed_close / delay_price) - 1.0) * 10000.0
        )
        delayed[f"net_ret{minutes}_bps"] = None if delayed_raw is None else round(delayed_raw - cost_bps, 6)

    raw_to_delay = (
        None
        if delay_price is None
        else sign * ((delay_price / reference_price) - 1.0) * 10000.0
    )
    net_to_delay = None if raw_to_delay is None else raw_to_delay - cost_bps
    return {
        "timestamp": row.get("timestamp"),
        "symbol": symbol,
        "side": side,
        "is_executable": _safe_float(row.get("order_intent_notional_usd")) > 0.0,
        "order_intent_notional_usd": _safe_float(row.get("order_intent_notional_usd")),
        "score": _safe_float(row.get("predictability_score")),
        "net_expected_edge_bps": _safe_float(row.get("net_expected_edge_bps")),
        "edge_to_cost": round(_edge_to_cost(row), 6),
        "volume_confirmation": _safe_float(row.get("volume_confirmation")),
        "liquidity_score": _safe_float(row.get("liquidity_score")),
        "trend_strength": _safe_float(row.get("trend_strength")),
        "cost_bps": cost_bps,
        "reference_price": reference_price,
        "delay_entry_price": delay_price,
        "raw_to_delay_bps": None if raw_to_delay is None else round(raw_to_delay, 6),
        "net_to_delay_bps": None if net_to_delay is None else round(net_to_delay, 6),
        "immediate_forward_net_returns_bps": immediate,
        "delayed_forward_net_returns_bps": delayed,
    }


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _summarize_returns(
    rows: list[dict[str, Any]],
    *,
    horizons: list[int],
    field: str,
) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for minutes in horizons:
        key = f"net_ret{minutes}_bps"
        values = [
            _safe_float(row.get(field, {}).get(key))
            for row in rows
            if row.get(field, {}).get(key) is not None
        ]
        summary[f"{minutes}m"] = {
            "n": len(values),
            "avg": _avg(values),
            "positive": sum(1 for value in values if value > 0.0),
            "negative": sum(1 for value in values if value < 0.0),
            "best": round(max(values), 6) if values else None,
            "worst": round(min(values), 6) if values else None,
        }
    return summary


def _symbol_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[str(row.get("symbol") or "")] += 1
    return dict(sorted(counts.items()))


def _group_summary(rows: list[dict[str, Any]], *, horizons: list[int]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "symbol_counts": _symbol_counts(rows),
        "immediate": _summarize_returns(rows, horizons=horizons, field="immediate_forward_net_returns_bps"),
        "delay_5m": _summarize_returns(rows, horizons=horizons, field="delayed_forward_net_returns_bps"),
    }


def _top_per_timestamp(rows: list[dict[str, Any]], key_func: Callable[[dict[str, Any]], float]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("timestamp") or "")].append(row)
    selected: list[dict[str, Any]] = []
    for _, group in sorted(grouped.items()):
        selected.append(max(group, key=key_func))
    return selected


def build_report(
    *,
    rows: list[dict[str, Any]],
    client: Any,
    horizons: list[int],
    delay_minutes: int,
    min_age_minutes: int,
) -> dict[str, Any]:
    signals = _futures_signals(rows, min_age_minutes=min_age_minutes)
    evaluated = [
        _evaluate_signal(client, row, delay_minutes=delay_minutes, horizons=horizons)
        for row in signals
    ]
    executable = [row for row in evaluated if row.get("is_executable")]
    zero_notional = [row for row in evaluated if not row.get("is_executable")]
    momentum_confirmed = [
        row for row in evaluated if _safe_float(row.get("raw_to_delay_bps")) > 0.0
    ]
    pullback_confirmed = [
        row
        for row in evaluated
        if -30.0 <= _safe_float(row.get("raw_to_delay_bps"), -999.0) <= 0.0
    ]
    top_score = _top_per_timestamp(evaluated, lambda row: _safe_float(row.get("score")))
    top_edge = _top_per_timestamp(evaluated, lambda row: _safe_float(row.get("net_expected_edge_bps")))
    top_composite = _top_per_timestamp(
        evaluated,
        lambda row: (
            _safe_float(row.get("score"))
            + _safe_float(row.get("net_expected_edge_bps")) * 0.35
            + _safe_float(row.get("volume_confirmation")) * 12.0
            + _safe_float(row.get("liquidity_score")) * 8.0
            + _safe_float(row.get("edge_to_cost")) * 2.0
        ),
    )
    top_oracle_15m = _top_per_timestamp(
        evaluated,
        lambda row: _safe_float(row.get("delayed_forward_net_returns_bps", {}).get(f"net_ret{max(horizons)}_bps"), -9999.0),
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "paper50_delayed_entry_experiment",
        "delay_minutes": delay_minutes,
        "summary": {
            "all_futures_signals": _group_summary(evaluated, horizons=horizons),
            "executable_entries": _group_summary(executable, horizons=horizons),
            "zero_notional_futures_signals": _group_summary(zero_notional, horizons=horizons),
            "delay_momentum_confirmed": _group_summary(momentum_confirmed, horizons=horizons),
            "delay_pullback_confirmed": _group_summary(pullback_confirmed, horizons=horizons),
            "top_score_per_timestamp": _group_summary(top_score, horizons=horizons),
            "top_edge_per_timestamp": _group_summary(top_edge, horizons=horizons),
            "top_composite_per_timestamp": _group_summary(top_composite, horizons=horizons),
            "oracle_top_delayed_15m_per_timestamp": _group_summary(top_oracle_15m, horizons=horizons),
        },
        "top_delayed_15m": sorted(
            evaluated,
            key=lambda row: _safe_float(row.get("delayed_forward_net_returns_bps", {}).get(f"net_ret{max(horizons)}_bps"), -9999.0),
            reverse=True,
        )[:20],
        "entries": sorted(evaluated, key=lambda row: (str(row.get("timestamp") or ""), str(row.get("symbol") or ""))),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions-path", action="append", required=True)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--horizons", default="5,10,15")
    parser.add_argument("--delay-minutes", type=int, default=5)
    parser.add_argument("--min-age-minutes", type=int, default=21)
    args = parser.parse_args()

    horizons = sorted({max(int(item.strip()), 1) for item in args.horizons.split(",") if item.strip()})
    rows = _load_jsonl([Path(path) for path in args.decisions_path])
    client = build_exchange_rest_client(exchange="bitget", allow_insecure_ssl=True, allow_missing_credentials=True)
    payload = build_report(
        rows=rows,
        client=client,
        horizons=horizons,
        delay_minutes=max(args.delay_minutes, 1),
        min_age_minutes=max(args.min_age_minutes, max(args.delay_minutes, 1) + max(horizons) + 1),
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
