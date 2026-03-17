from __future__ import annotations

import json
from collections import Counter, defaultdict
import json
from pathlib import Path
from datetime import datetime, timezone
from pathlib import Path
import shutil

from quant_binance.models import DecisionIntent
from quant_binance.observability.log_store import _json_ready


def _active_exchange_futures_positions(
    live_positions: list[dict[str, object]] | tuple[dict[str, object], ...] | None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for position in live_positions or []:
        total = float(position.get("total") or position.get("available") or 0.0)
        if total <= 0.0:
            continue
        rows.append(dict(position))
    return rows


def _futures_position_sync_payload(
    *,
    open_futures_positions: list[dict[str, object]] | None,
    live_positions: list[dict[str, object]] | tuple[dict[str, object], ...] | None,
) -> dict[str, object]:
    paper_open_futures_positions = list(open_futures_positions or [])
    exchange_live_futures_positions = _active_exchange_futures_positions(live_positions)
    adopted_futures_positions = [
        dict(position)
        for position in paper_open_futures_positions
        if str(position.get("origin", "")).strip().lower() == "adopted"
        or bool(position.get("adopted_at"))
        or bool(position.get("adoption_source"))
    ]
    paper_symbols = {
        str(position.get("symbol", ""))
        for position in paper_open_futures_positions
        if str(position.get("symbol", ""))
    }
    exchange_symbols = {
        str(position.get("symbol", ""))
        for position in exchange_live_futures_positions
        if str(position.get("symbol", ""))
    }
    missing_in_paper = sorted(exchange_symbols - paper_symbols)
    missing_on_exchange = sorted(paper_symbols - exchange_symbols)
    mismatch_details = {
        "missing_in_paper": missing_in_paper,
        "missing_on_exchange": missing_on_exchange,
    }
    pending_external_futures_positions = [
        dict(position)
        for position in exchange_live_futures_positions
        if str(position.get("symbol", "")) in set(missing_in_paper)
    ]
    return {
        "paper_open_futures_positions": paper_open_futures_positions,
        "paper_open_futures_position_count": len(paper_open_futures_positions),
        "adopted_futures_positions": adopted_futures_positions,
        "adopted_futures_position_count": len(adopted_futures_positions),
        "exchange_live_futures_positions": exchange_live_futures_positions,
        "exchange_live_futures_position_count": len(exchange_live_futures_positions),
        "pending_external_futures_positions": pending_external_futures_positions,
        "pending_external_futures_position_count": len(pending_external_futures_positions),
        "futures_position_mismatch": bool(missing_in_paper or missing_on_exchange),
        "futures_position_mismatch_details": mismatch_details,
    }


def _aggregate_closed_trades(closed_trades: list[dict[str, object]] | tuple[dict[str, object], ...]) -> tuple[list[dict[str, object]], dict[str, int], float]:
    by_symbol: dict[str, dict[str, float | int | str]] = defaultdict(
        lambda: {
            "symbol": "",
            "market": "",
            "trade_count": 0,
            "realized_pnl_usd_estimate": 0.0,
            "average_return_bps_estimate": 0.0,
        }
    )
    return_sums: dict[str, float] = defaultdict(float)
    exit_reasons = Counter()
    total_realized = 0.0
    for trade in closed_trades:
        symbol = str(trade.get("symbol", ""))
        market = str(trade.get("market", ""))
        pnl = float(trade.get("realized_pnl_usd_estimate", 0.0))
        bps = float(trade.get("realized_return_bps_estimate", 0.0))
        reason = str(trade.get("exit_reason", ""))
        row = by_symbol[symbol]
        row["symbol"] = symbol
        row["market"] = market
        row["trade_count"] = int(row["trade_count"]) + 1
        row["realized_pnl_usd_estimate"] = float(row["realized_pnl_usd_estimate"]) + pnl
        return_sums[symbol] += bps
        total_realized += pnl
        if reason:
            exit_reasons[reason] += 1
    rows: list[dict[str, object]] = []
    for symbol, row in by_symbol.items():
        count = int(row["trade_count"])
        rows.append(
            {
                "symbol": row["symbol"],
                "market": row["market"],
                "trade_count": count,
                "realized_pnl_usd_estimate": round(float(row["realized_pnl_usd_estimate"]), 6),
                "average_return_bps_estimate": round(return_sums[symbol] / count, 6) if count else 0.0,
            }
        )
    rows.sort(key=lambda item: (-float(item["realized_pnl_usd_estimate"]), str(item["symbol"])))
    return rows, dict(sorted(exit_reasons.items())), round(total_realized, 6)




def _aggregate_live_order_outcomes(live_orders: list[dict[str, object]] | tuple[dict[str, object], ...] | None) -> dict[str, object]:
    orders = list(live_orders or [])
    if not orders:
        return {
            "execution_outcome_counts": {},
            "accepted_live_order_count": 0,
            "rejected_live_order_count": 0,
            "avg_fill_ratio": 0.0,
            "avg_slippage_bps": 0.0,
            "avg_realized_edge_bps": 0.0,
            "avg_expected_edge_bps": 0.0,
            "avg_edge_retention_ratio": 0.0,
            "protection_degraded_count": 0,
            "protection_degraded_rate": 0.0,
            "realized_vs_expected_edge_gap_bps": 0.0,
            "execution_audit_by_symbol": [],
        }

    counts = Counter()
    accepted = 0
    rejected = 0
    fill_ratio_sum = 0.0
    slippage_values: list[float] = []
    realized_edge_values: list[float] = []
    expected_edge_values: list[float] = []
    retention_values: list[float] = []
    protection_degraded_count = 0
    by_symbol: dict[str, dict[str, float | int | str]] = defaultdict(
        lambda: {
            "symbol": "",
            "live_order_count": 0,
            "accepted_count": 0,
            "rejected_count": 0,
            "avg_fill_ratio": 0.0,
            "avg_slippage_bps": 0.0,
            "avg_realized_edge_bps": 0.0,
            "avg_expected_edge_bps": 0.0,
            "avg_edge_retention_ratio": 0.0,
            "protection_degraded_count": 0,
            "protection_degraded_rate": 0.0,
            "realized_vs_expected_edge_gap_bps": 0.0,
        }
    )
    fill_sums: dict[str, float] = defaultdict(float)
    slip_sums: dict[str, float] = defaultdict(float)
    slip_counts: dict[str, int] = defaultdict(int)
    realized_sums: dict[str, float] = defaultdict(float)
    realized_counts: dict[str, int] = defaultdict(int)
    expected_sums: dict[str, float] = defaultdict(float)
    retention_sums: dict[str, float] = defaultdict(float)
    retention_counts: dict[str, int] = defaultdict(int)

    for order in orders:
        status = str(order.get("fill_status") or ("accepted" if order.get("accepted") else "reject") or "unknown")
        symbol = str(order.get("symbol", ""))
        counts[status] += 1
        row = by_symbol[symbol]
        row["symbol"] = symbol
        row["live_order_count"] = int(row["live_order_count"]) + 1

        accepted_flag = bool(order.get("accepted", False))
        if accepted_flag:
            accepted += 1
            row["accepted_count"] = int(row["accepted_count"]) + 1
        else:
            rejected += 1
            row["rejected_count"] = int(row["rejected_count"]) + 1

        fill_ratio = float(order.get("fill_ratio", 0.0) or 0.0)
        fill_ratio_sum += fill_ratio
        fill_sums[symbol] += fill_ratio

        slippage = order.get("slippage_bps")
        if slippage is not None:
            slip = float(slippage or 0.0)
            slippage_values.append(slip)
            slip_sums[symbol] += slip
            slip_counts[symbol] += 1

        realized = order.get("realized_edge_bps")
        if realized is not None:
            realized_value = float(realized or 0.0)
            realized_edge_values.append(realized_value)
            realized_sums[symbol] += realized_value
            realized_counts[symbol] += 1

        expected = float(order.get("expected_net_edge_bps", order.get("net_expected_edge_bps", 0.0)) or 0.0)
        expected_edge_values.append(expected)
        expected_sums[symbol] += expected
        if expected > 0.0 and realized is not None:
            retention = max(min(float(realized or 0.0) / expected, 2.0), -2.0)
            retention_values.append(retention)
            retention_sums[symbol] += retention
            retention_counts[symbol] += 1
        if order.get("protection_error"):
            protection_degraded_count += 1
            row["protection_degraded_count"] = int(row["protection_degraded_count"]) + 1

    rows: list[dict[str, object]] = []
    for symbol, row in by_symbol.items():
        count = int(row["live_order_count"])
        expected_avg = expected_sums[symbol] / count if count else 0.0
        realized_avg = realized_sums[symbol] / realized_counts[symbol] if realized_counts[symbol] else 0.0
        row["avg_fill_ratio"] = round(fill_sums[symbol] / count, 6) if count else 0.0
        row["avg_slippage_bps"] = round(slip_sums[symbol] / slip_counts[symbol], 6) if slip_counts[symbol] else 0.0
        row["avg_realized_edge_bps"] = round(realized_avg, 6)
        row["avg_expected_edge_bps"] = round(expected_avg, 6)
        row["avg_edge_retention_ratio"] = round(retention_sums[symbol] / retention_counts[symbol], 6) if retention_counts[symbol] else 0.0
        row["realized_vs_expected_edge_gap_bps"] = round(realized_avg - expected_avg, 6)
        rows.append(dict(row))
    rows.sort(key=lambda item: (float(item["realized_vs_expected_edge_gap_bps"]), float(item["avg_realized_edge_bps"])), reverse=True)

    avg_expected = sum(expected_edge_values) / len(expected_edge_values) if expected_edge_values else 0.0
    avg_realized = sum(realized_edge_values) / len(realized_edge_values) if realized_edge_values else 0.0
    return {
        "execution_outcome_counts": dict(sorted(counts.items())),
        "accepted_live_order_count": accepted,
        "rejected_live_order_count": rejected,
        "avg_fill_ratio": round(fill_ratio_sum / len(orders), 6),
        "avg_slippage_bps": round(sum(slippage_values) / len(slippage_values), 6) if slippage_values else 0.0,
        "avg_realized_edge_bps": round(avg_realized, 6),
        "avg_expected_edge_bps": round(avg_expected, 6),
        "avg_edge_retention_ratio": round(sum(retention_values) / len(retention_values), 6) if retention_values else 0.0,
        "protection_degraded_count": protection_degraded_count,
        "protection_degraded_rate": round(protection_degraded_count / len(orders), 6),
        "realized_vs_expected_edge_gap_bps": round(avg_realized - avg_expected, 6),
        "execution_audit_by_symbol": rows,
    }



def _performance_bucket(order: dict[str, object]) -> tuple[str, str, str, str, str]:
    symbol = str(order.get("symbol", "") or "UNKNOWN")
    side = str(order.get("side", "") or "unknown")
    regime = "major" if symbol in {"BTCUSDT", "ETHUSDT"} else "alt"
    expected = float(order.get("expected_net_edge_bps", order.get("net_expected_edge_bps", 0.0)) or 0.0)
    fill_ratio = float(order.get("fill_ratio", 0.0) or 0.0)
    setup_class = "high_edge" if expected >= 15.0 else "standard_edge"
    execution_quality_state = "degraded" if order.get("protection_error") or fill_ratio < 0.85 or not bool(order.get("accepted", False)) else "healthy"
    return symbol, regime, setup_class, side, execution_quality_state


def build_performance_attribution(live_orders: list[dict[str, object]] | tuple[dict[str, object], ...] | None) -> list[dict[str, object]]:
    orders = list(live_orders or [])
    buckets: dict[tuple[str, str, str, str, str], dict[str, float | int | str]] = defaultdict(
        lambda: {
            "symbol": "",
            "regime": "",
            "setup_class": "",
            "side": "",
            "execution_quality_state": "",
            "sample_count": 0,
            "accepted_count": 0,
            "rejected_count": 0,
            "realized_edge_sum": 0.0,
            "expected_edge_sum": 0.0,
            "retention_sum": 0.0,
            "retention_count": 0,
            "protection_degraded_count": 0,
        }
    )
    for order in orders:
        key = _performance_bucket(order)
        row = buckets[key]
        row["symbol"], row["regime"], row["setup_class"], row["side"], row["execution_quality_state"] = key
        row["sample_count"] = int(row["sample_count"]) + 1
        if bool(order.get("accepted", False)):
            row["accepted_count"] = int(row["accepted_count"]) + 1
        else:
            row["rejected_count"] = int(row["rejected_count"]) + 1
        expected = float(order.get("expected_net_edge_bps", order.get("net_expected_edge_bps", 0.0)) or 0.0)
        realized = float(order.get("realized_edge_bps", 0.0) or 0.0)
        row["expected_edge_sum"] = float(row["expected_edge_sum"]) + expected
        row["realized_edge_sum"] = float(row["realized_edge_sum"]) + realized
        if expected > 0.0:
            row["retention_sum"] = float(row["retention_sum"]) + max(min(realized / expected, 2.0), -2.0)
            row["retention_count"] = int(row["retention_count"]) + 1
        if order.get("protection_error"):
            row["protection_degraded_count"] = int(row["protection_degraded_count"]) + 1
    rows: list[dict[str, object]] = []
    for row in buckets.values():
        sample_count = int(row["sample_count"])
        accepted_count = int(row["accepted_count"])
        rejected_count = int(row["rejected_count"])
        retention_count = int(row["retention_count"])
        rows.append({
            "symbol": row["symbol"],
            "regime": row["regime"],
            "setup_class": row["setup_class"],
            "side": row["side"],
            "execution_quality_state": row["execution_quality_state"],
            "sample_count": sample_count,
            "avg_realized_edge_bps": round(float(row["realized_edge_sum"]) / sample_count, 6) if sample_count else 0.0,
            "avg_expected_edge_bps": round(float(row["expected_edge_sum"]) / sample_count, 6) if sample_count else 0.0,
            "avg_edge_retention_ratio": round(float(row["retention_sum"]) / retention_count, 6) if retention_count else 0.0,
            "reject_rate": round(rejected_count / sample_count, 6) if sample_count else 0.0,
            "protection_degraded_rate": round(int(row["protection_degraded_count"]) / sample_count, 6) if sample_count else 0.0,
        })
    rows.sort(key=lambda item: (str(item["symbol"]), str(item["setup_class"]), str(item["side"]), str(item["execution_quality_state"])))
    return rows


def build_auto_tune_policy(attribution_rows: list[dict[str, object]] | tuple[dict[str, object], ...]) -> dict[str, object]:
    adjustments: list[dict[str, object]] = []
    for row in attribution_rows:
        sample_count = int(row.get("sample_count", 0) or 0)
        if sample_count < 3:
            continue
        retention = float(row.get("avg_edge_retention_ratio", 0.0) or 0.0)
        realized = float(row.get("avg_realized_edge_bps", 0.0) or 0.0)
        reject_rate = float(row.get("reject_rate", 0.0) or 0.0)
        degraded_rate = float(row.get("protection_degraded_rate", 0.0) or 0.0)
        action = "keep"
        size_multiplier = 1.0
        reason = "STABLE"
        if retention < 0.5 or realized <= 0.0 or reject_rate > 0.1 or degraded_rate > 0.1:
            action = "demote"
            size_multiplier = 0.75
            reason = "WEAK_ATTRIBUTION"
        elif retention >= 0.95 and realized > 0.0 and reject_rate <= 0.01 and degraded_rate <= 0.01 and str(row.get("regime", "")) == "major":
            action = "aggressive_promote"
            size_multiplier = 1.25
            reason = "ELITE_ATTRIBUTION"
        elif retention >= 0.8 and realized > 0.0 and reject_rate <= 0.03 and degraded_rate <= 0.03:
            action = "promote"
            size_multiplier = 1.1
            reason = "STRONG_ATTRIBUTION"
        leverage_multiplier = round(min(max(size_multiplier, 0.0), 1.2), 6)
        entry_threshold_bps = -1.5 if action == "aggressive_promote" else (-0.5 if action == "promote" else (1.5 if action == "demote" else 0.0))
        expected_profit_floor_bps = -2.0 if action == "aggressive_promote" else (-1.0 if action == "promote" else (2.0 if action == "demote" else 0.0))
        symbol_bias = "majors_only" if action in {"aggressive_promote", "promote"} and str(row.get("regime", "")) == "major" else "neutral"
        adjustments.append({
            "symbol": row.get("symbol", ""),
            "regime": row.get("regime", ""),
            "setup_class": row.get("setup_class", ""),
            "side": row.get("side", ""),
            "execution_quality_state": row.get("execution_quality_state", ""),
            "sample_count": sample_count,
            "action": action,
            "size_multiplier": size_multiplier,
            "leverage_multiplier": leverage_multiplier,
            "entry_threshold_bps": entry_threshold_bps,
            "expected_profit_floor_bps": expected_profit_floor_bps,
            "symbol_bias": symbol_bias,
            "reason": reason,
        })
    policy_status = "insufficient_data" if not adjustments else "candidate_ready"
    return {"status": policy_status, "adjustments": adjustments}


def build_promotion_verdict(candidate_policy: dict[str, object]) -> dict[str, object]:
    adjustments = list(candidate_policy.get("adjustments", []))
    if not adjustments:
        return {"status": "keep", "reasons": ["INSUFFICIENT_ATTRIBUTION_DATA"]}
    aggressive_count = sum(1 for item in adjustments if str(item.get("action", "")) == "aggressive_promote")
    promote_count = sum(1 for item in adjustments if str(item.get("action", "")) in {"promote", "aggressive_promote"})
    demote_count = sum(1 for item in adjustments if str(item.get("action", "")) == "demote")
    if demote_count > 0 and promote_count == 0:
        return {"status": "demote", "reasons": ["CANDIDATE_POLICY_WEAK"]}
    if aggressive_count > 0 and demote_count == 0:
        return {"status": "promote_aggressive", "reasons": ["CANDIDATE_POLICY_ELITE"]}
    if promote_count > 0 and demote_count == 0:
        return {"status": "promote", "reasons": ["CANDIDATE_POLICY_STRONG"]}
    if demote_count >= promote_count + 2:
        return {"status": "disable", "reasons": ["CANDIDATE_POLICY_UNSTABLE"]}
    return {"status": "keep", "reasons": ["CANDIDATE_POLICY_MIXED"]}

def _major_symbol_operational_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [row for row in rows if str(row.get("symbol", "")) in {"BTCUSDT", "ETHUSDT"}]










def load_validation_runner_evidence(base_path: str | Path | None) -> dict[str, object]:
    if base_path is None:
        return {}
    root = Path(base_path)
    candidate_paths = [
        root,
        root / "policy_validation.json",
        root / "policy_comparison.json",
        root / "validation_report.json",
        root / "performance_report.json",
        root / "summary.json",
    ]
    seen: set[Path] = set()
    for candidate in candidate_paths:
        path = candidate
        if path in seen:
            continue
        seen.add(path)
        if path.is_dir():
            continue
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        if "policy_validation" in payload and isinstance(payload.get("policy_validation"), dict):
            payload = dict(payload["policy_validation"])
        evidence = dict(payload.get("evidence", {}) or {})
        if "max_drawdown_pct" in payload and "runner_max_drawdown_pct" not in evidence:
            evidence["runner_max_drawdown_pct"] = float(payload.get("max_drawdown_pct", 0.0) or 0.0)
        if "total_return_pct" in payload and "runner_total_return_pct" not in evidence:
            evidence["runner_total_return_pct"] = float(payload.get("total_return_pct", 0.0) or 0.0)
        if "shadow_alignment_score" in payload and "runner_shadow_alignment_score" not in evidence:
            evidence["runner_shadow_alignment_score"] = float(payload.get("shadow_alignment_score", 0.0) or 0.0)
        if evidence:
            return evidence
    return {}


def merge_policy_validation_evidence(
    attribution_rows: list[dict[str, object]] | tuple[dict[str, object], ...],
    runner_evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    evidence = _replay_like_validation_evidence(attribution_rows)
    for key, value in dict(runner_evidence or {}).items():
        evidence[key] = value
    runner_max_drawdown_pct = float(evidence.get("runner_max_drawdown_pct", 0.0) or 0.0)
    if runner_max_drawdown_pct > 0.0:
        evidence["replay_like_drawdown_ratio"] = round(max(float(evidence.get("replay_like_drawdown_ratio", 0.0) or 0.0), runner_max_drawdown_pct / 100.0), 6)
    runner_shadow_alignment_score = float(evidence.get("runner_shadow_alignment_score", 0.0) or 0.0)
    if runner_shadow_alignment_score > 0.0:
        evidence["shadow_alignment_score"] = round(min(max(float(evidence.get("shadow_alignment_score", 0.0) or 0.0), runner_shadow_alignment_score), 1.0), 6)
    candidate_delta = float(evidence.get("candidate_vs_current_score_delta", 0.0) or 0.0)
    if candidate_delta > 0.1:
        evidence["comparison_alignment_score"] = round(min(1.0, 0.5 + candidate_delta), 6)
    elif candidate_delta < -0.1:
        evidence["comparison_alignment_score"] = round(max(0.0, 0.5 + candidate_delta), 6)
    return evidence

def _replay_like_validation_evidence(attribution_rows: list[dict[str, object]] | tuple[dict[str, object], ...]) -> dict[str, object]:
    rows = list(attribution_rows)
    if not rows:
        return {
            "sample_count": 0,
            "avg_retention": 0.0,
            "avg_realized_edge_bps": 0.0,
            "max_reject_rate": 1.0,
            "max_protection_degraded_rate": 1.0,
            "replay_like_drawdown_ratio": 1.0,
            "shadow_alignment_score": 0.0,
        }
    avg_retention = sum(float(row.get("avg_edge_retention_ratio", 0.0) or 0.0) for row in rows) / len(rows)
    avg_realized = sum(float(row.get("avg_realized_edge_bps", 0.0) or 0.0) for row in rows) / len(rows)
    max_reject_rate = max(float(row.get("reject_rate", 0.0) or 0.0) for row in rows)
    max_degraded_rate = max(float(row.get("protection_degraded_rate", 0.0) or 0.0) for row in rows)
    replay_like_drawdown_ratio = max(0.0, 1.0 - max(avg_retention, 0.0))
    shadow_alignment_score = max(0.0, min(1.0, avg_retention * (1.0 - max_reject_rate)))
    return {
        "sample_count": len(rows),
        "avg_retention": round(avg_retention, 6),
        "avg_realized_edge_bps": round(avg_realized, 6),
        "max_reject_rate": round(max_reject_rate, 6),
        "max_protection_degraded_rate": round(max_degraded_rate, 6),
        "replay_like_drawdown_ratio": round(replay_like_drawdown_ratio, 6),
        "shadow_alignment_score": round(shadow_alignment_score, 6),
    }

def build_policy_validation(candidate_policy: dict[str, object], promotion_verdict: dict[str, object], operational_verdict: dict[str, object], attribution_rows: list[dict[str, object]] | tuple[dict[str, object], ...] = (), runner_evidence: dict[str, object] | None = None) -> dict[str, object]:
    candidate_adjustments = list(candidate_policy.get("adjustments", []))
    verdict_status = str(promotion_verdict.get("status", "keep"))
    operational_status = str(operational_verdict.get("status", "hold"))
    evidence = merge_policy_validation_evidence(attribution_rows, runner_evidence)
    reasons: list[str] = []
    status = "fail"
    if not candidate_adjustments:
        reasons.append("NO_CANDIDATE_ADJUSTMENTS")
    else:
        status = "pass"
        reasons.append("CANDIDATE_DATA_AVAILABLE")
    if operational_status == "stop":
        status = "fail"
        reasons.append("OPERATIONAL_STOP_ACTIVE")
    elif operational_status == "hold" and verdict_status in {"promote", "promote_aggressive"}:
        reasons.append("PROMOTION_BLOCKED_BY_HOLD")
    elif verdict_status in {"promote", "promote_aggressive", "demote"}:
        reasons.append("PROMOTION_PATH_VALIDATED")
    else:
        reasons.append("NO_PROMOTION_ACTION")
    if evidence["replay_like_drawdown_ratio"] > 0.45:
        status = "fail"
        reasons.append("REPLAY_DRAWDOWN_TOO_HIGH")
    if evidence["shadow_alignment_score"] < 0.45:
        status = "fail"
        reasons.append("SHADOW_ALIGNMENT_TOO_LOW")
    if float(evidence.get("candidate_vs_current_score_delta", 0.0) or 0.0) < -0.1:
        status = "fail"
        reasons.append("CANDIDATE_UNDERPERFORMS_CURRENT_POLICY")
    elif float(evidence.get("candidate_vs_current_score_delta", 0.0) or 0.0) > 0.1:
        reasons.append("CANDIDATE_OUTPERFORMS_CURRENT_POLICY")
    return {"status": status, "reasons": reasons, "evidence": evidence}


def build_persisted_policy_state(
    previous_state: dict[str, object] | None,
    candidate_policy: dict[str, object],
    promotion_verdict: dict[str, object],
    operational_verdict: dict[str, object],
    validation: dict[str, object],
) -> dict[str, object]:
    previous_state = dict(previous_state or {})
    previous_active = dict(previous_state.get("active_policy", {}) or {})
    previous_version = int(previous_state.get("version", 0) or 0)
    verdict_status = str(promotion_verdict.get("status", "keep"))
    validation_status = str(validation.get("status", "fail"))
    if validation_status == "pass" and verdict_status in {"promote", "promote_aggressive", "demote"}:
        active_policy = dict(candidate_policy)
        active_policy["status"] = verdict_status
        lifecycle = "promoted" if verdict_status.startswith("promote") else "demoted"
        version = previous_version + 1
    elif (
        str(operational_verdict.get("status", "")) == "stop"
        or float(dict(validation.get("evidence", {}) or {}).get("replay_like_drawdown_ratio", 0.0) or 0.0) > 0.5
    ) and previous_active:
        active_policy = previous_active
        lifecycle = "rolled_back"
        version = previous_version + 1
    elif previous_active:
        active_policy = previous_active
        lifecycle = "kept"
        version = previous_version
    else:
        active_policy = {"status": "baseline", "adjustments": []}
        lifecycle = "baseline"
        version = previous_version
    return {
        "version": version,
        "status": lifecycle,
        "active_policy": active_policy,
        "candidate_policy": candidate_policy,
        "promotion_verdict": promotion_verdict,
        "operational_verdict": operational_verdict,
        "policy_validation": validation,
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }


def build_policy_history_entry(policy_state: dict[str, object]) -> dict[str, object]:
    return {
        "updated_at": policy_state.get("updated_at"),
        "version": policy_state.get("version", 0),
        "status": policy_state.get("status", "unknown"),
        "promotion_verdict": dict(policy_state.get("promotion_verdict", {}) or {}),
        "policy_validation": dict(policy_state.get("policy_validation", {}) or {}),
        "active_policy_status": str(dict(policy_state.get("active_policy", {}) or {}).get("status", "unknown")),
        "active_adjustment_count": len(list(dict(policy_state.get("active_policy", {}) or {}).get("adjustments", []))),
    }

def build_policy_state(candidate_policy: dict[str, object], promotion_verdict: dict[str, object]) -> dict[str, object]:
    candidate_adjustments = list(candidate_policy.get("adjustments", []))
    verdict_status = str(promotion_verdict.get("status", "keep"))
    if verdict_status == "disable":
        active_adjustments = [dict(item, action="disabled", size_multiplier=0.0) for item in candidate_adjustments]
        active_status = "disabled"
    elif verdict_status in {"promote", "promote_aggressive", "demote"}:
        active_adjustments = candidate_adjustments
        active_status = verdict_status
    else:
        active_adjustments = [dict(item, action="keep", size_multiplier=1.0, reason="ACTIVE_POLICY_UNCHANGED") for item in candidate_adjustments]
        active_status = "keep"
    return {
        "status": active_status,
        "active_policy": {
            "status": active_status,
            "adjustments": active_adjustments,
        },
        "candidate_policy": candidate_policy,
        "promotion_verdict": promotion_verdict,
    }

def build_operational_verdict(execution_outcomes: dict[str, object]) -> dict[str, object]:
    live_order_count = int(execution_outcomes.get("accepted_live_order_count", 0)) + int(execution_outcomes.get("rejected_live_order_count", 0))
    if live_order_count <= 0:
        return {
            "status": "hold",
            "reasons": ["INSUFFICIENT_LIVE_ORDERS"],
            "metrics": {
                "live_order_count": 0,
                "reject_rate": 0.0,
                "protection_degraded_rate": 0.0,
                "avg_fill_ratio": 0.0,
                "avg_edge_retention_ratio": 0.0,
                "avg_realized_edge_bps": 0.0,
                "realized_vs_expected_edge_gap_bps": 0.0,
            },
        }

    reject_rate = int(execution_outcomes.get("rejected_live_order_count", 0)) / live_order_count
    protection_degraded_rate = float(execution_outcomes.get("protection_degraded_rate", 0.0) or 0.0)
    avg_fill_ratio = float(execution_outcomes.get("avg_fill_ratio", 0.0) or 0.0)
    retention = float(execution_outcomes.get("avg_edge_retention_ratio", 0.0) or 0.0)
    realized = float(execution_outcomes.get("avg_realized_edge_bps", 0.0) or 0.0)
    gap = float(execution_outcomes.get("realized_vs_expected_edge_gap_bps", 0.0) or 0.0)
    major_rows = _major_symbol_operational_rows(list(execution_outcomes.get("execution_audit_by_symbol", [])))

    reasons: list[str] = []
    status = "pass"

    aggressive_pass = (
        live_order_count >= 10
        and retention >= 0.95
        and realized > 0.0
        and gap >= -1.5
        and protection_degraded_rate <= 0.01
        and reject_rate <= 0.01
        and avg_fill_ratio >= 0.97
    )
    strong_pass = (
        live_order_count >= 8
        and retention >= 0.80
        and realized > 0.0
        and gap > -3.0
        and protection_degraded_rate <= 0.02
        and reject_rate <= 0.02
        and avg_fill_ratio >= 0.92
    )

    if retention < 0.40 or realized <= 0.0 or protection_degraded_rate > 0.15 or reject_rate > 0.15:
        status = "stop"
    elif retention < 0.65 or gap <= -8.0 or protection_degraded_rate > 0.05 or reject_rate > 0.05 or avg_fill_ratio < 0.85:
        status = "hold"
    elif aggressive_pass:
        status = "aggressive_pass"
    elif strong_pass:
        status = "strong_pass"

    if live_order_count < 5 and status in {"pass", "strong_pass", "aggressive_pass"}:
        status = "hold"
        reasons.append("INSUFFICIENT_SAMPLE")

    if retention < 0.40:
        reasons.append("EDGE_RETENTION_TOO_LOW")
    elif retention < 0.65:
        reasons.append("EDGE_RETENTION_BELOW_PASS")

    if realized <= 0.0:
        reasons.append("REALIZED_EDGE_NOT_POSITIVE")
    if gap <= -8.0:
        reasons.append("EDGE_GAP_TOO_NEGATIVE")
    if protection_degraded_rate > 0.15:
        reasons.append("PROTECTION_DEGRADED_TOO_HIGH")
    elif protection_degraded_rate > 0.05:
        reasons.append("PROTECTION_DEGRADED_ABOVE_PASS")
    if reject_rate > 0.15:
        reasons.append("REJECT_RATE_TOO_HIGH")
    elif reject_rate > 0.05:
        reasons.append("REJECT_RATE_ABOVE_PASS")
    if avg_fill_ratio < 0.85:
        reasons.append("FILL_RATIO_TOO_LOW")

    if major_rows:
        weak_major_rows = [row for row in major_rows if float(row.get("realized_vs_expected_edge_gap_bps", 0.0) or 0.0) <= -8.0 or float(row.get("avg_realized_edge_bps", 0.0) or 0.0) <= 0.0]
        strong_major_rows = [row for row in major_rows if float(row.get("avg_edge_retention_ratio", 0.0) or 0.0) >= 0.8 and float(row.get("avg_realized_edge_bps", 0.0) or 0.0) > 0.0]
        if weak_major_rows:
            if status in {"pass", "strong_pass"}:
                status = "hold"
            reasons.append("MAJOR_SYMBOL_AUDIT_WEAK")
        elif status == "aggressive_pass" and len(strong_major_rows) < len(major_rows):
            status = "strong_pass"
            reasons.append("MAJOR_SYMBOL_AGGRESSIVE_CONFIRMATION_INCOMPLETE")
        elif status == "strong_pass" and not strong_major_rows:
            status = "pass"
            reasons.append("MAJOR_SYMBOL_CONFIRMATION_INCOMPLETE")

    if status == "aggressive_pass":
        reasons.append("OPERATING_WITH_ELITE_EDGE")
    elif status == "strong_pass":
        reasons.append("OPERATING_WITH_STRONG_EDGE")
    elif not reasons:
        reasons.append("OPERATING_WITHIN_THRESHOLDS")

    return {
        "status": status,
        "reasons": reasons,
        "metrics": {
            "live_order_count": live_order_count,
            "reject_rate": round(reject_rate, 6),
            "protection_degraded_rate": round(protection_degraded_rate, 6),
            "avg_fill_ratio": round(avg_fill_ratio, 6),
            "avg_edge_retention_ratio": round(retention, 6),
            "avg_realized_edge_bps": round(realized, 6),
            "realized_vs_expected_edge_gap_bps": round(gap, 6),
        },
    }


def build_runtime_summary(
    *,
    decisions: list[DecisionIntent] | tuple[DecisionIntent, ...],
    tested_orders: list[dict[str, object]] | None = None,
    live_orders: list[dict[str, object]] | None = None,
    account_snapshot: dict[str, object] | None = None,
    open_orders_snapshot: dict[str, object] | None = None,
    capital_report: dict[str, object] | None = None,
    kill_switch_status: dict[str, object] | None = None,
    observe_only_symbols: list[str] | tuple[str, ...] | None = None,
    open_spot_positions: list[dict[str, object]] | None = None,
    open_futures_positions: list[dict[str, object]] | None = None,
    closed_trades: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    telegram_alerts: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    live_positions: list[dict[str, object]] | tuple[dict[str, object], ...] | None = None,
    self_healing: dict[str, object] | None = None,
) -> dict[str, object]:
    derived_observe_only = {
        decision.symbol
        for decision in decisions
        if "OBSERVE_ONLY_SYMBOL" in decision.rejection_reasons
    }
    combined_observe_only = sorted(set(observe_only_symbols or []).union(derived_observe_only))
    symbol_performance, exit_reason_counts, realized_total = _aggregate_closed_trades(closed_trades or [])
    unrealized_spot_total = round(
        sum(float(position.get("unrealized_pnl_usd_estimate", 0.0)) for position in (open_spot_positions or [])),
        6,
    )
    unrealized_futures_total = round(
        sum(float(position.get("unrealized_pnl_usd_estimate", 0.0)) for position in (open_futures_positions or [])),
        6,
    )
    futures_position_sync = _futures_position_sync_payload(
        open_futures_positions=open_futures_positions,
        live_positions=live_positions,
    )
    execution_outcomes = _aggregate_live_order_outcomes(live_orders)
    performance_attribution = build_performance_attribution(live_orders)
    candidate_policy = build_auto_tune_policy(performance_attribution)
    promotion_verdict = build_promotion_verdict(candidate_policy)
    policy_state = build_policy_state(candidate_policy, promotion_verdict)
    operational_verdict = build_operational_verdict(execution_outcomes)
    runner_evidence = load_validation_runner_evidence(None)
    policy_validation = build_policy_validation(candidate_policy, promotion_verdict, operational_verdict, performance_attribution, runner_evidence)
    rejection_counts = Counter()
    for decision in decisions:
        for reason in decision.rejection_reasons:
            rejection_counts[reason] += 1
    recent_decisions = [
        {
            "symbol": decision.symbol,
            "candidate_mode": decision.candidate_mode,
            "mode": decision.final_mode,
            "side": decision.side,
            "score": round(decision.predictability_score, 2),
            "net_expected_edge_bps": round(decision.net_expected_edge_bps, 6),
            "estimated_round_trip_cost_bps": round(decision.estimated_round_trip_cost_bps, 6),
            "macro_trade_restraint": decision.macro_trade_restraint,
            "execution_quality_trade_restraint": decision.execution_quality_trade_restraint,
            "strategy_size_multiplier": round(decision.strategy_size_multiplier, 6),
            "entry_relaxations": list(decision.entry_relaxation_reasons[:4]),
            "size_boost_reasons": list(decision.size_boost_reasons[:4]),
            "reasons": list(decision.rejection_reasons[:4]),
        }
        for decision in list(decisions)[-5:]
    ]
    return {
        "decision_count": len(decisions),
        "modes": [decision.final_mode for decision in decisions],
        "symbols": sorted({decision.symbol for decision in decisions}),
        "observe_only_symbols": combined_observe_only,
        "open_spot_positions": list(open_spot_positions or []),
        "open_futures_positions": list(open_futures_positions or []),
        "live_positions": list(live_positions or []),
        **futures_position_sync,
        "closed_trades": list(closed_trades or []),
        "telegram_alerts": list(telegram_alerts or []),
        "recent_decisions": recent_decisions,
        "major_entry_relaxation_count": sum(1 for decision in decisions if decision.entry_relaxation_reasons),
        "major_size_boost_count": sum(1 for decision in decisions if decision.size_boost_reasons),
        "top_rejection_reasons": dict(rejection_counts.most_common(8)),
        "exit_reason_counts": exit_reason_counts,
        "symbol_performance": symbol_performance,
        "realized_pnl_usd_estimate": realized_total,
        "unrealized_pnl_usd_estimate": round(unrealized_spot_total + unrealized_futures_total, 6),
        "unrealized_spot_pnl_usd_estimate": unrealized_spot_total,
        "unrealized_futures_pnl_usd_estimate": unrealized_futures_total,
        "tested_order_count": len(tested_orders or []),
        "tested_orders": tested_orders or [],
        "live_order_count": len(live_orders or []),
        "live_orders": live_orders or [],
        **execution_outcomes,
        "performance_attribution": performance_attribution,
        "candidate_policy": candidate_policy,
        "promotion_verdict": promotion_verdict,
        "policy_state": policy_state,
        "policy_validation": policy_validation,
        "operational_verdict": operational_verdict,
        "account_snapshot": account_snapshot or {},
        "open_orders_snapshot": open_orders_snapshot or {},
        "capital_report": capital_report or {},
        "kill_switch": kill_switch_status or {"armed": False, "reasons": []},
        "self_healing": self_healing or {},
    }


def write_runtime_summary(path: str | Path, summary: dict[str, object]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(_json_ready(summary), indent=2, sort_keys=True), encoding="utf-8")
    latest_root = output_path.parent.parent / "latest"
    latest_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output_path, latest_root / "summary.json")
