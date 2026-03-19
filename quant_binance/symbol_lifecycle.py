from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


_POSITIVE_ACTIONS = {"promote", "aggressive_promote"}
_NEGATIVE_ACTIONS = {"demote", "disabled"}
_NEGATIVE_RECOMMENDATIONS = {"prune", "demote"}


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return default


def _parse_iso8601(value: object) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _policy_context_fresh(
    *,
    previous_timestamp: object,
    current_timestamp: object,
    max_age_days: int = 10,
) -> bool:
    previous = _parse_iso8601(previous_timestamp)
    current = _parse_iso8601(current_timestamp)
    if previous is None or current is None:
        return True
    return abs(current - previous) <= timedelta(days=max_age_days)


def summarize_symbol_lifecycle(rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> dict[str, object]:
    payload = [dict(row) for row in list(rows or []) if isinstance(row, dict)]
    action_counts: dict[str, int] = {}
    state_counts: dict[str, int] = {}
    actionable_symbols: list[str] = []
    for row in payload:
        action = str(row.get("recommended_action", "keep") or "keep")
        target_state = str(row.get("target_state", "baseline") or "baseline")
        symbol = str(row.get("symbol", "") or "")
        action_counts[action] = action_counts.get(action, 0) + 1
        state_counts[target_state] = state_counts.get(target_state, 0) + 1
        if symbol and action != "keep":
            actionable_symbols.append(symbol)
    return {
        "symbol_count": len(payload),
        "action_counts": action_counts,
        "state_counts": state_counts,
        "actionable_symbol_count": len(actionable_symbols),
        "actionable_symbols": sorted(actionable_symbols),
    }


def build_symbol_lifecycle(
    *,
    symbol_summary: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    symbol_scorecard: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    pruning_recommendations: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    active_adjustments: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    previous_rows: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    checkpoint_auto_judge: dict[str, Any] | None = None,
    sample_quality_watchdog: dict[str, Any] | None = None,
    baseline_control_comparison: dict[str, Any] | None = None,
    evaluated_at: object = "",
) -> list[dict[str, object]]:
    summary_by_symbol = {
        str(item.get("symbol", "") or ""): dict(item)
        for item in list(symbol_summary or [])
        if str(item.get("symbol", "") or "")
    }
    scorecard_by_symbol = {
        str(item.get("symbol", "") or ""): dict(item)
        for item in list(symbol_scorecard or [])
        if str(item.get("symbol", "") or "")
    }
    pruning_by_symbol = {
        str(item.get("symbol", "") or ""): dict(item)
        for item in list(pruning_recommendations or [])
        if str(item.get("symbol", "") or "")
    }
    active_by_symbol = {
        str(item.get("symbol", "") or ""): dict(item)
        for item in list(active_adjustments or [])
        if str(item.get("symbol", "") or "")
    }
    previous_by_symbol = {
        str(item.get("symbol", "") or ""): dict(item)
        for item in list(previous_rows or [])
        if str(item.get("symbol", "") or "")
    }
    checkpoint_symbol_actions = {
        str(item.get("symbol", "") or ""): dict(item)
        for item in list(dict(checkpoint_auto_judge or {}).get("symbol_actions", []) or [])
        if str(item.get("symbol", "") or "")
    }
    sample_watchdog_status = str(dict(sample_quality_watchdog or {}).get("status", "not_available") or "not_available")
    baseline_verdict = str(dict(baseline_control_comparison or {}).get("verdict", "not_available") or "not_available")
    baseline_gate = str(dict(baseline_control_comparison or {}).get("expansion_gate", "not_available") or "not_available")
    checkpoint_verdict = str(dict(checkpoint_auto_judge or {}).get("verdict", "") or "")
    symbols = sorted(
        set(summary_by_symbol)
        | set(scorecard_by_symbol)
        | set(pruning_by_symbol)
        | set(active_by_symbol)
        | set(previous_by_symbol)
        | set(checkpoint_symbol_actions)
    )
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        summary_row = dict(summary_by_symbol.get(symbol, {}) or {})
        scorecard_row = dict(scorecard_by_symbol.get(symbol, {}) or {})
        pruning_row = dict(pruning_by_symbol.get(symbol, {}) or {})
        active_row = dict(active_by_symbol.get(symbol, {}) or {})
        previous_row = dict(previous_by_symbol.get(symbol, {}) or {})
        checkpoint_row = dict(checkpoint_symbol_actions.get(symbol, {}) or {})

        previous_state = str(previous_row.get("target_state", previous_row.get("current_state", "baseline")) or "baseline")
        policy_context_fresh = _policy_context_fresh(
            previous_timestamp=previous_row.get("evidence_generated_at", previous_row.get("updated_at", "")),
            current_timestamp=evaluated_at,
        )
        active_action = str(active_row.get("action", previous_row.get("active_policy_action", "")) or "")
        active_positive = active_action in _POSITIVE_ACTIONS
        active_negative = active_action in _NEGATIVE_ACTIONS
        derived_current_state = previous_state if previous_row and policy_context_fresh else "baseline"
        if active_positive:
            derived_current_state = "promoted"
        elif active_negative:
            derived_current_state = "demoted"
        elif str(pruning_row.get("recommendation", "") or "") == "observe_only":
            derived_current_state = "observe_only"
        current_state = derived_current_state or "baseline"

        recommendation = str(summary_row.get("recommendation", "") or "")
        pruning_recommendation = str(pruning_row.get("recommendation", "") or "")
        if pruning_recommendation in _NEGATIVE_RECOMMENDATIONS | {"observe_only"}:
            recommendation = pruning_recommendation
        if not recommendation:
            recommendation = "keep"
        scorecard_recommendation = str(scorecard_row.get("recommendation", "keep") or "keep")
        trade_count = _safe_int(summary_row.get("trade_count"))
        required_trade_count = _safe_int(summary_row.get("required_trade_count_for_validation"), 3)
        rolling_evidence = dict(summary_row.get("rolling_evidence", {}) or {})
        positive_window_ratio = _safe_float(rolling_evidence.get("positive_window_ratio"))
        recent_run_consistency = _safe_float(rolling_evidence.get("recent_run_consistency"))
        observed_run_count = _safe_int(rolling_evidence.get("observed_run_count"))
        rolling_supportive = observed_run_count < 2 or (
            positive_window_ratio >= 0.6 and recent_run_consistency >= 0.67
        )
        validation_ready = trade_count >= required_trade_count
        baseline_blocks_expansion = baseline_gate == "block" and baseline_verdict in {"parity", "caution"}
        positive_support = (
            recommendation == "promote"
            and validation_ready
            and scorecard_recommendation == "promote"
            and rolling_supportive
            and sample_watchdog_status in {"healthy", "promote_ready"}
            and checkpoint_verdict not in {"rollback", "tighten"}
            and not baseline_blocks_expansion
        )
        positive_candidate = recommendation == "promote" and validation_ready

        recommended_action = "keep"
        target_state = current_state
        reason_codes: list[str] = []

        checkpoint_action = str(checkpoint_row.get("lifecycle_action", "") or "")
        if checkpoint_action == "rollback":
            recommended_action = "rollback"
            target_state = "demoted" if recommendation in _NEGATIVE_RECOMMENDATIONS else "observe_only"
            reason_codes.extend(str(code) for code in list(checkpoint_row.get("reason_codes", []) or []))
        elif checkpoint_action == "hold":
            recommended_action = "hold"
            target_state = "observe_only" if recommendation == "observe_only" else ("demoted" if recommendation in _NEGATIVE_RECOMMENDATIONS else current_state)
            reason_codes.extend(str(code) for code in list(checkpoint_row.get("reason_codes", []) or []))
        elif checkpoint_action == "re_review":
            recommended_action = "re_review"
            target_state = "re_review"
            reason_codes.extend(str(code) for code in list(checkpoint_row.get("reason_codes", []) or []))
        elif checkpoint_action == "expand":
            recommended_action = "cautious_repromote"
            target_state = "cautious_repromotion"
            reason_codes.extend(str(code) for code in list(checkpoint_row.get("reason_codes", []) or []))
        elif recommendation in _NEGATIVE_RECOMMENDATIONS or scorecard_recommendation == "demote":
            recommended_action = "rollback" if current_state == "promoted" else "hold"
            target_state = "demoted"
            reason_codes.append("SYMBOL_SUPPORT_NEGATIVE")
        elif recommendation == "observe_only":
            recommended_action = "rollback" if current_state == "promoted" else "hold"
            target_state = "observe_only"
            reason_codes.append("SYMBOL_OBSERVE_ONLY")
        elif checkpoint_verdict == "rollback" and current_state == "promoted":
            recommended_action = "rollback"
            target_state = "demoted"
            reason_codes.append("CHECKPOINT_REQUIRES_PROMOTION_ROLLBACK")
        elif positive_support:
            if current_state in {"demoted", "observe_only", "re_review"} or previous_state in {"demoted", "observe_only", "re_review"}:
                recommended_action = "cautious_repromote"
                target_state = "cautious_repromotion"
                reason_codes.append("POSITIVE_EVIDENCE_SUPPORTS_CAUTIOUS_REPROMOTION")
            elif current_state == "promoted":
                recommended_action = "keep"
                target_state = "promoted"
                reason_codes.append("PROMOTION_SUPPORT_RETAINED")
            else:
                recommended_action = "keep"
                target_state = "baseline"
                reason_codes.append("POSITIVE_EVIDENCE_SUPPORTIVE")
        elif positive_candidate:
            recommended_action = "re_review"
            target_state = "re_review"
            reason_codes.append("POSITIVE_EVIDENCE_REQUIRES_RE_REVIEW")
        elif current_state == "promoted":
            if sample_watchdog_status == "degraded" or checkpoint_verdict == "tighten" or baseline_blocks_expansion:
                recommended_action = "rollback"
                target_state = "demoted"
                reason_codes.append("PROMOTION_SUPPORT_WEAKENED")
            else:
                recommended_action = "re_review"
                target_state = "re_review"
                reason_codes.append("PROMOTION_REQUIRES_CONTINUED_REVIEW")
        elif current_state in {"demoted", "observe_only"}:
            recommended_action = "hold"
            target_state = current_state
            reason_codes.append("LIFECYCLE_STATE_HELD")

        if sample_watchdog_status == "degraded":
            reason_codes.append("SAMPLE_QUALITY_WATCHDOG_DEGRADED")
        elif sample_watchdog_status == "thin":
            reason_codes.append("SAMPLE_QUALITY_WATCHDOG_THIN")
        if baseline_blocks_expansion:
            reason_codes.append(
                str(
                    dict(baseline_control_comparison or {}).get(
                        "expansion_gate_reason",
                        "SIMPLE_BASELINE_CONTROL_NOT_CLEARLY_BEATEN",
                    )
                    or "SIMPLE_BASELINE_CONTROL_NOT_CLEARLY_BEATEN"
                )
            )
        if checkpoint_verdict:
            reason_codes.append(f"CHECKPOINT_VERDICT_{checkpoint_verdict.upper()}")
        if not policy_context_fresh:
            reason_codes.append("STALE_POLICY_CONTEXT_IGNORED")

        transition = (
            f"{current_state}_to_{target_state}"
            if current_state != target_state
            else f"{current_state}_steady"
        )
        rows.append(
            {
                "symbol": symbol,
                "current_state": current_state,
                "previous_state": previous_state,
                "target_state": target_state,
                "transition": transition,
                "recommended_action": recommended_action,
                "active_policy_action": active_action or "none",
                "policy_context_fresh": policy_context_fresh,
                "recommendation": recommendation,
                "pruning_recommendation": pruning_recommendation or recommendation,
                "scorecard_recommendation": scorecard_recommendation,
                "trade_count": trade_count,
                "required_trade_count_for_validation": required_trade_count,
                "validation_ready": validation_ready,
                "sample_watchdog_status": sample_watchdog_status,
                "baseline_verdict": baseline_verdict,
                "baseline_gate": baseline_gate,
                "checkpoint_verdict": checkpoint_verdict or "not_available",
                "rolling_positive_window_ratio": round(positive_window_ratio, 6),
                "rolling_recent_run_consistency": round(recent_run_consistency, 6),
                "evidence_generated_at": str(evaluated_at or ""),
                "reason_codes": sorted({code for code in reason_codes if str(code)}),
            }
        )
    rows.sort(
        key=lambda item: (
            {
                "rollback": 0,
                "hold": 1,
                "re_review": 2,
                "cautious_repromote": 3,
                "keep": 4,
            }.get(str(item.get("recommended_action", "keep")), 5),
            str(item.get("symbol", "")),
        )
    )
    return rows
