from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from quant_binance.models import DecisionIntent


def hash_decision_payload(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def serialize_decision(decision: DecisionIntent) -> dict[str, Any]:
    data = asdict(decision)
    data["timestamp"] = decision.timestamp.isoformat()
    return data


def render_audit_report(decision: DecisionIntent) -> str:
    data = serialize_decision(decision)
    lines = [
        f"# Decision Audit: {decision.decision_id}",
        "",
        f"- timestamp: {data['timestamp']}",
        f"- symbol: {decision.symbol}",
        f"- candidate_mode: {decision.candidate_mode}",
        f"- final_mode: {decision.final_mode}",
        f"- side: {decision.side}",
        f"- decision_hash: {decision.decision_hash}",
        f"- predictability_score: {decision.predictability_score}",
        f"- gross_expected_edge_bps: {decision.gross_expected_edge_bps}",
        f"- net_expected_edge_bps: {decision.net_expected_edge_bps}",
        f"- estimated_round_trip_cost_bps: {decision.estimated_round_trip_cost_bps}",
        f"- rejection_reasons: {list(decision.rejection_reasons)}",
        f"- linked_order_ids: {list(decision.linked_order_ids)}",
        f"- exit_reason_code: {decision.exit_reason_code}",
        f"- divergence_code: {decision.divergence_code}",
    ]
    return "\n".join(lines)
