from __future__ import annotations

from typing import Any

from quant_binance.policy_evidence import policy_evidence_bucket


_BLOCKING_LIFECYCLE_ACTIONS = {"rollback", "hold", "re_review"}
_NEGATIVE_BUCKET_RECOMMENDATIONS = {"observe_only", "prune", "demote"}
_POSITIVE_ACTIONS = {"promote", "aggressive_promote"}


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _runtime_policy_source(policy_state: dict[str, Any] | None) -> tuple[str, list[dict[str, object]]]:
    payload = dict(policy_state or {})
    active_policy = dict(payload.get("active_policy", {}) or {})
    adjustments = [dict(item) for item in list(active_policy.get("adjustments", []) or []) if isinstance(item, dict)]
    source = "active_policy"
    if (
        not adjustments
        and str(payload.get("status", "") or "") == "staged_rollout"
        and str(payload.get("rollout_status", "baseline") or "baseline") == "micro_live_pending"
    ):
        adjustments = [
            dict(item)
            for item in list(dict(payload.get("candidate_policy", {}) or {}).get("adjustments", []) or [])
            if isinstance(item, dict)
        ]
        source = "candidate_policy"
    return source, adjustments


def _preferred_bucket_context(
    policy_state: dict[str, Any] | None,
) -> tuple[str, dict[str, dict[str, object]], dict[str, dict[str, object]], dict[str, object]]:
    payload = dict(policy_state or {})
    source, _ = _runtime_policy_source(payload)
    bucket_order = (
        ("staged_candidate", "active_policy", "previous_policy")
        if source == "candidate_policy"
        else ("active_policy", "staged_candidate", "previous_policy")
    )
    for bucket_name in bucket_order:
        bucket = policy_evidence_bucket(payload, bucket_name)
        evidence = dict(bucket.get("evidence", {}) or {})
        if not evidence:
            continue
        if bucket.get("available") is False:
            continue
        alignment = dict(bucket.get("alignment", {}) or {})
        if alignment and not bool(alignment.get("aligned")):
            continue
        symbol_rows = [
            dict(row)
            for row in list(
                evidence.get(
                    "policy_context_bucket_symbol_summary",
                    evidence.get("symbol_summary", []),
                )
                or []
            )
            if isinstance(row, dict) and str(row.get("symbol", "") or "")
        ]
        pruning_rows = [
            dict(row)
            for row in list(
                evidence.get(
                    "policy_context_bucket_pruning_recommendations",
                    evidence.get("pruning_recommendations", []),
                )
                or []
            )
            if isinstance(row, dict) and str(row.get("symbol", "") or "")
        ]
        if not symbol_rows and not pruning_rows:
            continue
        return (
            bucket_name,
            {
                str(row.get("symbol", "") or ""): row
                for row in symbol_rows
            },
            {
                str(row.get("symbol", "") or ""): row
                for row in pruning_rows
            },
            {
                "source": str(bucket.get("source", "") or ""),
                "available": bool(bucket.get("available", True)),
                "alignment": alignment,
            },
        )
    return "", {}, {}, {}


def _effective_policy_guardrails(policy_state: dict[str, Any] | None) -> dict[str, object]:
    payload = dict(policy_state or {})
    auto_mode = dict(payload.get("auto_mode", {}) or {})
    auto_guidance = dict(auto_mode.get("policy_guidance", {}) or {})
    validation = dict(dict(payload.get("policy_validation", {}) or {}).get("evidence", {}) or {})
    checkpoint = dict(validation.get("checkpoint_auto_judge", payload.get("checkpoint_auto_judge", {})) or {})
    watchdog = dict(validation.get("sample_quality_watchdog", {}) or {})
    checkpoint_guardrails = dict(checkpoint.get("policy_guardrails", {}) or {})
    watchdog_guardrails = dict(watchdog.get("policy_guardrails", {}) or {})
    prefer_majors_only = bool(
        checkpoint_guardrails.get("prefer_majors_only")
        or watchdog_guardrails.get("prefer_majors_only")
        or auto_guidance.get("block_non_major_positive")
    )
    non_major_positive_bias = str(
        checkpoint_guardrails.get("non_major_positive_bias")
        or watchdog_guardrails.get("non_major_positive_bias")
        or ("observe_only" if auto_guidance.get("block_non_major_positive") else "")
        or ""
    )
    cap_candidates = [
        _safe_int(auto_guidance.get("max_positive_symbols")),
        _safe_int(checkpoint_guardrails.get("max_positive_symbols")),
        _safe_int(watchdog_guardrails.get("max_positive_symbols")),
    ]
    positive_caps = [value for value in cap_candidates if value > 0]
    return {
        "prefer_majors_only": prefer_majors_only,
        "non_major_positive_bias": non_major_positive_bias,
        "block_non_major_positive": bool(auto_guidance.get("block_non_major_positive")),
        "max_positive_symbols": min(positive_caps) if positive_caps else 0,
        "auto_mode": str(auto_mode.get("mode", "normal") or "normal"),
    }


