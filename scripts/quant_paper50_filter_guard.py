#!/usr/bin/env python3
"""Bounded paper50 entry-filter guard.

This guard consumes the read-only paper50 counterfactual artifact and, when
fresh post-config evidence repeatedly shows high-quality missed entries, applies
small symbol-scoped filter adjustments to the paper-only override config.

It never starts live-auto and never touches exchange orders.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_OUTPUT_BASE = Path("quant_runtime_paper50")
DEFAULT_FILTERS = DEFAULT_OUTPUT_BASE / "paper50_multi_symbol_filters.json"
DEFAULT_COUNTERFACTUAL = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_counterfactual_latest.json"
DEFAULT_STATE = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_filter_guard_state.json"
DEFAULT_AUDIT = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_filter_guard_audit.jsonl"


HARD_BOUNDS: dict[str, dict[str, float]] = {
    "BTCUSDT": {
        "min_predictability_score": 76.0,
        "min_liquidity_score": 0.48,
        "min_volume_confirmation": 0.45,
        "min_net_edge_bps": 34.0,
        "min_edge_to_cost": 3.5,
        "min_expected_profit_multiplier": 1.0,
        "max_stop_distance_bps": 300.0,
    },
    "DOGEUSDT": {
        "min_predictability_score": 68.0,
        "min_liquidity_score": 0.49,
        "min_volume_confirmation": 0.56,
        "min_net_edge_bps": 28.0,
        "min_edge_to_cost": 2.4,
        "min_expected_profit_multiplier": 1.25,
        "max_stop_distance_bps": 260.0,
    },
    "PEPEUSDT": {
        "min_predictability_score": 67.0,
        "min_liquidity_score": 0.52,
        "min_volume_confirmation": 0.54,
        "min_net_edge_bps": 27.0,
        "min_edge_to_cost": 2.8,
        "min_expected_profit_multiplier": 1.3,
        "max_stop_distance_bps": 340.0,
    },
    "SOLUSDT": {
        "min_predictability_score": 68.0,
        "min_liquidity_score": 0.48,
        "min_volume_confirmation": 0.48,
        "min_net_edge_bps": 22.0,
        "min_edge_to_cost": 1.8,
        "min_expected_profit_multiplier": 1.0,
        "max_stop_distance_bps": 340.0,
    },
    "ETHUSDT": {
        "min_predictability_score": 66.0,
        "min_liquidity_score": 0.47,
        "min_volume_confirmation": 0.43,
        "min_net_edge_bps": 18.0,
        "min_edge_to_cost": 1.6,
        "min_expected_profit_multiplier": 1.0,
        "max_stop_distance_bps": 360.0,
    },
    # XRP showed low-edge missed candidates in current evidence; keep more
    # conservative auto-bounds unless stronger future evidence arrives.
    "XRPUSDT": {
        "min_predictability_score": 70.0,
        "min_liquidity_score": 0.52,
        "min_volume_confirmation": 0.54,
        "min_net_edge_bps": 26.0,
        "min_edge_to_cost": 2.4,
        "min_expected_profit_multiplier": 1.35,
        "max_stop_distance_bps": 260.0,
    },
}


MAX_STEP_DOWN: dict[str, float] = {
    "min_predictability_score": 1.0,
    "min_liquidity_score": 0.02,
    "min_volume_confirmation": 0.02,
    "min_net_edge_bps": 2.0,
    "min_edge_to_cost": 0.15,
    "min_expected_profit_multiplier": 0.1,
}
MAX_STEP_UP: dict[str, float] = {"max_stop_distance_bps": 20.0}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_audit(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _parse_ts(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except Exception:
        return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _window_key(rows: list[dict[str, Any]]) -> str:
    raw = "|".join(
        f"{row.get('symbol')}:{row.get('timestamp')}:{row.get('net_after_cost_bps')}"
        for row in rows
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _config_digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _quality_missed_entries(
    entries: list[dict[str, Any]],
    *,
    evidence_after: datetime,
) -> list[dict[str, Any]]:
    fresh: list[dict[str, Any]] = []
    for row in entries:
        timestamp = _parse_ts(row.get("timestamp"))
        if timestamp is None or timestamp <= evidence_after:
            continue
        net_after_cost = _safe_float(row.get("net_after_cost_bps"), 0.0)
        net_edge = _safe_float(row.get("net_expected_edge_bps"), 0.0)
        edge_to_cost = _safe_float(row.get("edge_to_cost"), 0.0)
        score = _safe_float(row.get("score"), 0.0)
        mae = _safe_float(row.get("mae_bps"), -999.0)
        if net_after_cost < 10.0 or mae <= -25.0:
            continue
        if score < 60.0:
            continue
        if not (net_edge >= 20.0 or edge_to_cost >= 2.0):
            continue
        fresh.append(row)
    return fresh


def _target_down(current: float, observed: float, *, bound: float, max_step: float, pad: float) -> float:
    target = max(observed - pad, bound)
    return round(max(min(current, target), current - max_step, bound), 6)


def _target_up(current: float, observed: float, *, bound: float, max_step: float, pad: float) -> float:
    target = min(observed + pad, bound)
    return round(min(max(current, target), current + max_step, bound), 6)


def _propose_symbol_changes(
    symbol: str,
    profile: dict[str, Any],
    entries: list[dict[str, Any]],
) -> dict[str, float]:
    bounds = HARD_BOUNDS.get(symbol)
    if not bounds or len(entries) < 2:
        return {}

    changes: dict[str, float] = {}
    scores = [_safe_float(row.get("score"), 0.0) for row in entries]
    liquidities = [_safe_float(row.get("liquidity_score"), 0.0) for row in entries]
    volumes = [_safe_float(row.get("volume_confirmation"), 0.0) for row in entries]
    edges = [_safe_float(row.get("net_expected_edge_bps"), 0.0) for row in entries]
    edge_to_costs = [_safe_float(row.get("edge_to_cost"), 0.0) for row in entries]
    reasons = {str(reason) for row in entries for reason in row.get("rejection_reasons", [])}

    def maybe_lower(field: str, observed: float, pad: float) -> None:
        current = _safe_float(profile.get(field), 0.0)
        new_value = _target_down(
            current,
            observed,
            bound=_safe_float(bounds[field], current),
            max_step=MAX_STEP_DOWN[field],
            pad=pad,
        )
        if new_value < current:
            changes[field] = new_value

    if "SYMBOL_PROFILE_SCORE_TOO_LOW" in reasons:
        maybe_lower("min_predictability_score", min(scores), 0.5)
    if "SYMBOL_PROFILE_LIQUIDITY_TOO_WEAK" in reasons:
        maybe_lower("min_liquidity_score", min(liquidities), 0.005)
    if "SYMBOL_PROFILE_VOLUME_TOO_WEAK" in reasons:
        maybe_lower("min_volume_confirmation", min(volumes), 0.005)
    if "SYMBOL_PROFILE_EDGE_TOO_THIN" in reasons and min(edges) >= bounds["min_net_edge_bps"]:
        maybe_lower("min_net_edge_bps", min(edges), 0.5)
    if "SYMBOL_PROFILE_EDGE_COST_TOO_THIN" in reasons and min(edge_to_costs) >= bounds["min_edge_to_cost"]:
        maybe_lower("min_edge_to_cost", min(edge_to_costs), 0.05)
    if "SYMBOL_PROFILE_EXPECTED_PROFIT_TOO_SMALL" in reasons:
        current = _safe_float(profile.get("min_expected_profit_multiplier"), 0.0)
        new_value = round(max(current - MAX_STEP_DOWN["min_expected_profit_multiplier"], bounds["min_expected_profit_multiplier"]), 6)
        if new_value < current:
            changes["min_expected_profit_multiplier"] = new_value
    if "SYMBOL_PROFILE_STOP_TOO_WIDE" in reasons:
        current = _safe_float(profile.get("max_stop_distance_bps"), 0.0)
        # Counterfactual rows do not preserve the pre-zeroed stop; use bounded
        # incremental widening only when otherwise-quality missed entries repeat.
        new_value = _target_up(
            current,
            current + MAX_STEP_UP["max_stop_distance_bps"],
            bound=bounds["max_stop_distance_bps"],
            max_step=MAX_STEP_UP["max_stop_distance_bps"],
            pad=0.0,
        )
        if new_value > current:
            changes["max_stop_distance_bps"] = new_value
    return changes


def _kickstart_paper50() -> None:
    if not hasattr(os, "getuid"):
        return
    uid = os.getuid()
    try:
        subprocess.run(
            ["launchctl", "kickstart", "-k", f"gui/{uid}/com.tttksj.quant-paper50"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filters", default=str(DEFAULT_FILTERS))
    parser.add_argument("--counterfactual", default=str(DEFAULT_COUNTERFACTUAL))
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    parser.add_argument("--audit", default=str(DEFAULT_AUDIT))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restart-paper50", action="store_true")
    args = parser.parse_args()

    filters_path = Path(args.filters)
    counterfactual_path = Path(args.counterfactual)
    state_path = Path(args.state)
    audit_path = Path(args.audit)

    config = _read_json(filters_path)
    counterfactual = _read_json(counterfactual_path)
    state = _read_json(state_path) if state_path.exists() else {}

    config_digest = _config_digest(config)
    last_applied_at = _parse_ts(state.get("last_applied_at")) or datetime.min.replace(tzinfo=UTC)
    # Git syncs and artifact copies rewrite file mtimes, which can make old
    # runtime evidence look newer than the local config even when the embedded
    # decision timestamps are the true source of time. Gate on guard state
    # instead of filesystem mtime so copied paper artifacts remain usable.
    evidence_after = last_applied_at
    profiles = dict(config.get("symbol_filter_profiles") or {})
    entries_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in list(counterfactual.get("possible_missed_entries") or []):
        symbol = str(row.get("symbol") or "").upper()
        entries_by_symbol.setdefault(symbol, []).append(row)

    changes: dict[str, dict[str, float]] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for symbol, profile in profiles.items():
        quality_entries = _quality_missed_entries(
            entries_by_symbol.get(symbol, []),
            evidence_after=evidence_after,
        )
        quality_entries = sorted(quality_entries, key=lambda row: str(row.get("timestamp") or ""))
        key = _window_key(quality_entries)
        if not quality_entries or state.get("window_keys", {}).get(symbol) == key:
            continue
        proposed = _propose_symbol_changes(symbol, dict(profile), quality_entries)
        if proposed:
            changes[symbol] = proposed
            evidence[symbol] = {
                "quality_missed_count": len(quality_entries),
                "window_key": key,
                "entries": quality_entries[-5:],
            }

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "paper50_filter_guard",
        "apply_requested": bool(args.apply),
        "restart_requested": bool(args.restart_paper50),
        "evidence_after": evidence_after.isoformat(),
        "changes": changes,
        "evidence": evidence,
    }

    if args.apply and changes:
        for symbol, symbol_changes in changes.items():
            profiles.setdefault(symbol, {}).update(symbol_changes)
        config["symbol_filter_profiles"] = profiles
        _write_json(filters_path, config)
        state.setdefault("window_keys", {})
        for symbol, symbol_evidence in evidence.items():
            state["window_keys"][symbol] = symbol_evidence["window_key"]
        state["last_applied_at"] = payload["generated_at"]
        state["previous_config_digest"] = config_digest
        state["config_digest"] = _config_digest(config)
        _write_json(state_path, state)
        _append_audit(audit_path, payload)
        if args.restart_paper50:
            _kickstart_paper50()
        payload["applied"] = True
    else:
        payload["applied"] = False
        _write_json(state_path.with_name("paper50_filter_guard_latest.json"), payload)

    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
