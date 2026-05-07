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
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_binance.cost_calibration import CostCalibration, load_cost_calibration
from quant_binance.execution.client_factory import build_exchange_rest_client


DEFAULT_SYMBOLS = ("PEPEUSDT", "DOGEUSDT", "XRPUSDT", "SOLUSDT", "ETHUSDT", "BTCUSDT")
DEFAULT_FUNDING_RATE_8H = 0.0001
SLIPPAGE_STRESS_LEVELS_BPS = (0, 5, 10, 15, 20)
COST_UNSURVIVABLE_STRESS_BPS = 10
DEFAULT_FALLBACK_FEE_BPS = 6.0  # Bitget public taker fee (per side)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _default_decision_paths(output_base: Path) -> list[Path]:
    forensics_path = output_base / "forensics" / "decisions.jsonl"
    if forensics_path.exists():
        return [forensics_path]

    shell_root = output_base / "output" / "paper-live-shell"
    if not shell_root.exists():
        return []
    paths: list[Path] = []
    for run_dir in sorted(shell_root.iterdir(), key=lambda item: item.name):
        if not run_dir.is_dir() or run_dir.name == "latest":
            continue
        decisions_path = run_dir / "logs" / "decisions.jsonl"
        if decisions_path.exists():
            paths.append(decisions_path)
    return paths


def _load_decisions(paths: list[Path], *, symbols: set[str], min_age_minutes: int) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
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
            key = str(row.get("decision_id") or row.get("decision_hash") or f"{symbol}:{timestamp.isoformat()}")
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    return rows


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_blocked_entry(row: dict[str, Any]) -> bool:
    if bool(row.get("rejected")):
        return True
    if str(row.get("side") or "").lower() == "flat":
        return True
    if str(row.get("final_mode") or "").lower() == "cash":
        return True
    if row.get("rejection_reasons"):
        return True
    if (
        str(row.get("final_mode") or "").lower() in {"spot", "futures"}
        and _safe_float(row.get("order_intent_notional_usd")) > 0.0
    ):
        return False
    return False


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


def _decompose_costs(
    *,
    symbol: str,
    direction: str,
    upstream_cost_bps: float,
    calibration: CostCalibration | None,
    forward_minutes: int,
    funding_rate_8h: float = DEFAULT_FUNDING_RATE_8H,
) -> dict[str, Any]:
    """Break the upstream lump cost into entry_fee / exit_fee / slippage / funding.

    Returns a dict with bps components plus a `total_modeled_bps` field and a
    `reconciliation_diff_bps` measuring drift versus the upstream estimate.
    Source is `calibration` when present (median empirical fee + slippage per
    symbol); otherwise falls back to splitting the upstream cost evenly across
    the two fees and treating slippage/funding as zero unless overridden.
    """

    if calibration is not None:
        sym_cal = calibration.for_symbol(symbol)
        entry_fee = float(sym_cal.empirical_fee_bps or 0.0)
        exit_fee = float(sym_cal.empirical_fee_bps or 0.0)
        # If calibration has no fee samples but we have an upstream cost, fall
        # back to splitting it so we never report 0 fees against a positive lump.
        if entry_fee <= 0.0 and exit_fee <= 0.0 and upstream_cost_bps > 0.0:
            entry_fee = exit_fee = upstream_cost_bps / 2.0
            source = "fallback_lump_split"
        else:
            source = "calibration"
        entry_slippage = float(sym_cal.empirical_entry_slippage_bps or 0.0)
        exit_slippage = float(sym_cal.empirical_exit_slippage_bps or 0.0)
        slippage_untrusted = bool(sym_cal.slippage_untrusted)
    else:
        # No calibration available: split the lump cost evenly, treat slippage
        # as untrusted.
        entry_fee = upstream_cost_bps / 2.0 if upstream_cost_bps > 0.0 else DEFAULT_FALLBACK_FEE_BPS
        exit_fee = entry_fee
        entry_slippage = 0.0
        exit_slippage = 0.0
        slippage_untrusted = True
        source = "fallback_no_calibration"

    # Funding: prorate FUNDING_8H over the forward window. Long pays positive
    # rate, short receives. Units: rate is fraction (e.g. 0.0001 = 1bp/8h),
    # convert to bps via *10000.
    hold_hours = max(forward_minutes, 0) / 60.0
    funding_fraction = funding_rate_8h * (hold_hours / 8.0)
    funding_bps = funding_fraction * 10000.0
    if direction == "short":
        funding_bps = -funding_bps  # short receives funding when rate>0

    total_modeled = entry_fee + exit_fee + entry_slippage + exit_slippage + max(funding_bps, 0.0)
    reconciliation_diff = round(total_modeled - upstream_cost_bps, 6)
    return {
        "entry_fee_bps": round(entry_fee, 6),
        "exit_fee_bps": round(exit_fee, 6),
        "entry_slippage_bps": round(entry_slippage, 6),
        "exit_slippage_bps": round(exit_slippage, 6),
        "funding_bps": round(funding_bps, 6),
        "total_modeled_bps": round(total_modeled, 6),
        "upstream_cost_bps": round(upstream_cost_bps, 6),
        "reconciliation_diff_bps": reconciliation_diff,
        "slippage_untrusted": slippage_untrusted,
        "source": source,
    }


