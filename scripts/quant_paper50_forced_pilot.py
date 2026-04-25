#!/usr/bin/env python3
"""Open and track one forced paper-only pilot from blocked paper50 decisions.

This is an experiment surface for checking whether the existing strategy is too
conservative. It never opens paper runtime positions, never calls private order
endpoints, and never places, tests, cancels, or modifies exchange orders.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_binance.execution.client_factory import build_exchange_rest_client
from scripts.quant_paper50_counterfactual import _evaluate_decision, _parse_timestamp, _safe_float
from scripts.quant_paper50_entry_outcomes import _load_jsonl


DEFAULT_DECISIONS = Path("quant_runtime_paper50/forensics/decisions.jsonl")
DEFAULT_STATE = Path("quant_runtime_paper50/artifacts/paper50_forced_pilot_state.json")
DEFAULT_OUTPUT = Path("quant_runtime_paper50/artifacts/paper50_forced_pilot_latest.json")
HORIZONS = (5, 10, 15, 30)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _decision_side(row: dict[str, Any]) -> str:
    return "long" if _safe_float(row.get("trend_direction")) >= 0.0 else "short"


def _is_forced_candidate(row: dict[str, Any]) -> bool:
    if str(row.get("candidate_mode") or "").lower() != "futures":
        return False
    if str(row.get("final_mode") or "").lower() != "cash" and not bool(row.get("rejected")):
        return False
    if _decision_side(row) not in {"long", "short"}:
        return False
    if _safe_float(row.get("reference_price")) <= 0.0:
        return False
    if _safe_float(row.get("net_expected_edge_bps")) <= 0.0:
        return False
    if _safe_float(row.get("predictability_score")) < 60.0:
        return False
    return True


def _candidate_score(row: dict[str, Any]) -> float:
    score = _safe_float(row.get("predictability_score"))
    edge = _safe_float(row.get("net_expected_edge_bps"))
    cost = _safe_float(row.get("estimated_round_trip_cost_bps"), 1.0)
    volume = _safe_float(row.get("volume_confirmation"))
    liquidity = _safe_float(row.get("liquidity_score"))
    blocker_penalty = len(list(row.get("rejection_reasons") or [])) * 3.0
    edge_to_cost = edge / cost if cost > 0.0 else 0.0
    return score + (edge * 0.7) + (edge_to_cost * 5.0) + (volume * 6.0) + (liquidity * 4.0) - blocker_penalty


def _candidate_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "pilot_id": str(row.get("decision_id") or row.get("decision_hash") or f"{row.get('symbol')}:{row.get('timestamp')}"),
        "decision_id": row.get("decision_id"),
        "decision_hash": row.get("decision_hash"),
        "symbol": str(row.get("symbol") or "").upper(),
        "side": _decision_side(row),
        "timestamp": row.get("timestamp"),
        "reference_price": _safe_float(row.get("reference_price")),
        "score": round(_safe_float(row.get("predictability_score")), 6),
        "net_expected_edge_bps": round(_safe_float(row.get("net_expected_edge_bps")), 6),
        "estimated_round_trip_cost_bps": round(_safe_float(row.get("estimated_round_trip_cost_bps")), 6),
        "edge_to_cost": round(
            _safe_float(row.get("net_expected_edge_bps")) / max(_safe_float(row.get("estimated_round_trip_cost_bps"), 1.0), 1e-9),
            6,
        ),
        "trend_strength": round(_safe_float(row.get("trend_strength")), 6),
        "volume_confirmation": round(_safe_float(row.get("volume_confirmation")), 6),
        "liquidity_score": round(_safe_float(row.get("liquidity_score")), 6),
        "planned_leverage": int(_safe_float(row.get("planned_leverage"), 1.0)),
        "strategy_size_multiplier": round(_safe_float(row.get("strategy_size_multiplier"), 1.0), 6),
        "rejection_reasons": list(row.get("rejection_reasons") or []),
        "divergence_code": row.get("divergence_code") or "",
        "forced_paper_only": True,
        "no_order_side_effects": True,
    }


def _select_candidate(rows: list[dict[str, Any]], state: dict[str, Any], *, lookback: int) -> dict[str, Any] | None:
    active_ids = {str(row.get("pilot_id")) for row in list(state.get("active_pilots") or [])}
    completed_ids = {str(row.get("pilot_id")) for row in list(state.get("completed_pilots") or [])}
    blocked = []
    for row in rows[-max(lookback, 1) :]:
        pilot_id = str(row.get("decision_id") or row.get("decision_hash") or f"{row.get('symbol')}:{row.get('timestamp')}")
        if pilot_id in active_ids or pilot_id in completed_ids:
            continue
        if _is_forced_candidate(row):
            blocked.append(row)
    if not blocked:
        return None
    return max(blocked, key=_candidate_score)


def _evaluate_pilot(client: Any, pilot: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    timestamp = _parse_timestamp(str(pilot.get("timestamp") or ""))
    matured = [minutes for minutes in HORIZONS if now >= timestamp + timedelta(minutes=minutes + 1)]
    result = dict(pilot)
    result["matured_horizons"] = matured
    result["status"] = "active"
    if not matured:
        return result
    row = dict(pilot)
    row["trend_direction"] = 1 if str(pilot.get("side")) == "long" else -1
    row["reference_price"] = pilot.get("reference_price")
    row["estimated_round_trip_cost_bps"] = pilot.get("estimated_round_trip_cost_bps")
    try:
        evaluated = _evaluate_decision(client, row, forward_minutes=max(matured))
    except Exception as exc:
        result["evaluation_error"] = f"{type(exc).__name__}: {exc}"
        return result
    result["evaluation"] = evaluated
    result["status"] = "completed" if max(matured) >= max(HORIZONS) else "active"
    return result


def _summarize(completed: list[dict[str, Any]]) -> dict[str, Any]:
    values = []
    for row in completed:
        ret = dict(dict(row.get("evaluation") or {}).get("forward_returns_bps") or {}).get(f"ret{max(HORIZONS)}_bps")
        if ret is not None:
            values.append(float(ret) - _safe_float(row.get("estimated_round_trip_cost_bps")))
    if not values:
        return {"completed_count": len(completed), "net_return_count": 0, "action": "collect_forced_pilot_outcomes"}
    avg = sum(values) / len(values)
    worst = min(values)
    win_rate = sum(1 for value in values if value > 0.0) / len(values)
    action = "keep_collecting"
    if len(values) >= 3 and avg > 0.0 and win_rate >= 0.66 and worst > -25.0:
        action = "review_small_live_pilot_candidate"
    elif len(values) >= 3 and (avg <= 0.0 or worst <= -25.0):
        action = "forced_pilot_reject_or_tighten"
    return {
        "completed_count": len(completed),
        "net_return_count": len(values),
        "avg_net_bps": round(avg, 6),
        "win_rate": round(win_rate, 6),
        "worst_net_bps": round(worst, 6),
        "action": action,
    }


def build_forced_pilot(
    *,
    rows: list[dict[str, Any]],
    state: dict[str, Any],
    client: Any,
    open_new: bool,
    max_active: int,
    lookback: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = datetime.now(UTC)
    active: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = list(state.get("completed_pilots") or [])
    for pilot in list(state.get("active_pilots") or []):
        evaluated = _evaluate_pilot(client, dict(pilot), now=now)
        if evaluated.get("status") == "completed":
            completed.append(evaluated)
        else:
            active.append(evaluated)

    opened: dict[str, Any] | None = None
    if open_new and len(active) < max(max_active, 1):
        candidate = _select_candidate(rows, {"active_pilots": active, "completed_pilots": completed}, lookback=lookback)
        if candidate is not None:
            opened = _candidate_payload(candidate)
            opened["opened_at"] = now.isoformat()
            opened["selection_score"] = round(_candidate_score(candidate), 6)
            active.append(opened)

    next_state = {
        "updated_at": now.isoformat(),
        "active_pilots": active,
        "completed_pilots": completed[-100:],
    }
    payload = {
        "generated_at": now.isoformat(),
        "mode": "paper50_forced_pilot",
        "paper_only": True,
        "no_order_side_effects": True,
        "open_new_requested": open_new,
        "opened_pilot": opened,
        "active_pilots": active,
        "completed_recent": completed[-10:],
        "summary": _summarize(completed),
    }
    return next_state, payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions-path", default=str(DEFAULT_DECISIONS))
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--open-new", action="store_true")
    parser.add_argument("--max-active", type=int, default=1)
    parser.add_argument("--lookback", type=int, default=120)
    args = parser.parse_args()

    state_path = Path(args.state)
    rows = _load_jsonl([Path(args.decisions_path)])
    state = _read_json(state_path)
    client = build_exchange_rest_client(exchange="bitget", allow_insecure_ssl=True, allow_missing_credentials=True)
    next_state, payload = build_forced_pilot(
        rows=rows,
        state=state,
        client=client,
        open_new=bool(args.open_new),
        max_active=max(args.max_active, 1),
        lookback=max(args.lookback, 1),
    )
    _write_json(state_path, next_state)
    _write_json(Path(args.output), payload)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
