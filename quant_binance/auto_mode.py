from __future__ import annotations

from typing import Any


_POSITIVE_ACTIONS = {"promote", "aggressive_promote"}
_EXECUTION_QUALITY_BUCKET_ORDER = ("active_policy", "staged_candidate", "baseline_control")


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _coerce_symbol_lifecycle_summary(
    summary: dict[str, Any] | None,
    rows: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> dict[str, object]:
    payload = dict(summary or {})
    if payload:
        payload.setdefault("action_counts", dict(payload.get("action_counts", {}) or {}))
        payload.setdefault("state_counts", dict(payload.get("state_counts", {}) or {}))
        payload.setdefault("actionable_symbol_count", _safe_int(payload.get("actionable_symbol_count")))
        payload.setdefault("actionable_symbols", list(payload.get("actionable_symbols", []) or []))
        payload.setdefault("symbol_count", _safe_int(payload.get("symbol_count")))
        return payload
    action_counts: dict[str, int] = {}
    state_counts: dict[str, int] = {}
    actionable_symbols: list[str] = []
    normalized_rows = [dict(row) for row in list(rows or []) if isinstance(row, dict)]
    for row in normalized_rows:
        action = str(row.get("recommended_action", "keep") or "keep")
        state = str(row.get("target_state", "baseline") or "baseline")
        symbol = str(row.get("symbol", "") or "")
        action_counts[action] = action_counts.get(action, 0) + 1
        state_counts[state] = state_counts.get(state, 0) + 1
        if symbol and action != "keep":
            actionable_symbols.append(symbol)
    return {
        "action_counts": action_counts,
        "state_counts": state_counts,
        "actionable_symbol_count": len(actionable_symbols),
        "actionable_symbols": sorted(actionable_symbols),
        "symbol_count": len(normalized_rows),
    }


def _regime_signal(regime_summary: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None) -> dict[str, object]:
    rows = [dict(row) for row in list(regime_summary or []) if isinstance(row, dict)]
    supportive_modes: list[str] = []
    caution_modes: list[str] = []
    dominant_mode = ""
    dominant_score = float("-inf")
    futures_supportive = False
    futures_negative = False
    for row in rows:
        mode = str(row.get("mode", "") or "")
        decision_count = _safe_int(row.get("decision_count"))
        avg_score = _safe_float(row.get("avg_score"))
        avg_net_edge_bps = _safe_float(row.get("avg_net_edge_bps"))
        if not mode or decision_count <= 0:
            continue
        if decision_count >= 3 and avg_net_edge_bps > 0.0 and avg_score >= 55.0:
            supportive_modes.append(mode)
        if decision_count >= 3 and (avg_net_edge_bps <= 0.0 or avg_score < 50.0):
            caution_modes.append(mode)
        if mode == "futures":
            futures_supportive = decision_count >= 6 and avg_net_edge_bps >= 8.0 and avg_score >= 60.0
            futures_negative = decision_count >= 3 and (avg_net_edge_bps <= 0.0 or avg_score < 50.0)
        row_dominance_score = avg_net_edge_bps + (avg_score / 100.0)
        if dominant_mode == "" or row_dominance_score > dominant_score:
            dominant_mode = mode
            dominant_score = row_dominance_score
    return {
        "rows": rows,
        "supportive_modes": sorted(set(supportive_modes)),
        "caution_modes": sorted(set(caution_modes)),
        "dominant_mode": dominant_mode,
        "futures_supportive": futures_supportive,
        "futures_negative": futures_negative,
    }


def _has_execution_quality_metrics(payload: dict[str, Any] | None) -> bool:
    candidate = dict(payload or {})
    return any(
        key in candidate
        for key in (
            "runner_total_realized_pnl_usd",
            "runner_drawdown_to_pnl_ratio",
            "runner_reject_rate",
            "runner_protection_degraded_rate",
            "runner_avg_edge_retention_ratio",
            "runner_avg_realized_edge_bps",
            "runner_avg_slippage_bps",
            "runner_positive_walk_forward_ratio",
            "total_closed_trade_count",
            "total_live_order_count",
            "micro_live_gate",
        )
    )


def _execution_quality_bucket_payloads(execution_quality: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    payload = dict(execution_quality or {})
    bucket_payloads: dict[str, dict[str, Any]] = {}
    for bucket_name, bucket_payload in dict(payload.get("policy_context_bucket_evidence", {}) or {}).items():
        if isinstance(bucket_payload, dict) and str(bucket_name):
            bucket_payloads[str(bucket_name)] = dict(bucket_payload)
    for bucket_name, bucket_payload in dict(payload.get("policy_evidence_buckets", {}) or {}).items():
        if not isinstance(bucket_payload, dict) or not str(bucket_name):
            continue
        evidence = dict(bucket_payload.get("evidence", {}) or {})
        if evidence:
            bucket_payloads.setdefault(str(bucket_name), evidence)
    return bucket_payloads


def _preferred_execution_quality_payload(execution_quality: dict[str, Any] | None) -> tuple[str, dict[str, Any], str]:
    payload = dict(execution_quality or {})
    bucket_payloads = _execution_quality_bucket_payloads(payload)
    preferred_bucket = str(payload.get("preferred_policy_bucket", "") or "").strip().lower()
    bucket_order: list[str] = []
    if preferred_bucket:
        bucket_order.append(preferred_bucket)
    bucket_order.extend(name for name in _EXECUTION_QUALITY_BUCKET_ORDER if name not in bucket_order)
    bucket_order.extend(
        name
        for name in bucket_payloads
        if name not in bucket_order
    )
    for bucket_name in bucket_order:
        bucket_payload = bucket_payloads.get(bucket_name)
        if bucket_payload and _has_execution_quality_metrics(bucket_payload):
            return bucket_name, bucket_payload, "policy_bucket"
    return "", payload, "root"


def _execution_quality_signal(execution_quality: dict[str, Any] | None) -> dict[str, object]:
    selected_bucket, payload, source = _preferred_execution_quality_payload(execution_quality)
    micro_live_gate = dict(payload.get("micro_live_gate", {}) or {})
    return {
        "available": _has_execution_quality_metrics(payload),
        "total_closed_trade_count": max(
            _safe_int(payload.get("total_closed_trade_count")),
            _safe_int(payload.get("closed_trade_count")),
        ),
        "total_live_order_count": max(
            _safe_int(payload.get("total_live_order_count")),
            _safe_int(payload.get("live_order_count")),
        ),
        "realized_pnl_usd": _safe_float(
            payload.get("runner_total_realized_pnl_usd", payload.get("realized_pnl_usd"))
        ),
        "drawdown_ratio": _safe_float(
            payload.get("runner_drawdown_to_pnl_ratio", payload.get("drawdown_to_pnl_ratio"))
        ),
        "reject_rate": _safe_float(payload.get("runner_reject_rate", payload.get("reject_rate"))),
        "protection_degraded_rate": _safe_float(
            payload.get("runner_protection_degraded_rate", payload.get("protection_degraded_rate"))
        ),
        "avg_edge_retention_ratio": _safe_float(
            payload.get("runner_avg_edge_retention_ratio", payload.get("avg_edge_retention_ratio"))
        ),
        "avg_realized_edge_bps": _safe_float(
            payload.get("runner_avg_realized_edge_bps", payload.get("avg_realized_edge_bps"))
        ),
        "walk_forward_window_count": _safe_int(
            payload.get("runner_walk_forward_window_count", payload.get("walk_forward_window_count"))
        ),
        "positive_walk_forward_ratio": _safe_float(
            payload.get("runner_positive_walk_forward_ratio", payload.get("positive_walk_forward_ratio"))
        ),
        "micro_live_status": str(micro_live_gate.get("status", "not_available") or "not_available"),
        "policy_bucket": selected_bucket,
        "source": source,
    }


def build_regime_aware_auto_mode(
    *,
    regime_summary: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    sample_quality_watchdog: dict[str, Any] | None = None,
    checkpoint_auto_judge: dict[str, Any] | None = None,
    baseline_control_comparison: dict[str, Any] | None = None,
    execution_quality: dict[str, Any] | None = None,
    symbol_lifecycle_summary: dict[str, Any] | None = None,
    symbol_lifecycle: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> dict[str, object]:
    watchdog = dict(sample_quality_watchdog or {})
    checkpoint = dict(checkpoint_auto_judge or {})
    baseline = dict(baseline_control_comparison or {})
    lifecycle = _coerce_symbol_lifecycle_summary(symbol_lifecycle_summary, rows=symbol_lifecycle)
    regime = _regime_signal(regime_summary)
    execution = _execution_quality_signal(execution_quality)

    watchdog_status = str(watchdog.get("status", "not_available") or "not_available")
    checkpoint_verdict = str(checkpoint.get("verdict", "not_available") or "not_available")
    baseline_verdict = str(baseline.get("verdict", "not_available") or "not_available")
    baseline_gate = str(baseline.get("expansion_gate", "not_available") or "not_available")

    tighten_score = 0
    expand_score = 0.0
    expansion_blocked = False
    strong_execution = False
    reason_codes: list[str] = []

    if watchdog_status == "degraded":
        tighten_score += 4
        expansion_blocked = True
        reason_codes.append("AUTO_MODE_TIGHTENED_BY_SAMPLE_QUALITY_WATCHDOG_DEGRADED")
    elif watchdog_status == "thin":
        tighten_score += 1
        expansion_blocked = True
        reason_codes.append("AUTO_MODE_EXPANSION_BLOCKED_BY_SAMPLE_QUALITY_WATCHDOG_THIN")
    elif watchdog_status == "healthy":
        expand_score += 0.5
        reason_codes.append("AUTO_MODE_SAMPLE_QUALITY_HEALTHY")
    elif watchdog_status == "promote_ready":
        expand_score += 1.0
        reason_codes.append("AUTO_MODE_SAMPLE_QUALITY_PROMOTE_READY")

    if checkpoint_verdict == "rollback":
        tighten_score += 4
        expansion_blocked = True
        reason_codes.append("AUTO_MODE_TIGHTENED_BY_CHECKPOINT_ROLLBACK")
    elif checkpoint_verdict == "tighten":
        tighten_score += 3
        expansion_blocked = True
        reason_codes.append("AUTO_MODE_TIGHTENED_BY_CHECKPOINT_TIGHTEN")
    elif checkpoint_verdict == "expand":
        expand_score += 1.0
        reason_codes.append("AUTO_MODE_CHECKPOINT_SUPPORTS_EXPANSION")

    if baseline_verdict == "caution":
        tighten_score += 2
        expansion_blocked = True
        reason_codes.append("AUTO_MODE_TIGHTENED_BY_SIMPLE_BASELINE_CAUTION")
    elif baseline_verdict == "parity" or baseline_gate == "block":
        expansion_blocked = True
        reason_codes.append("AUTO_MODE_EXPANSION_BLOCKED_BY_SIMPLE_BASELINE_PARITY")
    elif baseline_gate == "pass":
        expand_score += 1.0
        reason_codes.append("AUTO_MODE_SIMPLE_BASELINE_SUPPORTIVE")

    rollback_count = _safe_int(dict(lifecycle.get("action_counts", {}) or {}).get("rollback"))
    hold_count = _safe_int(dict(lifecycle.get("action_counts", {}) or {}).get("hold"))
    review_count = _safe_int(dict(lifecycle.get("action_counts", {}) or {}).get("re_review"))
    cautious_count = _safe_int(dict(lifecycle.get("action_counts", {}) or {}).get("cautious_repromote"))
    actionable_symbol_count = _safe_int(lifecycle.get("actionable_symbol_count"))
    if rollback_count > 0:
        tighten_score += 2
        expansion_blocked = True
        reason_codes.append("AUTO_MODE_TIGHTENED_BY_SYMBOL_LIFECYCLE_ROLLBACK")
    if hold_count > 0 or review_count > 0:
        tighten_score += 1
        expansion_blocked = True
        reason_codes.append("AUTO_MODE_EXPANSION_BLOCKED_BY_SYMBOL_LIFECYCLE")
    if actionable_symbol_count == 0 and cautious_count == 0:
        expand_score += 0.5
        reason_codes.append("AUTO_MODE_SYMBOL_LIFECYCLE_CLEAR")

    if regime.get("futures_negative"):
        tighten_score += 1
        reason_codes.append("AUTO_MODE_TIGHTENED_BY_FUTURES_REGIME_WEAKNESS")
    if str(regime.get("dominant_mode", "") or "") == "cash":
        tighten_score += 2
        expansion_blocked = True
        reason_codes.append("AUTO_MODE_TIGHTENED_BY_CASH_DOMINANT_REGIME")
    if regime.get("futures_supportive"):
        expand_score += 1.0
        reason_codes.append("AUTO_MODE_FUTURES_REGIME_SUPPORTIVE")

    if execution["available"]:
        sample_ready = (
            int(execution["total_closed_trade_count"]) >= 6
            or int(execution["total_live_order_count"]) >= 6
        )
        if sample_ready and (
            float(execution["realized_pnl_usd"]) <= 0.0
            or float(execution["drawdown_ratio"]) > 0.9
            or float(execution["avg_edge_retention_ratio"]) < 0.55
            or float(execution["reject_rate"]) > 0.08
            or float(execution["protection_degraded_rate"]) > 0.08
        ):
            tighten_score += 3
            expansion_blocked = True
            reason_codes.append("AUTO_MODE_TIGHTENED_BY_EXECUTION_QUALITY")
        elif (
            float(execution["realized_pnl_usd"]) > 0.0
            and float(execution["avg_edge_retention_ratio"]) >= 0.8
            and float(execution["reject_rate"]) <= 0.03
            and float(execution["protection_degraded_rate"]) <= 0.03
            and (
                int(execution["walk_forward_window_count"]) < 2
                or float(execution["positive_walk_forward_ratio"]) >= 0.75
            )
        ):
            strong_execution = True
            expand_score += 1.0
            reason_codes.append("AUTO_MODE_EXECUTION_QUALITY_STRONG")

    mode = "normal"
    if tighten_score >= 3:
        mode = "tighter"
    elif (
        not expansion_blocked
        and watchdog_status == "promote_ready"
        and checkpoint_verdict == "expand"
        and baseline_gate == "pass"
        and bool(regime.get("futures_supportive"))
        and strong_execution
        and rollback_count == 0
        and hold_count == 0
        and review_count == 0
        and expand_score >= 4.0
    ):
        mode = "cautiously_expanded"

    if mode == "tighter":
        policy_guidance = {
            "promotion_intensity_cap": 0.85,
            "max_positive_symbols": 1,
            "block_non_major_positive": True,
            "positive_action_cap": "promote",
        }
        runtime_guidance = {
            "mode_thresholds": {
                "futures_score_min_delta": 2.0,
                "spot_score_min_delta": 1.0,
            },
            "risk": {"per_trade_equity_risk_scale": 0.85},
            "cash_reserve": {"when_futures_enabled_delta": 0.03},
        }
    elif mode == "cautiously_expanded":
        policy_guidance = {
            "promotion_intensity_cap": 1.05,
            "max_positive_symbols": 2,
            "block_non_major_positive": False,
            "positive_action_cap": "promote",
        }
        runtime_guidance = {
            "mode_thresholds": {
                "futures_score_min_delta": -1.0,
                "spot_score_min_delta": -1.0,
            },
            "risk": {"per_trade_equity_risk_scale": 1.03},
            "cash_reserve": {"when_futures_enabled_delta": -0.01},
        }
    else:
        policy_guidance = {
            "promotion_intensity_cap": 1.0,
            "max_positive_symbols": 0,
            "block_non_major_positive": False,
            "positive_action_cap": "",
        }
        runtime_guidance = {
            "mode_thresholds": {
                "futures_score_min_delta": 0.0,
                "spot_score_min_delta": 0.0,
            },
            "risk": {"per_trade_equity_risk_scale": 1.0},
            "cash_reserve": {"when_futures_enabled_delta": 0.0},
        }

    return {
        "mode": mode,
        "reason_codes": sorted(set(reason_codes)),
        "expansion_blocked": expansion_blocked,
        "policy_guidance": policy_guidance,
        "runtime_guidance": runtime_guidance,
        "inputs": {
            "sample_quality_watchdog_status": watchdog_status,
            "checkpoint_verdict": checkpoint_verdict,
            "baseline_verdict": baseline_verdict,
            "baseline_gate": baseline_gate,
            "supportive_regime_modes": list(regime.get("supportive_modes", [])),
            "dominant_regime_mode": str(regime.get("dominant_mode", "") or ""),
            "symbol_lifecycle_actionable_count": actionable_symbol_count,
            "execution_quality": execution,
        },
    }


def apply_auto_mode_runtime_overrides(
    *,
    base_config: dict[str, Any],
    auto_mode: dict[str, Any] | None,
) -> dict[str, object]:
    mode = str(dict(auto_mode or {}).get("mode", "normal") or "normal")
    guidance = dict(dict(auto_mode or {}).get("runtime_guidance", {}) or {})
    if mode == "normal":
        return {}
    overrides: dict[str, object] = {}
    mode_thresholds = dict(base_config.get("mode_thresholds", {}) or {})
    threshold_guidance = dict(guidance.get("mode_thresholds", {}) or {})
    futures_score_min = _safe_float(mode_thresholds.get("futures_score_min"))
    spot_score_min = _safe_float(mode_thresholds.get("spot_score_min"))
    futures_delta = _safe_float(threshold_guidance.get("futures_score_min_delta"))
    spot_delta = _safe_float(threshold_guidance.get("spot_score_min_delta"))
    updated_thresholds: dict[str, float] = {}
    if futures_score_min > 0.0 or futures_delta != 0.0:
        updated_thresholds["futures_score_min"] = round(max(1.0, futures_score_min + futures_delta), 6)
    if spot_score_min > 0.0 or spot_delta != 0.0:
        updated_thresholds["spot_score_min"] = round(max(1.0, spot_score_min + spot_delta), 6)
    if updated_thresholds:
        overrides["mode_thresholds"] = updated_thresholds
    risk = dict(base_config.get("risk", {}) or {})
    risk_scale = _safe_float(dict(guidance.get("risk", {}) or {}).get("per_trade_equity_risk_scale"), 1.0)
    per_trade_equity_risk = _safe_float(risk.get("per_trade_equity_risk"))
    if per_trade_equity_risk > 0.0 and abs(risk_scale - 1.0) > 1e-9:
        overrides.setdefault("risk", {})["per_trade_equity_risk"] = round(per_trade_equity_risk * risk_scale, 6)
    cash_reserve = dict(base_config.get("cash_reserve", {}) or {})
    reserve_delta = _safe_float(dict(guidance.get("cash_reserve", {}) or {}).get("when_futures_enabled_delta"))
    when_futures_enabled = _safe_float(cash_reserve.get("when_futures_enabled"))
    if when_futures_enabled > 0.0 and reserve_delta != 0.0:
        overrides.setdefault("cash_reserve", {})["when_futures_enabled"] = round(
            min(max(when_futures_enabled + reserve_delta, 0.0), 1.0),
            6,
        )
    return overrides


def auto_mode_positive_cap(auto_mode: dict[str, Any] | None) -> int:
    return max(
        _safe_int(dict(dict(auto_mode or {}).get("policy_guidance", {}) or {}).get("max_positive_symbols")),
        0,
    )


def auto_mode_blocks_non_major_positive(auto_mode: dict[str, Any] | None) -> bool:
    return bool(
        dict(dict(auto_mode or {}).get("policy_guidance", {}) or {}).get("block_non_major_positive")
    )


def auto_mode_positive_action_cap(auto_mode: dict[str, Any] | None) -> str:
    return str(
        dict(dict(auto_mode or {}).get("policy_guidance", {}) or {}).get("positive_action_cap", "") or ""
    )


def auto_mode_promotion_intensity_cap(auto_mode: dict[str, Any] | None, *, default: float = 1.0) -> float:
    cap = _safe_float(
        dict(dict(auto_mode or {}).get("policy_guidance", {}) or {}).get("promotion_intensity_cap"),
        default,
    )
    return max(0.5, min(cap, 1.05))


def is_positive_policy_action(action: str) -> bool:
    return action in _POSITIVE_ACTIONS
