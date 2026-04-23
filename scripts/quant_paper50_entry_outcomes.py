#!/usr/bin/env python3
"""Evaluate accepted paper50 entries against forward Bitget market returns."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_binance.execution.client_factory import build_exchange_rest_client


DEFAULT_OUTPUT = Path("quant_runtime_paper50/artifacts/paper50_entry_outcomes_latest.json")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_jsonl(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            key = str(row.get("decision_id") or row.get("decision_hash") or f"{row.get('symbol')}:{row.get('timestamp')}")
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


def _accepted_entries(rows: list[dict[str, Any]], *, min_age_minutes: int) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(minutes=min_age_minutes)
    accepted: list[dict[str, Any]] = []
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
        if _safe_float(row.get("order_intent_notional_usd")) <= 0.0:
            continue
        accepted.append(row)
    return accepted


def _close_at_or_before(bars: list[dict[str, Any]], target_ms: int) -> float | None:
    candidates = [bar for bar in bars if int(bar.get("open_time") or 0) <= target_ms]
    if not candidates:
        return None
    close = _safe_float(candidates[-1].get("close_price"))
    return close or None


def _evaluate_entry(client: Any, row: dict[str, Any], *, horizons: list[int]) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "").upper()
    timestamp = _parse_timestamp(str(row.get("timestamp") or ""))
    reference_price = _safe_float(row.get("reference_price"))
    side = str(row.get("side") or "").lower()
    sign = 1.0 if side == "long" else -1.0
    cost_bps = _safe_float(row.get("estimated_round_trip_cost_bps"))
    max_horizon = max(horizons)
    start_ms = int(timestamp.timestamp() * 1000)
    bars = sorted(
        client.get_klines(
            market="futures",
            symbol=symbol,
            interval="1m",
            limit=max(20, max_horizon + 5),
            start_time=start_ms,
            end_time=int((timestamp + timedelta(minutes=max_horizon + 1)).timestamp() * 1000),
        ),
        key=lambda item: int(item.get("open_time") or 0),
    )
    returns: dict[str, float | None] = {}
    net_returns: dict[str, float | None] = {}
    for minutes in horizons:
        close = _close_at_or_before(bars, start_ms + minutes * 60_000)
        raw = None if close is None or reference_price <= 0.0 else sign * ((close / reference_price) - 1.0) * 10000.0
        returns[f"ret{minutes}_bps"] = None if raw is None else round(raw, 6)
        net_returns[f"net_ret{minutes}_bps"] = None if raw is None else round(raw - cost_bps, 6)
    return {
        "timestamp": row.get("timestamp"),
        "symbol": symbol,
        "side": side,
        "reference_price": reference_price,
        "order_intent_notional_usd": _safe_float(row.get("order_intent_notional_usd")),
        "score": _safe_float(row.get("predictability_score")),
        "net_expected_edge_bps": _safe_float(row.get("net_expected_edge_bps")),
        "estimated_round_trip_cost_bps": cost_bps,
        "forward_returns_bps": returns,
        "forward_net_returns_bps": net_returns,
    }


def _summarize(results: list[dict[str, Any]], *, horizons: list[int]) -> dict[str, Any]:
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        by_symbol[str(row.get("symbol") or "")].append(row)
    horizon_summary: dict[str, dict[str, Any]] = {}
    for minutes in horizons:
        key = f"net_ret{minutes}_bps"
        values = [
            _safe_float(row.get("forward_net_returns_bps", {}).get(key))
            for row in results
            if row.get("forward_net_returns_bps", {}).get(key) is not None
        ]
        horizon_summary[f"{minutes}m"] = {
            "complete_count": len(values),
            "negative_count": sum(1 for value in values if value < 0.0),
            "avg_net_bps": round(sum(values) / len(values), 6) if values else None,
            "best_net_bps": round(max(values), 6) if values else None,
            "worst_net_bps": round(min(values), 6) if values else None,
        }
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "paper50_accepted_entry_outcomes",
        "accepted_entry_count": len(results),
        "horizon_summary": horizon_summary,
        "symbol_counts": {symbol: len(rows) for symbol, rows in sorted(by_symbol.items())},
        "entries": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions-path", action="append", required=True)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--horizons", default="5,10,15")
    parser.add_argument("--min-age-minutes", type=int, default=5)
    args = parser.parse_args()

    horizons = sorted({max(int(item.strip()), 1) for item in args.horizons.split(",") if item.strip()})
    rows = _accepted_entries(_load_jsonl([Path(path) for path in args.decisions_path]), min_age_minutes=max(args.min_age_minutes, 0))
    client = build_exchange_rest_client(exchange="bitget", allow_insecure_ssl=True, allow_missing_credentials=True)
    results = [_evaluate_entry(client, row, horizons=horizons) for row in rows]
    payload = _summarize(results, horizons=horizons)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