def _compute_slippage_stress(
    *,
    forward_ret_bps: float | None,
    breakdown: dict[str, Any],
    stress_levels_bps: tuple[int, ...] = SLIPPAGE_STRESS_LEVELS_BPS,
) -> dict[str, Any]:
    """For each stress level S, compute net = forward_ret - fees - funding - S*2.

    Stress applies to BOTH legs (entry + exit), so a 10bps stress level adds
    20bps of slippage to the cost. Result is keyed `net_at_<S>bps`.
    Also returns `cost_unsurvivable` flag = True iff net at COST_UNSURVIVABLE_STRESS_BPS
    is non-positive (the hard reject rule from the MAD consensus).
    """

    if forward_ret_bps is None:
        return {
            "available": False,
            "cost_unsurvivable": False,
        }
    fee_total = float(breakdown.get("entry_fee_bps", 0.0)) + float(breakdown.get("exit_fee_bps", 0.0))
    funding = float(breakdown.get("funding_bps", 0.0))
    base_net = forward_ret_bps - fee_total - max(funding, 0.0)
    matrix: dict[str, float] = {}
    for stress in stress_levels_bps:
        matrix[f"net_at_{stress}bps"] = round(base_net - 2.0 * stress, 6)
    cost_unsurvivable = matrix[f"net_at_{COST_UNSURVIVABLE_STRESS_BPS}bps"] <= 0.0
    return {
        "available": True,
        "base_net_bps": round(base_net, 6),
        **matrix,
        "cost_unsurvivable": cost_unsurvivable,
    }