def build_runtime_universe_hydration(
    *,
    policy_state: dict[str, Any] | None,
    configured_symbols: list[str] | tuple[str, ...] | set[str] = (),
    major_symbols: list[str] | tuple[str, ...] | set[str] = (),
) -> dict[str, object]:
    payload = dict(policy_state or {})
    configured_symbol_set = {
        str(symbol)
        for symbol in list(configured_symbols or [])
        if str(symbol)
    }
    major_symbol_set = {str(symbol) for symbol in list(major_symbols or []) if str(symbol)}
    source, active_adjustments = _runtime_policy_source(payload)
    active_by_symbol = {
        str(item.get("symbol", "") or ""): item
        for item in active_adjustments
        if str(item.get("symbol", "") or "")
    }
    lifecycle_by_symbol = {
        str(row.get("symbol", "") or ""): dict(row)
        for row in list(payload.get("symbol_lifecycle", []) or [])
        if isinstance(row, dict) and str(row.get("symbol", "") or "")
    }
    bucket_name, bucket_summary_by_symbol, bucket_pruning_by_symbol, bucket_context = _preferred_bucket_context(payload)
    guardrails = _effective_policy_guardrails(payload)
    symbols = sorted(configured_symbol_set)
    rows: list[dict[str, object]] = []
    rows_by_symbol: dict[str, dict[str, object]] = {}
    for symbol in symbols:
        is_major = symbol in major_symbol_set
        lifecycle_row = dict(lifecycle_by_symbol.get(symbol, {}) or {})
        active_row = dict(active_by_symbol.get(symbol, {}) or {})
        bucket_summary_row = dict(bucket_summary_by_symbol.get(symbol, {}) or {})
        bucket_pruning_row = dict(bucket_pruning_by_symbol.get(symbol, {}) or {})
        lifecycle_action = str(lifecycle_row.get("recommended_action", "keep") or "keep")
        active_action = str(active_row.get("action", "") or "")
        bucket_summary_recommendation = str(bucket_summary_row.get("recommendation", "") or "")
        bucket_pruning_recommendation = str(bucket_pruning_row.get("recommendation", "") or "")
        positive_bucket_signal = bucket_summary_recommendation == "promote"
        observe_only = False
        allow_bootstrap = True
        exclude_from_top_k = False
        deprioritized = False
        reason_codes: list[str] = []

        if lifecycle_action in _BLOCKING_LIFECYCLE_ACTIONS:
            observe_only = True
            allow_bootstrap = False
            exclude_from_top_k = True
            deprioritized = True
            reason_codes.append(f"SYMBOL_LIFECYCLE_{lifecycle_action.upper()}")

        if bucket_pruning_recommendation in _NEGATIVE_BUCKET_RECOMMENDATIONS:
            allow_bootstrap = False
            exclude_from_top_k = True
            deprioritized = True
            if bucket_pruning_recommendation == "observe_only":
                observe_only = True
            reason_codes.append(f"POLICY_BUCKET_{bucket_pruning_recommendation.upper()}")

        if bucket_summary_recommendation in _NEGATIVE_BUCKET_RECOMMENDATIONS:
            allow_bootstrap = False
            exclude_from_top_k = True
            deprioritized = True
            if bucket_summary_recommendation == "observe_only":
                observe_only = True
            reason_codes.append(f"POLICY_BUCKET_{bucket_summary_recommendation.upper()}")

        if (
            not is_major
            and bool(guardrails.get("prefer_majors_only"))
            and (positive_bucket_signal or active_action in _POSITIVE_ACTIONS)
        ):
            allow_bootstrap = False
            exclude_from_top_k = True
            deprioritized = True
            if str(guardrails.get("non_major_positive_bias", "") or "") == "observe_only":
                observe_only = True
            reason_codes.append("POLICY_BUCKET_NON_MAJOR_POSITIVE_DEPRIORITIZED")

        sort_key = (
            1 if not allow_bootstrap else 0,
            1 if not is_major else 0,
            0 if positive_bucket_signal and is_major else 1,
            1 if deprioritized else 0,
            symbol,
        )
        row = {
            "symbol": symbol,
            "is_major": is_major,
            "policy_source": source,
            "bucket_name": bucket_name,
            "bucket_context": dict(bucket_context),
            "bucket_summary_recommendation": bucket_summary_recommendation,
            "bucket_pruning_recommendation": bucket_pruning_recommendation,
            "bucket_evidence_available": bool(bucket_summary_row or bucket_pruning_row),
            "lifecycle_action": lifecycle_action,
            "active_policy_action": active_action,
            "observe_only": observe_only,
            "allow_bootstrap": allow_bootstrap,
            "exclude_from_top_k": exclude_from_top_k,
            "deprioritized": deprioritized,
            "reason_codes": sorted(set(reason_codes)),
            "sort_key": sort_key,
        }
        rows.append(row)
        rows_by_symbol[symbol] = row
    rows.sort(key=lambda item: tuple(item.get("sort_key", (1, 1, 1, 1, str(item.get("symbol", ""))))))
    return {
        "policy_source": source,
        "bucket_name": bucket_name,
        "bucket_context": dict(bucket_context),
        "guardrails": guardrails,
        "rows": rows,
        "rows_by_symbol": rows_by_symbol,
    }
