#!/usr/bin/env python3
"""Counterfactual check for the 50 USDT read-only paper monitor.

Reads paper50 decision logs, fetches Bitget futures 1m candles, and checks
whether blocked entries were correctly filtered after 5/10/15 minute outcomes.
This script is read-only: it only uses public market candles and writes a local
diagnostic artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_binance.execution.client_factory import build_exchange_rest_client


DEFAULT_SYMBOLS = ("PEPEUSDT", "DOGEUSDT", "XRPUSDT", "SOLUSDT", "ETHUSDT", "BTCUSDT")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _load_decisions(path: Path, *, symbols: set[str], min_age_minutes: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    now = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
            symbol = str(row.get("symbol") or "").upper()
            timestamp = _parse_timestamp(str(row.get("timestamp") or ""))
        except Exception:
            continue
        if symbol not in symbols:
            continue
        if timestamp > now - timedelta(minutes=min_age_minutes):
            continue
        rows.append(row)
    return rows


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _close_at_or_before(bars: list[dict[str, Any]], target_ms: int) -> float | None:
    candidates = [bar for bar in bars if int(bar.get("open_time") or 0) <= target_ms]
    if not candidates:
        return None
    return _safe_float(candidates[-1].get("close_price"), 0.0) or None


def _label_result(*, net_after_cost_bps: float | None, mfe_bps: float, mae_bps: float, cost_bps: float) -> str:
    if net_after_cost_bps is None:
        return "unknown"
    if net_after_cost_bps <= 0:
        return "confirmed_block"
    if net_after_cost_bps > 10.0 and mfe_bps > cost_bps + 18.0 and mae_bps > -25.0:
        return "possible_missed_entry"
    if mfe_bps > cost_bps + 10.0:
        return "watch_marginal_miss"
    return "valid_block"


def _decision_direction(row: dict[str, Any]) -> str:
    trend = _safe_float(row.get("trend_direction"), 0.0)
    return "long" if trend >= 0.0 else "short"


def _evaluate_decision(client: Any, row: dict[str, Any], *, forward_minutes: int) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "").upper()
    timestamp = _parse_timestamp(str(row.get("timestamp") or ""))
    start_ms = int(timestamp.timestamp() * 1000)
    end_ms = int((timestamp + timedelta(minutes=forward_minutes + 1)).timestamp() * 1000)
    bars = sorted(
        client.get_klines(
            market="futures",
            symbol=symbol,
            interval="1m",
            limit=max(20, forward_minutes + 5),
            start_time=start_ms,
            end_time=end_ms,
        ),
        key=lambda item: int(item.get("open_time") or 0),
    )
    reference_price = _safe_float(row.get("reference_price"), 0.0)
    direction = _decision_direction(row)
    sign = 1.0 if direction == "long" else -1.0
    cost_bps = _safe_float(row.get("estimated_round_trip_cost_bps"), 0.0)
    if reference_price <= 0.0 or not bars:
        raise RuntimeError(f"missing forward data for {symbol} {timestamp.isoformat()}")

    high = max(_safe_float(bar.get("high_price"), 0.0) for bar in bars)
    low = min(_safe_float(bar.get("low_price"), 0.0) for bar in bars)
    if direction == "long":
        mfe_bps = (high / reference_price - 1.0) * 10000.0
        mae_bps = (low / reference_price - 1.0) * 10000.0
    else:
        mfe_bps = (1.0 - low / reference_price) * 10000.0
        mae_bps = (1.0 - high / reference_price) * 10000.0

    returns: dict[str, float | None] = {}
    for minutes in (5, 10, forward_minutes):
        close = _close_at_or_before(bars, start_ms + minutes * 60_000)
        returns[f"ret{minutes}_bps"] = None if close is None else sign * ((close / reference_price) - 1.0) * 10000.0
    forward_ret = returns[f"ret{forward_minutes}_bps"]
    net_after_cost = None if forward_ret is None else forward_ret - cost_bps
    label = _label_result(
        net_after_cost_bps=net_after_cost,
        mfe_bps=mfe_bps,
        mae_bps=mae_bps,
        cost_bps=cost_bps,
    )
    return {
        "timestamp": row.get("timestamp"),
        "symbol": symbol,
        "direction": direction,
        "side": row.get("side"),
        "candidate_mode": row.get("candidate_mode"),
        "score": round(_safe_float(row.get("predictability_score"), 0.0), 6),
        "trend_strength": round(_safe_float(row.get("trend_strength"), 0.0), 6),
        "net_expected_edge_bps": round(_safe_float(row.get("net_expected_edge_bps"), 0.0), 6),
        "edge_to_cost": round(
            _safe_float(row.get("net_expected_edge_bps"), 0.0) / cost_bps if cost_bps > 0.0 else 999.0,
            6,
        ),
        "liquidity_score": round(_safe_float(row.get("liquidity_score"), 0.0), 6),
        "volume_confirmation": round(_safe_float(row.get("volume_confirmation"), 0.0), 6),
        "cost_bps": round(cost_bps, 6),
        "mfe_bps": round(mfe_bps, 6),
        "mae_bps": round(mae_bps, 6),
        "net_after_cost_bps": None if net_after_cost is None else round(net_after_cost, 6),
        "forward_returns_bps": {key: None if value is None else round(value, 6) for key, value in returns.items()},
        "label": label,
        "rejection_reasons": list(row.get("rejection_reasons") or []),
        "divergence_code": row.get("divergence_code") or "",
    }


def _summarize(results: list[dict[str, Any]], *, symbols: tuple[str, ...]) -> dict[str, Any]:
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        by_symbol[str(row.get("symbol") or "")].append(row)

    symbol_summaries: dict[str, dict[str, Any]] = {}
    all_possible: list[dict[str, Any]] = []
    for symbol in symbols:
        rows = by_symbol.get(symbol, [])
        label_counts = Counter(str(row.get("label") or "unknown") for row in rows)
        net_values = [
            float(row["net_after_cost_bps"])
            for row in rows
            if row.get("net_after_cost_bps") is not None
        ]
        possible = [row for row in rows if row.get("label") == "possible_missed_entry"]
        all_possible.extend(possible)
        verdict = "healthy"
        if len(possible) >= 2:
            verdict = "needs_review"
        elif possible or label_counts.get("watch_marginal_miss", 0) >= 3:
            verdict = "watch"
        symbol_summaries[symbol] = {
            "decision_count": len(rows),
            "label_counts": dict(label_counts),
            "avg_net_after_cost_bps": round(sum(net_values) / len(net_values), 6) if net_values else None,
            "best_net_after_cost_bps": round(max(net_values), 6) if net_values else None,
            "worst_net_after_cost_bps": round(min(net_values), 6) if net_values else None,
            "verdict": verdict,
            "recent_possible_missed_entries": possible[-5:],
        }

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "paper50_blocked_entry_counterfactual",
        "decision_count": len(results),
        "possible_missed_entry_count": len(all_possible),
        "possible_missed_entries": sorted(
            all_possible,
            key=lambda row: float(row.get("net_after_cost_bps") or 0.0),
            reverse=True,
        )[:20],
        "symbol_summaries": symbol_summaries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-base", default="quant_runtime_paper50")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--forward-minutes", type=int, default=15)
    parser.add_argument("--min-age-minutes", type=int, default=16)
    parser.add_argument("--per-symbol-limit", type=int, default=20)
    parser.add_argument("--write-latest", action="store_true")
    args = parser.parse_args()

    symbols = tuple(symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip())
    decisions_path = Path(args.output_base) / "forensics" / "decisions.jsonl"
    rows = _load_decisions(decisions_path, symbols=set(symbols), min_age_minutes=args.min_age_minutes)
    per_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        per_symbol[str(row.get("symbol") or "").upper()].append(row)
    selected: list[dict[str, Any]] = []
    for symbol in symbols:
        selected.extend(per_symbol[symbol][-max(args.per_symbol_limit, 1):])

    client = build_exchange_rest_client(exchange="bitget", allow_insecure_ssl=True, allow_missing_credentials=True)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for row in selected:
        try:
            results.append(_evaluate_decision(client, row, forward_minutes=max(args.forward_minutes, 1)))
        except Exception as exc:
            errors.append(
                {
                    "timestamp": str(row.get("timestamp") or ""),
                    "symbol": str(row.get("symbol") or ""),
                    "error": str(exc),
                }
            )

    payload = _summarize(results, symbols=symbols)
    payload["error_count"] = len(errors)
    payload["errors"] = errors[:20]
    if args.write_latest:
        artifact_dir = Path(args.output_base) / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "paper50_counterfactual_latest.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
