#!/usr/bin/env python3
"""Classify read-only Bitget paper decisions with the high-probability gate.

This script is observational only. It reads local decision logs and writes a
summary; it never calls private endpoints or sends exchange orders.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


HARD_BLOCKS = {
    "DIRECTION_CONFLICT",
    "EDGE_BELOW_COST",
    "BUYING_INTO_RESISTANCE",
    "SUPPORT_NOT_CONFIRMED",
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _latest_overlay_metrics(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    metrics: dict[str, dict[str, Any]] = {}
    for row in list(payload.get("rows") or []):
        symbol = str(row.get("symbol") or "").upper()
        market_metrics = row.get("market_metrics")
        if symbol and isinstance(market_metrics, dict):
            metrics[symbol] = market_metrics
    return metrics


def classify_decision(row: dict[str, Any], overlay_metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "").upper()
    reasons = {str(reason) for reason in list(row.get("rejection_reasons") or [])}
    score = _safe_float(row.get("predictability_score"))
    trend = _safe_float(row.get("trend_strength"))
    edge = _safe_float(row.get("net_expected_edge_bps"))
    cost = max(_safe_float(row.get("estimated_round_trip_cost_bps")), 0.000001)
    edge_to_cost = edge / cost
    volume = _safe_float(row.get("volume_confirmation"))
    side = "long" if _safe_float(row.get("trend_direction")) > 0 else "short"
    metrics = overlay_metrics or {}
    taker_ratio = metrics.get("taker_buy_ratio_6h")
    taker_ratio_float = None if taker_ratio is None else _safe_float(taker_ratio)
    funding_pct = _safe_float(metrics.get("funding_pct"))
    spread_bps = _safe_float(metrics.get("spread_bps"))
    effective_cost = _safe_float(metrics.get("effective_round_trip_cost_bps"), cost)

    if reasons & HARD_BLOCKS:
        return {
            "state": "shadow_only",
            "reason": "hard_block",
            "hard_blocks": sorted(reasons & HARD_BLOCKS),
        }

    if symbol == "DOGEUSDT":
        ok = (
            side == "long"
            and score >= 72.0
            and trend >= 0.74
            and edge >= 24.0
            and edge_to_cost >= 2.25
            and volume >= 0.42
            and effective_cost <= 18.5
            and (taker_ratio_float is None or taker_ratio_float >= 0.49)
        )
        return {"state": "admit_paper" if ok else "confirm_only", "reason": "doge_primary_candidate"}

    if symbol == "ETHUSDT":
        ok = (
            side == "long"
            and score >= 71.0
            and trend >= 0.72
            and edge >= 26.0
            and edge_to_cost >= 3.0
            and volume >= 0.39
            and funding_pct <= 0.006
        )
        return {"state": "confirm_only" if ok else "shadow_only", "reason": "eth_secondary_candidate"}

    if symbol == "BTCUSDT":
        return {"state": "confirm_only", "reason": "btc_anchor_only"}

    if symbol == "PEPEUSDT":
        breakout = (
            side == "long"
            and score >= 68.0
            and edge >= 32.0
            and volume >= 0.48
            and spread_bps <= 0.45
            and funding_pct <= 0.0
        )
        return {"state": "confirm_only" if breakout else "shadow_only", "reason": "pepe_breakout_exception"}

    return {"state": "shadow_only", "reason": "non_primary_symbol"}


def build_summary(*, decisions_path: Path, overlay_path: Path) -> dict[str, Any]:
    rows = _load_jsonl(decisions_path)
    metrics_by_symbol = _latest_overlay_metrics(overlay_path)
    classified: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        gate = classify_decision(row, metrics_by_symbol.get(symbol))
        classified.append(
            {
                "timestamp": row.get("timestamp"),
                "symbol": symbol,
                "final_mode": row.get("final_mode") or row.get("mode"),
                "side": row.get("side"),
                "order_intent_notional_usd": _safe_float(row.get("order_intent_notional_usd")),
                "score": _safe_float(row.get("predictability_score")),
                "volume_confirmation": _safe_float(row.get("volume_confirmation")),
                "net_expected_edge_bps": _safe_float(row.get("net_expected_edge_bps")),
                "estimated_round_trip_cost_bps": _safe_float(row.get("estimated_round_trip_cost_bps")),
                "rejection_reasons": list(row.get("rejection_reasons") or []),
                "high_probability_gate": gate,
            }
        )
    counts = Counter(item["high_probability_gate"]["state"] for item in classified)
    by_symbol: dict[str, Counter[str]] = defaultdict(Counter)
    for item in classified:
        by_symbol[item["symbol"]][item["high_probability_gate"]["state"]] += 1
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "decisions_path": str(decisions_path),
        "overlay_path": str(overlay_path),
        "decision_count": len(classified),
        "state_counts": dict(counts),
        "symbol_state_counts": {symbol: dict(counter) for symbol, counter in sorted(by_symbol.items())},
        "classified_decisions": classified,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize high-probability Bitget paper decisions.")
    parser.add_argument("--decisions", required=True)
    parser.add_argument(
        "--overlay",
        default="quant_runtime_paper50/bitget_overlay_tuning/bitget_overlay_tuning_report.json",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    summary = build_summary(decisions_path=Path(args.decisions), overlay_path=Path(args.overlay))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("decision_count", "state_counts", "symbol_state_counts")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
