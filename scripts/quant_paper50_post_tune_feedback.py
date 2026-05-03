#!/usr/bin/env python3
"""Evaluate post-filter-tune paper outcomes and rollback candidates.

This script reads local paper50 artifacts only. It does not contact exchanges
and does not place, test, cancel, or modify orders.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_BASE = Path("quant_runtime_paper50")
DEFAULT_FILTERS = DEFAULT_OUTPUT_BASE / "paper50_multi_symbol_filters.json"
DEFAULT_STATE = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_filter_guard_state.json"
DEFAULT_AUDIT = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_filter_guard_audit.jsonl"
DEFAULT_COUNTERFACTUAL = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_counterfactual_latest.json"
DEFAULT_FUTURES_OUTCOMES = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_futures_signal_outcomes_latest.json"
DEFAULT_OUTPUT = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_post_tune_feedback_latest.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _latest_applied_audit(audit_rows: list[dict[str, Any]]) -> dict[str, Any]:
    applied = [
        row
        for row in audit_rows
        if bool(row.get("apply_requested")) and dict(row.get("changes") or {})
    ]
    return applied[-1] if applied else {}


def _evidence_side(evidence: dict[str, Any]) -> str:
    entry_sides = {
        str(row.get("direction") or row.get("side") or "").lower()
        for row in list(dict(evidence).get("entries") or [])
    }
    return "short" if "short" in entry_sides else "long"


def _symbol_states(state: dict[str, Any], audit_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    symbols = {
        str(symbol).upper(): dict(payload)
        for symbol, payload in dict(state.get("symbol_states") or {}).items()
        if isinstance(payload, dict)
    }
    for row in audit_rows:
        if not bool(row.get("apply_requested")):
            continue
        for symbol, changes in dict(row.get("changes") or {}).items():
            symbol = str(symbol).upper()
            evidence = dict(dict(row.get("evidence") or {}).get(symbol) or {})
            previous = dict(dict(row.get("previous_profiles") or {}).get(symbol) or {})
            existing = symbols.setdefault(symbol, {})
            existing.update(
                {
                    "last_applied_at": row.get("generated_at"),
                    "changes": changes,
                    "window_key": evidence.get("window_key") or existing.get("window_key"),
                    "side": _evidence_side(evidence),
                }
            )
            if previous:
                existing["rollback_profile"] = previous
    for symbol, window_key in dict(state.get("window_keys") or {}).items():
        symbol = str(symbol).upper()
        existing = symbols.setdefault(symbol, {})
        existing.setdefault("window_key", window_key)
        existing.setdefault("last_applied_at", state.get("last_applied_at"))
        rollback = dict(state.get("rollback_profiles") or {}).get(symbol)
        if rollback and "rollback_profile" not in existing:
            existing["rollback_profile"] = rollback
        existing.setdefault("side", "long")
    return symbols


def _tuned_symbols(state: dict[str, Any], audit_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    symbols = _symbol_states(state, audit_rows)
    latest = _latest_applied_audit(audit_rows)
    for symbol, evidence in dict(latest.get("evidence") or {}).items():
        entry_sides = {
            str(row.get("direction") or row.get("side") or "").lower()
            for row in list(dict(evidence).get("entries") or [])
        }
        symbols.setdefault(str(symbol).upper(), {})["side"] = "short" if "short" in entry_sides else "long"
    return symbols


def _horizon_value(row: dict[str, Any], horizon: int) -> float | None:
    value = dict(row.get("forward_net_returns_bps") or {}).get(f"net_ret{horizon}_bps")
    if value is None:
        return None
    return _safe_float(value)


def _outcome_summary(rows: list[dict[str, Any]], *, horizon: int) -> dict[str, Any]:
    values = [value for row in rows if (value := _horizon_value(row, horizon)) is not None]
    return {
        "count": len(rows),
        "net_return_count": len(values),
        "avg_net_bps": round(sum(values) / len(values), 6) if values else None,
        "win_rate": round(sum(1 for value in values if value > 0.0) / len(values), 6) if values else None,
        "positive_count": sum(1 for value in values if value > 0.0),
        "negative_count": sum(1 for value in values if value < 0.0),
        "best_net_bps": round(max(values), 6) if values else None,
        "worst_net_bps": round(min(values), 6) if values else None,
    }


def _fresh_outcomes(
    futures_outcomes: dict[str, Any],
    *,
    symbol: str,
    side: str,
    applied_at: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_rows: list[dict[str, Any]] = []
    executable_rows: list[dict[str, Any]] = []
    for row in list(futures_outcomes.get("entries") or []):
        timestamp = _parse_ts(row.get("timestamp"))
        if timestamp is None or timestamp <= applied_at:
            continue
        if str(row.get("symbol") or "").upper() != symbol:
            continue
        if str(row.get("side") or "").lower() != side:
            continue
        all_rows.append(row)
        if bool(row.get("is_executable")):
            executable_rows.append(row)
    return all_rows, executable_rows


def _quality_missed(row: dict[str, Any]) -> bool:
    net_after_cost = _safe_float(row.get("net_after_cost_bps"))
    net_edge = _safe_float(row.get("net_expected_edge_bps"))
    edge_to_cost = _safe_float(row.get("edge_to_cost"))
    score = _safe_float(row.get("score"))
    mae = _safe_float(row.get("mae_bps"), -999.0)
    return net_after_cost >= 10.0 and mae > -25.0 and score >= 60.0 and (net_edge >= 20.0 or edge_to_cost >= 2.0)


def _fresh_counterfactual(
    counterfactual: dict[str, Any],
    *,
    symbol: str,
    side: str,
    applied_at: datetime,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in list(counterfactual.get("possible_missed_entries") or []):
        timestamp = _parse_ts(row.get("timestamp"))
        if timestamp is None or timestamp <= applied_at:
            continue
        if str(row.get("symbol") or "").upper() != symbol:
            continue
        direction = str(row.get("direction") or row.get("side") or "").lower()
        if direction != side:
            continue
        if _quality_missed(row):
            rows.append(row)
    return rows


def _decide(
    *,
    executable_summary: dict[str, Any],
    all_signal_summary: dict[str, Any],
    quality_missed_count: int,
    has_rollback_profile: bool,
) -> tuple[str, str, list[str], str]:
    executable_count = _safe_int(executable_summary.get("net_return_count"))
    all_signal_count = _safe_int(all_signal_summary.get("net_return_count"))
    avg = executable_summary.get("avg_net_bps")
    win = executable_summary.get("win_rate")
    worst = executable_summary.get("worst_net_bps")
    blockers: list[str] = []

    if executable_count >= 3 and avg is not None and worst is not None and (float(avg) < 0.0 or float(worst) <= -25.0):
        if not has_rollback_profile:
            blockers.append("rollback_profile_missing")
        return (
            "rollback_candidate",
            "Post-tune executable paper entries are losing enough to review rollback.",
            blockers,
            "restore_previous_symbol_profile_or_tighten_one_step",
        )
    if executable_count >= 5 and avg is not None and win is not None and worst is not None:
        if float(avg) >= 4.0 and float(win) >= 0.6 and float(worst) > -15.0:
            return (
                "keep_tune",
                "Post-tune executable paper entries support keeping the current filter change.",
                [],
                "keep_current_profile_and_continue_observation",
            )
    if executable_count == 0 and quality_missed_count >= 2:
        return (
            "still_too_tight_watch",
            "Fresh quality misses remain after the tune, but no executable post-tune entries have matured.",
            ["no_executable_post_tune_entries"],
            "diagnose_capacity_or_specific_blockers_before_more_relaxation",
        )
    if executable_count == 0 and all_signal_count >= 3:
        return (
            "capacity_watch",
            "Post-tune futures signals exist but are not executable, so capacity or sizing may be the limiter.",
            ["no_executable_post_tune_entries"],
            "inspect_zero_notional_signals_and_position_capacity",
        )
    return (
        "post_tune_watch",
        "Post-tune evidence is not mature enough for keep or rollback.",
        ["post_tune_sample_lt_3"],
        "collect_more_post_tune_outcomes",
    )


def build_feedback(
    *,
    state: dict[str, Any],
    audit_rows: list[dict[str, Any]],
    futures_outcomes: dict[str, Any],
    counterfactual: dict[str, Any],
    filters: dict[str, Any],
    horizon: int = 15,
) -> dict[str, Any]:
    tuned_symbols = _tuned_symbols(state, audit_rows)
    if not tuned_symbols:
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "mode": "paper50_post_tune_feedback",
            "paper_only": True,
            "overall_action": "hold",
            "reason": "No applied paper filter tune was found.",
            "candidates": [],
        }

    profiles = dict(filters.get("symbol_filter_profiles") or {})
    rollback_profiles = dict(state.get("rollback_profiles") or {})
    candidates: list[dict[str, Any]] = []
    symbol_reports: dict[str, Any] = {}
    applied_times: list[datetime] = []
    for symbol, metadata in sorted(tuned_symbols.items()):
        applied_at = _parse_ts(metadata.get("last_applied_at"))
        if applied_at is None:
            continue
        applied_times.append(applied_at)
        side = str(metadata.get("side") or "long")
        all_rows, executable_rows = _fresh_outcomes(
            futures_outcomes,
            symbol=symbol,
            side=side,
            applied_at=applied_at,
        )
        quality_missed = _fresh_counterfactual(
            counterfactual,
            symbol=symbol,
            side=side,
            applied_at=applied_at,
        )
        executable_summary = _outcome_summary(executable_rows, horizon=horizon)
        all_signal_summary = _outcome_summary(all_rows, horizon=horizon)
        has_rollback_profile = symbol in rollback_profiles
        rollback_profile = metadata.get("rollback_profile") or rollback_profiles.get(symbol)
        if rollback_profile:
            has_rollback_profile = True
        action, reason, blockers, next_step = _decide(
            executable_summary=executable_summary,
            all_signal_summary=all_signal_summary,
            quality_missed_count=len(quality_missed),
            has_rollback_profile=has_rollback_profile,
        )
        metrics = {
            "applied_at": applied_at.isoformat(),
            "horizon_minutes": horizon,
            "changes": dict(metadata.get("changes") or {}),
            "current_profile": profiles.get(symbol, {}),
            "rollback_profile": rollback_profile,
            "all_post_tune_signals": all_signal_summary,
            "executable_post_tune_entries": executable_summary,
            "quality_missed_after_apply_count": len(quality_missed),
        }
        symbol_reports[symbol] = {
            "side": side,
            "action": action,
            "reason": reason,
            "metrics": metrics,
            "recent_quality_missed": quality_missed[-5:],
            "recent_executable_entries": executable_rows[-5:],
        }
        candidates.append(
            {
                "id": f"post_tune_feedback:{symbol}",
                "scope": "symbol_filter",
                "symbol": symbol,
                "side": side,
                "source": "paper50_post_tune_feedback",
                "action": action,
                "reason": reason,
                "metrics": metrics,
                "blockers": blockers,
                "next_step": next_step,
            }
        )

    actions = {str(row.get("action")) for row in candidates}
    if "rollback_candidate" in actions:
        overall_action = "review_rollback_candidate"
    elif "keep_tune" in actions:
        overall_action = "keep_current_tune"
    elif {"still_too_tight_watch", "capacity_watch", "post_tune_watch"}.intersection(actions):
        overall_action = "continue_observation"
    else:
        overall_action = "hold"
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "paper50_post_tune_feedback",
        "paper_only": True,
        "no_order_side_effects": True,
        "applied_at": max(applied_times).isoformat() if applied_times else None,
        "horizon_minutes": horizon,
        "overall_action": overall_action,
        "symbol_reports": symbol_reports,
        "candidates": candidates,
    }


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Paper50 Post-Tune Feedback",
        "",
        f"Generated: {payload['generated_at']}",
        f"Overall action: `{payload['overall_action']}`",
        "",
        "Paper-only. This report does not place, test, cancel, or modify exchange orders.",
        "",
    ]
    for row in payload.get("candidates") or []:
        metrics = dict(row.get("metrics") or {})
        executable = dict(metrics.get("executable_post_tune_entries") or {})
        lines.append(
            f"- `{row['action']}` `{row['id']}`: n={executable.get('net_return_count')}, "
            f"avg={executable.get('avg_net_bps')}, worst={executable.get('worst_net_bps')}, "
            f"missed={metrics.get('quality_missed_after_apply_count')}; {row['reason']}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filters", default=str(DEFAULT_FILTERS))
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    parser.add_argument("--audit", default=str(DEFAULT_AUDIT))
    parser.add_argument("--counterfactual", default=str(DEFAULT_COUNTERFACTUAL))
    parser.add_argument("--futures-outcomes", default=str(DEFAULT_FUTURES_OUTCOMES))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output")
    parser.add_argument("--horizon", type=int, default=15)
    args = parser.parse_args()

    payload = build_feedback(
        state=_read_json(Path(args.state)),
        audit_rows=_load_jsonl(Path(args.audit)),
        futures_outcomes=_read_json(Path(args.futures_outcomes)),
        counterfactual=_read_json(Path(args.counterfactual)),
        filters=_read_json(Path(args.filters)),
        horizon=max(args.horizon, 1),
    )
    output = Path(args.output)
    _write_json(output, payload)
    markdown_output = Path(args.markdown_output) if args.markdown_output else output.with_suffix(".md")
    markdown_output.write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
