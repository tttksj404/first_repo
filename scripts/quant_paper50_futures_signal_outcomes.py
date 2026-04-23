#!/usr/bin/env python3
"""Evaluate all accepted futures signals, including zero-notional paper signals.

The regular accepted-entry outcome report intentionally ignores futures signals
with zero notional because those are not executable entries. This companion
report keeps them so paper50 can diagnose whether portfolio capacity or entry
timing is causing missed opportunities after a position is already open.
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
from scripts.quant_paper50_entry_outcomes import _evaluate_entry, _load_jsonl, _parse_timestamp, _safe_float


DEFAULT_OUTPUT = Path("quant_runtime_paper50/artifacts/paper50_futures_signal_outcomes_latest.json")


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


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _horizon_summary(results: list[dict[str, Any]], *, horizons: list[int]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for minutes in horizons:
        key = f"net_ret{minutes}_bps"
        values = [
            _safe_float(row.get("forward_net_returns_bps", {}).get(key))
            for row in results
            if row.get("forward_net_returns_bps", {}).get(key) is not None
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


def _symbol_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in results:
        counts[str(row.get("symbol") or "")] += 1
    return dict(sorted(counts.items()))


def _summarize_group(
    results: list[dict[str, Any]],
    *,
    horizons: list[int],
    predicate: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    rows = [row for row in results if predicate(row)]
    return {
        "count": len(rows),
        "horizons": _horizon_summary(rows, horizons=horizons),
        "symbol_counts": _symbol_counts(rows),
    }


def _annotate_result(result: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    executable_notional = _safe_float(source.get("order_intent_notional_usd"))
    result["executable_notional"] = executable_notional
    result["is_executable"] = executable_notional > 0.0
    result["score"] = _safe_float(source.get("predictability_score"))
    result["net_expected_edge_bps"] = _safe_float(source.get("net_expected_edge_bps"))
    result["volume_confirmation"] = _safe_float(source.get("volume_confirmation"))
    result["liquidity_score"] = _safe_float(source.get("liquidity_score"))
    result["trend_strength"] = _safe_float(source.get("trend_strength"))
    return result


def build_report(
    *,
    rows: list[dict[str, Any]],
    client: Any,
    horizons: list[int],
    min_age_minutes: int,
) -> dict[str, Any]:
    signals = _futures_signals(rows, min_age_minutes=min_age_minutes)
    results = [
        _annotate_result(_evaluate_entry(client, row, horizons=horizons), row)
        for row in signals
    ]
    zero_notional = [row for row in results if not row.get("is_executable")]
    top_zero = sorted(
        zero_notional,
        key=lambda row: _safe_float(row.get("forward_net_returns_bps", {}).get(f"net_ret{max(horizons)}_bps"), -9999.0),
        reverse=True,
    )[:20]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "paper50_futures_signal_outcomes",
        "summary": {
            "all_futures_signals": _summarize_group(results, horizons=horizons, predicate=lambda row: True),
            "executable_entries": _summarize_group(
                results,
                horizons=horizons,
                predicate=lambda row: bool(row.get("is_executable")),
            ),
            "zero_notional_futures_signals": _summarize_group(
                results,
                horizons=horizons,
                predicate=lambda row: not bool(row.get("is_executable")),
            ),
        },
        "top_zero_notional_15m": top_zero,
        "entries": sorted(results, key=lambda row: (str(row.get("timestamp") or ""), str(row.get("symbol") or ""))),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions-path", action="append", required=True)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--horizons", default="5,10,15")
    parser.add_argument("--min-age-minutes", type=int, default=16)
    args = parser.parse_args()

    horizons = sorted({max(int(item.strip()), 1) for item in args.horizons.split(",") if item.strip()})
    rows = _load_jsonl([Path(path) for path in args.decisions_path])
    client = build_exchange_rest_client(exchange="bitget", allow_insecure_ssl=True, allow_missing_credentials=True)
    payload = build_report(
        rows=rows,
        client=client,
        horizons=horizons,
        min_age_minutes=args.min_age_minutes,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