def _evaluate_decision(
    client: Any,
    row: dict[str, Any],
    *,
    forward_minutes: int,
    cache_dir: Path | None = None,
    calibration: CostCalibration | None = None,
    funding_rate_8h: float = DEFAULT_FUNDING_RATE_8H,
) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "").upper()
    timestamp = _parse_timestamp(str(row.get("timestamp") or ""))
    start_ms = int(timestamp.timestamp() * 1000)
    end_ms = int((timestamp + timedelta(minutes=forward_minutes + 1)).timestamp() * 1000)
    effective_cache_dir = cache_dir if cache_dir is not None else Path("quant_runtime_paper50") / "cache" / "klines"
    bars = sorted(
        fetch_klines_cached(
            client.get_klines,
            symbol=symbol,
            start_ms=start_ms,
            end_ms=end_ms,
            forward_minutes=forward_minutes,
            cache_dir=effective_cache_dir,
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
    cost_breakdown = _decompose_costs(
        symbol=symbol,
        direction=direction,
        upstream_cost_bps=cost_bps,
        calibration=calibration,
        forward_minutes=forward_minutes,
        funding_rate_8h=funding_rate_8h,
    )
    slippage_stress = _compute_slippage_stress(
        forward_ret_bps=forward_ret,
        breakdown=cost_breakdown,
    )
    label = _label_result(
        net_after_cost_bps=net_after_cost,
        mfe_bps=mfe_bps,
        mae_bps=mae_bps,
        cost_bps=cost_bps,
    )
    if slippage_stress.get("cost_unsurvivable"):
        # MAD consensus hard reject rule: candidate dies at 10bps stress.
        label = "cost_unsurvivable"
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
        "cost_breakdown": cost_breakdown,
        "slippage_stress": slippage_stress,
        "rejection_reasons": list(row.get("rejection_reasons") or []),
        "divergence_code": row.get("divergence_code") or "",
    }


def _summarize(results: list[dict[str, Any]], *, symbols: tuple[str, ...]) -> dict[str, Any]:
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_direction: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        by_symbol[str(row.get("symbol") or "")].append(row)
        by_direction[str(row.get("direction") or "unknown")].append(row)

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
        unsurvivable = [row for row in rows if row.get("label") == "cost_unsurvivable"]
        survivable_at_10bps = [
            row
            for row in rows
            if (row.get("slippage_stress") or {}).get("available")
            and (row["slippage_stress"].get(f"net_at_{COST_UNSURVIVABLE_STRESS_BPS}bps") or 0.0) > 0.0
        ]
        evaluated_with_stress = [row for row in rows if (row.get("slippage_stress") or {}).get("available")]
        survival_rate = (
            round(len(survivable_at_10bps) / len(evaluated_with_stress), 6)
            if evaluated_with_stress
            else None
        )
        symbol_summaries[symbol] = {
            "decision_count": len(rows),
            "label_counts": dict(label_counts),
            "avg_net_after_cost_bps": round(sum(net_values) / len(net_values), 6) if net_values else None,
            "best_net_after_cost_bps": round(max(net_values), 6) if net_values else None,
            "worst_net_after_cost_bps": round(min(net_values), 6) if net_values else None,
            "cost_unsurvivable_count": len(unsurvivable),
            "survival_at_10bps_rate": survival_rate,
            "verdict": verdict,
            "recent_possible_missed_entries": possible[-5:],
        }

    side_summaries: dict[str, dict[str, Any]] = {}
    for direction in ("long", "short"):
        rows = by_direction.get(direction, [])
        label_counts = Counter(str(row.get("label") or "unknown") for row in rows)
        net_values = [
            float(row["net_after_cost_bps"])
            for row in rows
            if row.get("net_after_cost_bps") is not None
        ]
        possible = [row for row in rows if row.get("label") == "possible_missed_entry"]
        unsurvivable = [row for row in rows if row.get("label") == "cost_unsurvivable"]
        survivable_at_10bps = [
            row
            for row in rows
            if (row.get("slippage_stress") or {}).get("available")
            and (row["slippage_stress"].get(f"net_at_{COST_UNSURVIVABLE_STRESS_BPS}bps") or 0.0) > 0.0
        ]
        evaluated_with_stress = [row for row in rows if (row.get("slippage_stress") or {}).get("available")]
        survival_rate = (
            round(len(survivable_at_10bps) / len(evaluated_with_stress), 6)
            if evaluated_with_stress
            else None
        )
        side_summaries[direction] = {
            "decision_count": len(rows),
            "label_counts": dict(label_counts),
            "possible_missed_entry_count": len(possible),
            "avg_net_after_cost_bps": round(sum(net_values) / len(net_values), 6) if net_values else None,
            "best_net_after_cost_bps": round(max(net_values), 6) if net_values else None,
            "worst_net_after_cost_bps": round(min(net_values), 6) if net_values else None,
            "cost_unsurvivable_count": len(unsurvivable),
            "survival_at_10bps_rate": survival_rate,
            "symbol_counts": dict(Counter(str(row.get("symbol") or "") for row in rows)),
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
        "side_summaries": side_summaries,
        "symbol_summaries": symbol_summaries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-base", default="quant_runtime_paper50")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--forward-minutes", type=int, default=15)
    parser.add_argument("--min-age-minutes", type=int, default=16)
    parser.add_argument("--per-symbol-limit", type=int, default=20)
    parser.add_argument(
        "--decisions-path",
        action="append",
        default=[],
        help="Explicit decisions.jsonl path; may be provided multiple times.",
    )
    parser.add_argument("--write-latest", action="store_true")
    parser.add_argument(
        "--calibration-path",
        default=None,
        help="Cost calibration JSON. Defaults to <output-base>/artifacts/cost_calibration.json.",
    )
    parser.add_argument(
        "--funding-rate-8h",
        type=float,
        default=DEFAULT_FUNDING_RATE_8H,
        help="Funding rate per 8h (fractional, e.g. 0.0001 = 1bp/8h). Used for cost decomposition.",
    )
    args = parser.parse_args()

    symbols = tuple(symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip())
    output_base = Path(args.output_base)
    decision_paths = [Path(path) for path in args.decisions_path] or _default_decision_paths(output_base)
    rows = _load_decisions(decision_paths, symbols=set(symbols), min_age_minutes=args.min_age_minutes)
    rows = [row for row in rows if _is_blocked_entry(row)]
    per_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        per_symbol[str(row.get("symbol") or "").upper()].append(row)
    selected: list[dict[str, Any]] = []
    for symbol in symbols:
        selected.extend(per_symbol[symbol][-max(args.per_symbol_limit, 1):])

    client = build_exchange_rest_client(exchange="bitget", allow_insecure_ssl=True, allow_missing_credentials=True)
    cache_dir = output_base / "cache" / "klines"
    calibration_path = (
        Path(args.calibration_path)
        if args.calibration_path is not None
        else output_base / "artifacts" / "cost_calibration.json"
    )
    calibration = load_cost_calibration(calibration_path)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for row in selected:
        try:
            results.append(
                _evaluate_decision(
                    client,
                    row,
                    forward_minutes=max(args.forward_minutes, 1),
                    cache_dir=cache_dir,
                    calibration=calibration,
                    funding_rate_8h=args.funding_rate_8h,
                )
            )
        except Exception as exc:
            errors.append(
                {
                    "timestamp": str(row.get("timestamp") or ""),
                    "symbol": str(row.get("symbol") or ""),
                    "error": str(exc),
                }
            )

    attempted = len(results) + len(errors)
    coverage_rate = (len(results) / attempted) if attempted > 0 else 0.0
    error_rate = (len(errors) / attempted) if attempted > 0 else 0.0
    untrusted = attempted == 0 or coverage_rate < 0.95 or error_rate > 0.05

    payload = _summarize(results, symbols=symbols)
    payload["error_count"] = len(errors)
    payload["errors"] = errors[:20]
    payload["attempted_count"] = attempted
    payload["coverage_rate"] = round(coverage_rate, 6)
    payload["error_rate"] = round(error_rate, 6)
    payload["untrusted"] = untrusted
    payload["calibration_meta"] = {
        "path": str(calibration_path),
        "loaded": calibration is not None,
        "slippage_untrusted": bool(calibration.slippage_untrusted) if calibration is not None else True,
        "global_empirical_fee_bps": float(calibration.global_empirical_fee_bps) if calibration is not None else None,
        "funding_rate_8h": args.funding_rate_8h,
    }
    cost_unsurvivable_total = sum(1 for row in results if row.get("label") == "cost_unsurvivable")
    payload["cost_unsurvivable_count"] = cost_unsurvivable_total
    if results:
        survivable = sum(
            1
            for row in results
            if (row.get("slippage_stress") or {}).get("available")
            and (row["slippage_stress"].get(f"net_at_{COST_UNSURVIVABLE_STRESS_BPS}bps") or 0.0) > 0.0
        )
        evaluable = sum(1 for row in results if (row.get("slippage_stress") or {}).get("available"))
        payload["survival_at_10bps_rate"] = round(survivable / evaluable, 6) if evaluable else None
    else:
        payload["survival_at_10bps_rate"] = None
    if args.write_latest:
        artifact_dir = Path(args.output_base) / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        latest_path = artifact_dir / "paper50_counterfactual_latest.json"
        if results:
            latest_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        else:
            (artifact_dir / "paper50_counterfactual_last_error.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
