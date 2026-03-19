from __future__ import annotations

from copy import deepcopy
from typing import Any


POLICY_EVIDENCE_BUCKET_NAMES = (
    "active_policy",
    "previous_policy",
    "staged_candidate",
    "baseline_control",
)


def _copy_payload(value: Any) -> Any:
    return deepcopy(value)


def _policy_evidence_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw_payload = dict(payload or {})
    if "policy_evidence_buckets" in raw_payload:
        return raw_payload
    policy_context = dict(raw_payload.get("policy_context", {}) or {})
    if "policy_evidence_buckets" in policy_context:
        return policy_context
    policy_validation = dict(raw_payload.get("policy_validation", {}) or {})
    validation_evidence = dict(policy_validation.get("evidence", {}) or {})
    if validation_evidence:
        return validation_evidence
    return raw_payload


def normalize_policy_evidence_buckets(payload: dict[str, Any] | None) -> dict[str, dict[str, object]]:
    raw_payload = _policy_evidence_payload(payload)
    raw_buckets = dict(raw_payload.get("policy_evidence_buckets", {}) or {})
    buckets: dict[str, dict[str, object]] = {}
    for bucket_name in POLICY_EVIDENCE_BUCKET_NAMES:
        bucket = dict(raw_buckets.get(bucket_name, {}) or {})
        buckets[bucket_name] = {
            **bucket,
            "evidence": dict(bucket.get("evidence", {}) or {}),
            "comparison": dict(bucket.get("comparison", {}) or {}),
            "policy_lineage": dict(bucket.get("policy_lineage", {}) or {}),
            "evidence_lineage": dict(bucket.get("evidence_lineage", {}) or {}),
            "alignment": dict(bucket.get("alignment", {}) or {}),
            "policy_application": dict(bucket.get("policy_application", {}) or {}),
            "replay_summary": dict(bucket.get("replay_summary", {}) or {}),
        }
    return buckets


def policy_evidence_bucket(payload: dict[str, Any] | None, bucket_name: str) -> dict[str, object]:
    return dict(normalize_policy_evidence_buckets(payload).get(bucket_name, {}) or {})


def policy_evidence_bucket_evidence(
    payload: dict[str, Any] | None,
    bucket_name: str,
    *,
    fallback_to_root: bool = False,
) -> dict[str, object]:
    bucket = policy_evidence_bucket(payload, bucket_name)
    evidence = dict(bucket.get("evidence", {}) or {})
    if evidence or not fallback_to_root:
        return evidence
    fallback = _policy_evidence_payload(payload)
    fallback = dict(fallback or {})
    fallback.pop("policy_evidence_buckets", None)
    fallback.pop("policy_context", None)
    return fallback


def baseline_control_bucket_comparison(payload: dict[str, Any] | None) -> dict[str, object]:
    bucket = policy_evidence_bucket(payload, "baseline_control")
    comparison = dict(bucket.get("comparison", {}) or {})
    if comparison:
        return comparison
    return dict(_policy_evidence_payload(payload).get("baseline_control_comparison", {}) or {})


def with_policy_evidence_buckets(
    payload: dict[str, Any] | None,
    buckets: dict[str, dict[str, object]] | None,
) -> dict[str, object]:
    updated = dict(payload or {})
    updated["policy_evidence_buckets"] = {
        str(bucket_name): _copy_payload(bucket_payload)
        for bucket_name, bucket_payload in dict(buckets or {}).items()
    }
    return updated
