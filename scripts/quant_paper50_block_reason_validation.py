"""Reason-level validation for paper50 blocked entries.

Reads paper50 decision logs, re-evaluates mature blocked entries against Bitget
public 1m futures candles, and writes reason-level diagnostics.

This script is read-only: it does not place, modify, or cancel any order.
"""

from __future__ import annotations

import argparse
import importlib.util
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
DEFAULT_OUTPUT_BASE = Path("quant_runtime_paper50")
DEFAULT_FULL_OUTPUT = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_block_reason_full_validation_latest.json"
DEFAULT_SUMMARY_OUTPUT = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_block_reason_validation_latest.json"


def _load_counterfactual_module():
    path = ROOT / "scripts" / "quant_paper50_counterfactual.py"
    spec = importlib.util.spec_from_file_location("quant_paper50_counterfactual", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


counterfactual = _load_counterfactual_module()


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_accepted_futures_entry(row: dict[str, Any]) -> bool:
    if bool(row.get("rejected")):
        return False
    if str(row.get("final_mode") or "").lower() != "futures":
        return False
    if str(row.get("side") or "").lower() not in {"long", "short"}:
        return False
    return _safe_float(row.get("order_intent_notional_usd")) > 0.0


def _bucket_rows(
    rows: list[dict[str, Any]],
    *,
    maturity_cutoff: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    mature_blocked: list[dict[str, Any]] = []
    pending_blocked: list[dict[str, Any]] = []
    pending_accepted: list[dict[str, Any]] = []
    for row in rows:
        try:
            timestamp = _parse_timestamp(str(row.get("timestamp") or ""))
        except Exception:
            continue
        if counterfactual._is_blocked_entry(row):
            if timestamp <= maturity_cutoff:
                mature_blocked.append(row)
            else:
                pending_blocked.append(row)
        elif _is_accepted_futures_entry(row) and timestamp > maturity_cutoff:
            pending_accepted.append(row)
    return mature_blocked, pending_blocked, pending_accepted


def _classify_bucket(*, n: int, miss_rate: float, confirmed_or_valid_rate: float, avg_net_after_cost_bps: float | None) -> str:
    if n < 4:
        return "insufficient_sample"
    if miss_rate >= 0.2:
        return "watch_too_conservative"
    if confirmed_or_valid_rate >= 0.75 and (avg_net_after_cost_bps is None or avg_net_after_cost_bps <= -5.0):
        return "acceptable_or_useful_block"
    return "acceptable_mixed"


def _summarize_evaluated(rows: list[dict[str, Any]]) -> dict[str, Any]:
    label_counts = Counter(str(row.get("label") or "unknown") for row in rows)
    n = len(rows)
    net_values = [_safe_float(row.get("net_after_cost_bps")) for row in rows if row.get("net_after_cost_bps") is not None]
    confirmed = int(label_counts.get("confirmed_block", 0))
    valid = int(label_counts.get("valid_block", 0))
    possible = int(label_counts.get("possible_missed_entry", 0))
    watch = int(label_counts.get("watch_marginal_miss", 0))
    miss_rate = possible / n if n else 0.0
    confirmed_or_valid_rate = (confirmed + valid) / n if n else 0.0
    avg_net = round(sum(net_values) / len(net_values), 6) if net_values else None
    summary = {
        "n": n,
        "label_counts": dict(label_counts),
        "confirmed_block": confirmed,
        "valid_block": valid,
        "possible_missed_entry": possible,
        "watch_marginal_miss": watch,
        "miss_rate": round(miss_rate, 6),
        "confirmed_or_valid_rate": round(confirmed_or_valid_rate, 6),
        "watch_or_miss_rate": round((possible + watch) / n, 6) if n else 0.0,
        "avg_net_after_cost_bps": avg_net,
        "best_net_after_cost_bps": round(max(net_values), 6) if net_values else None,
        "worst_net_after_cost_bps": round(min(net_values), 6) if net_values else None,
    }
    summary["classification"] = _classify_bucket(
        n=n,
        miss_rate=miss_rate,
        confirmed_or_valid_rate=confirmed_or_valid_rate,
        avg_net_after_cost_bps=avg_net,
    )
    return summary


def _reason_buckets(evaluated: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    by_reason_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_symbol_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_symbol_reason_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in evaluated:
        symbol = str(row.get("symbol") or "").upper()
        reasons = [str(reason) for reason in row.get("rejection_reasons") or []]
        if not reasons:
            reasons = ["UNSPECIFIED_BLOCK_REASON"]
        by_symbol_rows[symbol].append(row)
        for reason in reasons:
            by_reason_rows[reason].append(row)
            by_symbol_reason_rows[f"{symbol}:{reason}"].append(row)

    by_reason = {key: _summarize_evaluated(value) for key, value in sorted(by_reason_rows.items())}
    by_symbol = {key: _summarize_evaluated(value) for key, value in sorted(by_symbol_rows.items())}
    by_symbol_reason = {key: _summarize_evaluated(value) for key, value in sorted(by_symbol_reason_rows.items())}
    return by_reason, by_symbol, by_symbol_reason


def _pending_rows_payload(rows: list[dict[str, Any]], *, limit: int = 50) -> list[dict[str, Any]]:
    selected = sorted(rows, key=lambda row: str(row.get("timestamp") or ""))[-max(limit, 1):]
    return [
        {
            "timestamp": row.get("timestamp"),
            "symbol": row.get("symbol"),
            "side": row.get("side"),
            "final_mode": row.get("final_mode"),
            "order_intent_notional_usd": _safe_float(row.get("order_intent_notional_usd")),
            "rejection_reasons": list(row.get("rejection_reasons") or []),
        }
        for row in selected
    ]


def build_payload(
    *,
    decision_rows: list[dict[str, Any]],
    symbols: tuple[str, ...],
    min_age_minutes: int,
    forward_minutes: int,
    max_evaluated: int | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    maturity_cutoff = now - timedelta(minutes=max(min_age_minutes, 0))
    filtered_rows = [row for row in decision_rows if str(row.get("symbol") or "").upper() in set(symbols)]
    mature_blocked, pending_blocked, pending_accepted = _bucket_rows(
        filtered_rows,
        maturity_cutoff=maturity_cutoff,
    )

    client = build_exchange_rest_client(exchange="bitget", allow_insecure_ssl=True, allow_missing_credentials=True)
    evaluated: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    selected_mature_blocked = sorted(mature_blocked, key=lambda row: str(row.get("timestamp") or ""))
    if max_evaluated is not None and max_evaluated > 0:
        selected_mature_blocked = selected_mature_blocked[-max_evaluated:]
    for row in selected_mature_blocked:
        try:
            evaluated.append(counterfactual._evaluate_decision(client, row, forward_minutes=max(forward_minutes, 1)))
        except Exception as exc:
            errors.append(
                {
                    "timestamp": row.get("timestamp"),
                    "symbol": row.get("symbol"),
                    "error": str(exc),
                }
            )

    by_reason, by_symbol, by_symbol_reason = _reason_buckets(evaluated)
    overall = _summarize_evaluated(evaluated)
    payload = {
        "generated_at": now.isoformat(),
        "mode": "paper50_block_reason_full_validation",
        "method": "bitget_public_candles_forward_5_10_15_after_cost",
        "mature_blocked_available": len(mature_blocked),
        "max_evaluated": max_evaluated,
        "mature_blocked_evaluated": len(evaluated),
        "pending_not_yet_15m_mature_count": len(pending_blocked),
        "pending_not_yet_15m_mature": _pending_rows_payload(pending_blocked),
        "pending_accepted_not_yet_15m_mature_count": len(pending_accepted),
        "pending_accepted_not_yet_15m_mature": _pending_rows_payload(pending_accepted),
        "overall": overall,
        "by_reason": by_reason,
        "by_symbol": by_symbol,
        "by_symbol_reason": by_symbol_reason,
        "error_count": len(errors),
        "errors": errors[:50],
    }
    return payload


def _summary_payload(full_payload: dict[str, Any]) -> dict[str, Any]:
    not_mature = list(full_payload.get("pending_not_yet_15m_mature") or [])
    return {
        "generated_at": full_payload.get("generated_at"),
        "mature_blocked_evaluated": full_payload.get("mature_blocked_evaluated"),
        "recent_mature_evaluated": full_payload.get("mature_blocked_evaluated"),
        "not_yet_15m_mature_count": full_payload.get("pending_not_yet_15m_mature_count"),
        "not_yet_15m_mature_timestamps": [row.get("timestamp") for row in not_mature],
        "overall": full_payload.get("overall"),
        "by_reason": full_payload.get("by_reason"),
        "errors": full_payload.get("errors"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-base", default=str(DEFAULT_OUTPUT_BASE))
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--min-age-minutes", type=int, default=21)
    parser.add_argument("--forward-minutes", type=int, default=15)
    parser.add_argument("--max-evaluated", type=int)
    parser.add_argument("--decisions-path", action="append", default=[])
    parser.add_argument("--output-full", default=str(DEFAULT_FULL_OUTPUT))
    parser.add_argument("--output-summary", default=str(DEFAULT_SUMMARY_OUTPUT))
    args = parser.parse_args()

    output_base = Path(args.output_base)
    symbols = tuple(symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip())
    decision_paths = [Path(path) for path in args.decisions_path] or counterfactual._default_decision_paths(output_base)
    decision_rows = counterfactual._load_decisions(decision_paths, symbols=set(symbols), min_age_minutes=0)

    full_payload = build_payload(
        decision_rows=decision_rows,
        symbols=symbols,
        min_age_minutes=max(args.min_age_minutes, 0),
        forward_minutes=max(args.forward_minutes, 1),
        max_evaluated=args.max_evaluated,
    )
    summary_payload = _summary_payload(full_payload)

    output_full = Path(args.output_full)
    output_summary = Path(args.output_summary)
    output_full.parent.mkdir(parents=True, exist_ok=True)
    output_summary.parent.mkdir(parents=True, exist_ok=True)
    output_full.write_text(json.dumps(full_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output_summary.write_text(json.dumps(summary_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary_payload, ensure_ascii=False, sort_keys=True))
    return 0 if int(full_payload.get("error_count") or 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
