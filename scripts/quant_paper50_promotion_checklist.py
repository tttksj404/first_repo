#!/usr/bin/env python3
"""Build a paper-only promotion checklist for paper50 strategy tuning.

The checklist consolidates local monitor artifacts into conservative actions:
promote only to paper-watch candidates, keep weak signals in observation, and
halt review if any live/test order side effects appear.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_BASE = Path("quant_runtime_paper50")
DEFAULT_ALPHA_STATUS = DEFAULT_OUTPUT_BASE / "bitget_external_alpha_shadow" / "status.json"
DEFAULT_OVERLAY_REPORT = (
    DEFAULT_OUTPUT_BASE
    / "bitget_external_alpha_shadow"
    / "long_failure_overlay_check"
    / "long_failure_short_overlay_report.json"
)
DEFAULT_SIDE_SCORECARD = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_side_scorecard_latest.json"
DEFAULT_FILTER_GUARD_STATE = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_filter_guard_state.json"
DEFAULT_FILTER_GUARD_LATEST = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_filter_guard_latest.json"
DEFAULT_FILTER_GUARD_AUDIT = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_filter_guard_audit.jsonl"
DEFAULT_POST_TUNE_FEEDBACK = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_post_tune_feedback_latest.json"
DEFAULT_MARKET_REGIME = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_market_regime_latest.json"
DEFAULT_FORCED_PILOT = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_forced_pilot_latest.json"
DEFAULT_MONITOR_STATUS = DEFAULT_OUTPUT_BASE / "_monitor_status.json"
DEFAULT_OUTPUT = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_promotion_checklist_latest.json"


ACTION_PRIORITY = {
    "halt_review": 100,
    "rollback_candidate": 90,
    "paper_candidate": 80,
    "paper_tune_candidate": 70,
    "keep_tune": 65,
    "still_too_tight_watch": 58,
    "capacity_watch": 56,
    "post_tune_watch": 60,
    "watch_only": 50,
    "hold": 20,
}


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


def _split_key(key: str) -> tuple[str, str, str]:
    parts = key.split("|")
    if len(parts) != 3:
        return key, "unknown", "unknown"
    return parts[0], parts[1], parts[2]


def _safety_gate(monitor_status: dict[str, Any]) -> dict[str, Any]:
    heartbeats = dict(monitor_status.get("heartbeats") or {})
    bitget = dict(monitor_status.get("bitget") or {})
    positions = list(bitget.get("positions") or [])
    live_orders = _safe_int(heartbeats.get("live_orders") or monitor_status.get("live_order_count"))
    tested_orders = _safe_int(heartbeats.get("tested_orders") or monitor_status.get("tested_order_count"))
    safe = live_orders == 0 and tested_orders == 0 and not positions
    blockers = []
    if live_orders:
        blockers.append("live_orders_present")
    if tested_orders:
        blockers.append("tested_orders_present")
    if positions:
        blockers.append("bitget_positions_present")
    return {
        "safe": safe,
        "status_ts": monitor_status.get("ts") or monitor_status.get("updated_at"),
        "decisions": _safe_int(heartbeats.get("decisions") or monitor_status.get("decision_count")),
        "live_orders": live_orders,
        "tested_orders": tested_orders,
        "bitget_positions": positions,
        "blockers": blockers,
    }


def _candidate(
    *,
    id: str,
    source: str,
    action: str,
    reason: str,
    scope: str = "strategy",
    symbol: str | None = None,
    side: str | None = None,
    metrics: dict[str, Any] | None = None,
    blockers: list[str] | None = None,
    next_step: str = "continue_paper_observation",
) -> dict[str, Any]:
    return {
        "id": id,
        "scope": scope,
        "symbol": symbol,
        "side": side,
        "source": source,
        "action": action,
        "reason": reason,
        "metrics": metrics or {},
        "blockers": blockers or [],
        "next_step": next_step,
    }


def _external_alpha_candidates(external_alpha: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    summaries = dict(external_alpha.get("outcome_summary") or {})
    ranked = sorted(
        summaries.items(),
        key=lambda item: (
            _safe_float(item[1].get("avg_ret15_bps"), -999.0),
            _safe_float(item[1].get("win15_rate"), 0.0),
            _safe_int(item[1].get("count")),
        ),
        reverse=True,
    )
    for key, row in ranked[:12]:
        symbol, strategy, side = _split_key(str(key))
        count = _safe_int(row.get("count"))
        avg = _safe_float(row.get("avg_ret15_bps"))
        win = _safe_float(row.get("win15_rate"))
        latest = _safe_float(row.get("latest_ret15_bps"))
        recent = [_safe_float(value) for value in list(row.get("recent5_ret15_bps") or [])]
        recent_worst = min(recent) if recent else None
        metrics = {
            "strategy": strategy,
            "count": count,
            "avg_ret15_bps": row.get("avg_ret15_bps"),
            "win15_rate": row.get("win15_rate"),
            "latest_ret15_bps": row.get("latest_ret15_bps"),
            "recent_worst_ret15_bps": round(recent_worst, 6) if recent_worst is not None else None,
        }
        blockers = []
        if count < 12:
            blockers.append("sample_lt_12")
        if avg < 4.0:
            blockers.append("avg_ret15_lt_4bps")
        if win < 0.65:
            blockers.append("win15_lt_65pct")
        if recent_worst is not None and recent_worst < -12.0:
            blockers.append("recent_tail_loss_lt_-12bps")
        if latest <= 0.0:
            blockers.append("latest_not_positive")

        if not blockers:
            action = "paper_candidate"
            reason = "External alpha has enough sample quality for a paper-only gated trial."
            next_step = "review_symbol_scoped_paper_overlay"
        elif count >= 5 and avg > 0.0 and win >= 0.55:
            action = "watch_only"
            reason = "External alpha is positive but not clean enough for a paper promotion."
            next_step = "collect_more_mature_outcomes"
        else:
            action = "hold"
            reason = "External alpha evidence is too weak or too noisy."
            next_step = "do_not_relax_from_this_signal"
        candidates.append(
            _candidate(
                id=f"external_alpha:{key}",
                source="bitget_external_alpha_shadow",
                action=action,
                reason=reason,
                symbol=symbol,
                side=side,
                metrics=metrics,
                blockers=blockers,
                next_step=next_step,
            )
        )
    return candidates


def _overlay_candidates(overlay_report: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in list(overlay_report.get("leg_stats") or []):
        key = str(row.get("key") or "")
        symbol, strategy, side = _split_key(key)
        count = _safe_int(row.get("matched_count"))
        avg = _safe_float(row.get("avg_ret15_bps"))
        win = _safe_float(row.get("win15_rate"))
        worst = _safe_float(row.get("worst_ret15_bps"), 999.0)
        latest = _safe_float(row.get("latest_ret15_bps"))
        verdict = str(row.get("verdict") or "")
        metrics = {
            "strategy": strategy,
            "verdict": verdict,
            "matched_count": count,
            "avg_ret15_bps": row.get("avg_ret15_bps"),
            "win15_rate": row.get("win15_rate"),
            "worst_ret15_bps": row.get("worst_ret15_bps"),
            "latest_ret15_bps": row.get("latest_ret15_bps"),
        }
        blockers = []
        if verdict != "paper_short_overlay_watch":
            blockers.append(f"verdict_{verdict or 'missing'}")
        if count < 12:
            blockers.append("matched_count_lt_12")
        if avg < 4.0:
            blockers.append("avg_ret15_lt_4bps")
        if win < 0.65:
            blockers.append("win15_lt_65pct")
        if worst <= -10.0:
            blockers.append("worst_ret15_lte_-10bps")
        if latest <= 0.0:
            blockers.append("latest_not_positive")

        if not blockers:
            action = "paper_candidate"
            reason = "Long-failure short overlay passed the paper-only promotion gate."
            next_step = "enable_symbol_scoped_paper_watch_only"
        elif verdict == "shadow_watch":
            action = "watch_only"
            reason = "Overlay is promising enough to watch, but remains report-only."
            next_step = "collect_more_matches_before_paper_enable"
        else:
            action = "hold"
            reason = "Overlay does not have enough matched evidence."
            next_step = "do_not_enable_overlay"
        candidates.append(
            _candidate(
                id=f"long_failure_short_overlay:{key}",
                source="long_failure_short_overlay",
                action=action,
                reason=reason,
                symbol=symbol,
                side=side,
                metrics=metrics,
                blockers=blockers,
                next_step=next_step,
            )
        )
    return candidates


def _side_scorecard_candidates(side_scorecard: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    fallback = dict(side_scorecard.get("fallback_semantics") or {})
    candidates.append(
        _candidate(
            id="runtime_semantics:long_failure_to_short",
            scope="runtime",
            source="paper50_side_scorecard",
            action="hold",
            reason="Runtime does not enter short merely because a long failed.",
            metrics={"long_failure_enters_short": bool(fallback.get("long_failure_enters_short"))},
            next_step="keep_short_logic_directional_not_fallback",
        )
    )
    for side, row in dict(side_scorecard.get("sides") or {}).items():
        recommendation = str(dict(row).get("recommendation") or "")
        accepted = dict(dict(row).get("accepted_outcomes") or {})
        counterfactual = dict(dict(row).get("counterfactual") or {})
        metrics = {
            "recommendation": recommendation,
            "accepted_count": accepted.get("count"),
            "accepted_avg_net_bps": accepted.get("avg_net_bps"),
            "possible_missed_entry_count": counterfactual.get("possible_missed_entry_count"),
            "counterfactual_avg_net_after_cost_bps": counterfactual.get("avg_net_after_cost_bps"),
        }
        if recommendation == f"test_one_step_{side}_relaxation_in_paper_only":
            action = "paper_tune_candidate"
            reason = f"{side} gates may be too tight; only a one-step paper relaxation is allowed."
            next_step = "use_filter_guard_or_replay_before_apply"
        elif recommendation == f"watch_{side}_misses_before_relaxing":
            action = "watch_only"
            reason = f"{side} missed entries exist but evidence is not repeated enough."
            next_step = "collect_more_counterfactual_rows"
        elif recommendation == f"hold_{side}_gates_accepted_signal_lost":
            action = "hold"
            reason = f"Accepted {side} signal has a negative outcome; do not broaden further."
            next_step = "wait_for_post_tune_outcomes_or_tighten_if_repeated"
        else:
            action = "hold"
            reason = f"{side} gates should stay unchanged."
            next_step = "continue_paper_observation"
        candidates.append(
            _candidate(
                id=f"side_scorecard:{side}",
                source="paper50_side_scorecard",
                action=action,
                reason=reason,
                side=side,
                metrics=metrics,
                next_step=next_step,
            )
        )
    return candidates


def _evidence_side(evidence: dict[str, Any]) -> str:
    entry_sides = {
        str(row.get("direction") or row.get("side") or "").lower()
        for row in list(dict(evidence).get("entries") or [])
    }
    return "short" if "short" in entry_sides else "long"


def _filter_guard_symbol_states(
    filter_guard_state: dict[str, Any],
    filter_guard_audit_rows: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    states = {
        str(symbol).upper(): dict(payload)
        for symbol, payload in dict(filter_guard_state.get("symbol_states") or {}).items()
        if isinstance(payload, dict)
    }
    for row in filter_guard_audit_rows or []:
        if not bool(row.get("apply_requested")):
            continue
        generated_at = row.get("generated_at")
        for symbol, changes in dict(row.get("changes") or {}).items():
            symbol = str(symbol).upper()
            evidence = dict(dict(row.get("evidence") or {}).get(symbol) or {})
            previous = dict(dict(row.get("previous_profiles") or {}).get(symbol) or {})
            existing = states.setdefault(symbol, {})
            existing.update(
                {
                    "last_applied_at": generated_at,
                    "changes": changes,
                    "window_key": evidence.get("window_key") or existing.get("window_key"),
                    "side": _evidence_side(evidence),
                }
            )
            if previous:
                existing["rollback_profile"] = previous
    for symbol, window_key in dict(filter_guard_state.get("window_keys") or {}).items():
        symbol = str(symbol).upper()
        existing = states.setdefault(symbol, {})
        existing.setdefault("window_key", window_key)
        existing.setdefault("last_applied_at", filter_guard_state.get("last_applied_at"))
        existing.setdefault("side", "long")
        rollback = dict(filter_guard_state.get("rollback_profiles") or {}).get(symbol)
        if rollback and "rollback_profile" not in existing:
            existing["rollback_profile"] = rollback
    return states


def _filter_guard_candidates(
    filter_guard_state: dict[str, Any],
    filter_guard_latest: dict[str, Any],
    market_regime: dict[str, Any] | None = None,
    filter_guard_audit_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    symbol_states = _filter_guard_symbol_states(filter_guard_state, filter_guard_audit_rows)
    applied_symbols = set(symbol_states)
    for symbol in sorted(applied_symbols):
        symbol_state = dict(symbol_states.get(symbol) or {})
        last_applied_at = symbol_state.get("last_applied_at")
        if last_applied_at:
            latest_changes = dict(filter_guard_latest.get("changes") or {}).get(symbol)
            candidates.append(
                _candidate(
                    id=f"filter_guard:{symbol}",
                    scope="symbol_filter",
                    source="paper50_filter_guard",
                    action="post_tune_watch",
                    reason="A symbol-scoped paper filter change was already applied; avoid another relaxation until fresh outcomes mature.",
                    symbol=symbol,
                    side=str(symbol_state.get("side") or "long"),
                    metrics={
                        "last_applied_at": last_applied_at,
                        "config_digest": symbol_state.get("config_digest") or filter_guard_state.get("config_digest"),
                        "changes": dict(symbol_state.get("changes") or {}),
                        "latest_changes": latest_changes if latest_changes is not None else symbol_state.get("changes"),
                    },
                    next_step="measure_post_apply_entries_before_more_tuning",
                )
            )

    for symbol, changes in dict(filter_guard_latest.get("changes") or {}).items():
        symbol = str(symbol).upper()
        if symbol in applied_symbols:
            continue
        evidence = dict(dict(filter_guard_latest.get("evidence") or {}).get(symbol) or {})
        action = "paper_tune_candidate" if evidence.get("quality_missed_count", 0) >= 2 else "watch_only"
        market_gate = dict(dict(market_regime or {}).get("symbol_gates") or {}).get(symbol, {})
        blockers = []
        if action == "paper_tune_candidate" and market_regime and not bool(market_gate.get("long_relax_allowed")):
            action = "watch_only"
            blockers.append("market_regime_blocks_long_relaxation")
        reason = "Filter guard found repeated quality missed entries."
        if "market_regime_blocks_long_relaxation" in blockers:
            reason = "Filter guard found repeated quality misses, but current market regime does not support long relaxation."
        elif action != "paper_tune_candidate":
            reason = "Filter guard evidence is not repeated enough."
        candidates.append(
            _candidate(
                id=f"filter_guard:{symbol}",
                scope="symbol_filter",
                source="paper50_filter_guard",
                action=action,
                reason=reason,
                symbol=symbol,
                side="long",
                metrics={
                    "changes": changes,
                    "quality_missed_count": evidence.get("quality_missed_count"),
                    "market_posture": dict(market_regime or {}).get("posture"),
                    "market_gate": market_gate,
                },
                blockers=blockers,
                next_step="apply_small_paper_only_change" if action == "paper_tune_candidate" else "collect_more_counterfactual_rows",
            )
        )
    return candidates


def _post_tune_feedback_candidates(post_tune_feedback: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in list(post_tune_feedback.get("candidates") or []):
        action = str(row.get("action") or "post_tune_watch")
        if action not in ACTION_PRIORITY:
            action = "post_tune_watch"
        candidates.append(
            _candidate(
                id=str(row.get("id") or f"post_tune_feedback:{row.get('symbol') or 'unknown'}"),
                scope=str(row.get("scope") or "symbol_filter"),
                source="paper50_post_tune_feedback",
                action=action,
                reason=str(row.get("reason") or "Post-tune feedback is still maturing."),
                symbol=row.get("symbol"),
                side=row.get("side"),
                metrics=dict(row.get("metrics") or {}),
                blockers=list(row.get("blockers") or []),
                next_step=str(row.get("next_step") or "collect_more_post_tune_outcomes"),
            )
        )
    return candidates


def _forced_pilot_candidates(forced_pilot: dict[str, Any]) -> list[dict[str, Any]]:
    if not forced_pilot:
        return []
    summary = dict(forced_pilot.get("summary") or {})
    action_code = str(summary.get("action") or "collect_forced_pilot_outcomes")
    active = list(forced_pilot.get("active_pilots") or [])
    completed = list(forced_pilot.get("completed_recent") or [])
    metrics = {
        "summary_action": action_code,
        "active_count": len(active),
        "completed_recent_count": len(completed),
        "completed_count": summary.get("completed_count"),
        "net_return_count": summary.get("net_return_count"),
        "avg_net_bps": summary.get("avg_net_bps"),
        "win_rate": summary.get("win_rate"),
        "worst_net_bps": summary.get("worst_net_bps"),
    }
    if active:
        head = dict(active[0])
        metrics["active_symbol"] = head.get("symbol")
        metrics["active_side"] = head.get("side")
        metrics["active_matured_horizons"] = head.get("matured_horizons")
        metrics["active_label"] = dict(head.get("evaluation") or {}).get("label")
        metrics["active_net_after_cost_bps"] = dict(head.get("evaluation") or {}).get("net_after_cost_bps")

    if action_code == "review_small_live_pilot_candidate":
        action = "paper_candidate"
        reason = "Forced paper-only pilots show blocked entries may have enough edge to review."
        blockers = ["requires_explicit_live_approval"]
        next_step = "review_small_live_pilot_candidate_before_any_live_change"
    elif action_code == "forced_pilot_reject_or_tighten":
        action = "hold"
        reason = "Forced paper-only pilots lost after costs; existing blocks should stay or tighten."
        blockers = []
        next_step = "keep_current_blocks_and_collect_only_if_market_changes"
    elif active or completed:
        action = "watch_only"
        reason = "Forced paper-only pilot evidence is still maturing."
        blockers = []
        next_step = "collect_forced_pilot_outcomes"
    else:
        action = "hold"
        reason = "No forced paper-only pilot outcomes exist yet."
        blockers = []
        next_step = "wait_for_blocked_candidate"

    return [
        _candidate(
            id="forced_pilot:block_override_quality",
            scope="strategy",
            source="paper50_forced_pilot",
            action=action,
            reason=reason,
            metrics=metrics,
            blockers=blockers,
            next_step=next_step,
        )
    ]


def build_checklist(
    *,
    monitor_status: dict[str, Any],
    external_alpha: dict[str, Any],
    overlay_report: dict[str, Any],
    side_scorecard: dict[str, Any],
    filter_guard_state: dict[str, Any],
    filter_guard_latest: dict[str, Any],
    filter_guard_audit_rows: list[dict[str, Any]] | None = None,
    post_tune_feedback: dict[str, Any] | None = None,
    market_regime: dict[str, Any] | None = None,
    forced_pilot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    safety = _safety_gate(monitor_status)
    candidates: list[dict[str, Any]] = []
    if not safety["safe"]:
        candidates.append(
            _candidate(
                id="safety:paper50_side_effects",
                scope="safety",
                source="paper50_monitor_status",
                action="halt_review",
                reason="Paper-only review is blocked because order side effects or positions are present.",
                metrics=safety,
                blockers=list(safety["blockers"]),
                next_step="stop_promotion_review_and_investigate_runtime",
            )
        )
    else:
        candidates.extend(_post_tune_feedback_candidates(post_tune_feedback or {}))
        candidates.extend(_forced_pilot_candidates(forced_pilot or {}))
        candidates.extend(
            _filter_guard_candidates(
                filter_guard_state,
                filter_guard_latest,
                market_regime,
                filter_guard_audit_rows,
            )
        )
        candidates.extend(_overlay_candidates(overlay_report))
        candidates.extend(_external_alpha_candidates(external_alpha))
        candidates.extend(_side_scorecard_candidates(side_scorecard))

    candidates.sort(
        key=lambda row: (
            ACTION_PRIORITY.get(str(row.get("action")), 0),
            _safe_float(dict(row.get("metrics") or {}).get("avg_ret15_bps"), -999.0),
            _safe_int(dict(row.get("metrics") or {}).get("count") or dict(row.get("metrics") or {}).get("matched_count")),
        ),
        reverse=True,
    )
    actions = {str(row.get("action")) for row in candidates}
    if "halt_review" in actions:
        overall_action = "halt_review"
    elif "rollback_candidate" in actions:
        overall_action = "review_rollback_candidate"
    elif "paper_candidate" in actions or "paper_tune_candidate" in actions:
        overall_action = "review_paper_candidate"
    elif "keep_tune" in actions:
        overall_action = "keep_current_tune"
    elif {"post_tune_watch", "still_too_tight_watch", "capacity_watch", "watch_only"}.intersection(actions):
        overall_action = "continue_observation"
    else:
        overall_action = "hold"

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "paper50_promotion_checklist",
        "paper_only": True,
        "no_order_side_effects": True,
        "safety": safety,
        "market_regime": {
            "posture": dict(market_regime or {}).get("posture"),
            "core_avg_change_pct_24h": dict(market_regime or {}).get("core_avg_change_pct_24h"),
            "alt_avg_change_pct_24h": dict(market_regime or {}).get("alt_avg_change_pct_24h"),
            "alt_relative_to_core_pct": dict(market_regime or {}).get("alt_relative_to_core_pct"),
        },
        "overall_action": overall_action,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Paper50 Promotion Checklist",
        "",
        f"Generated: {payload['generated_at']}",
        f"Overall action: `{payload['overall_action']}`",
        f"Safety: `{'safe' if payload['safety']['safe'] else 'blocked'}`",
        f"Market regime: `{dict(payload.get('market_regime') or {}).get('posture')}`",
        "",
        "Paper-only. This checklist does not place, test, cancel, or modify exchange orders.",
        "",
        "## Top Candidates",
        "",
    ]
    for row in list(payload.get("candidates") or [])[:12]:
        metrics = dict(row.get("metrics") or {})
        metric_bits = []
        for key in (
            "matched_count",
            "count",
            "avg_ret15_bps",
            "win15_rate",
            "worst_ret15_bps",
            "latest_ret15_bps",
            "avg_net_bps",
            "win_rate",
            "worst_net_bps",
            "active_count",
        ):
            if metrics.get(key) is not None:
                metric_bits.append(f"{key}={metrics[key]}")
        executable = dict(metrics.get("executable_post_tune_entries") or {})
        if executable:
            metric_bits.append(f"post_n={executable.get('net_return_count')}")
            metric_bits.append(f"post_avg={executable.get('avg_net_bps')}")
            metric_bits.append(f"post_worst={executable.get('worst_net_bps')}")
        blockers = ", ".join(row.get("blockers") or []) or "none"
        lines.append(
            f"- `{row['action']}` `{row['id']}`: {row['reason']} "
            f"({' '.join(metric_bits) if metric_bits else 'no metrics'}; blockers: {blockers})"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alpha-status", default=str(DEFAULT_ALPHA_STATUS))
    parser.add_argument("--overlay-report", default=str(DEFAULT_OVERLAY_REPORT))
    parser.add_argument("--side-scorecard", default=str(DEFAULT_SIDE_SCORECARD))
    parser.add_argument("--filter-guard-state", default=str(DEFAULT_FILTER_GUARD_STATE))
    parser.add_argument("--filter-guard-latest", default=str(DEFAULT_FILTER_GUARD_LATEST))
    parser.add_argument("--filter-guard-audit", default=str(DEFAULT_FILTER_GUARD_AUDIT))
    parser.add_argument("--post-tune-feedback", default=str(DEFAULT_POST_TUNE_FEEDBACK))
    parser.add_argument("--market-regime", default=str(DEFAULT_MARKET_REGIME))
    parser.add_argument("--forced-pilot", default=str(DEFAULT_FORCED_PILOT))
    parser.add_argument("--monitor-status", default=str(DEFAULT_MONITOR_STATUS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output")
    args = parser.parse_args()

    payload = build_checklist(
        monitor_status=_read_json(Path(args.monitor_status)),
        external_alpha=_read_json(Path(args.alpha_status)),
        overlay_report=_read_json(Path(args.overlay_report)),
        side_scorecard=_read_json(Path(args.side_scorecard)),
        filter_guard_state=_read_json(Path(args.filter_guard_state)),
        filter_guard_latest=_read_json(Path(args.filter_guard_latest)),
        filter_guard_audit_rows=_load_jsonl(Path(args.filter_guard_audit)),
        post_tune_feedback=_read_json(Path(args.post_tune_feedback)),
        market_regime=_read_json(Path(args.market_regime)),
        forced_pilot=_read_json(Path(args.forced_pilot)),
    )
    output = Path(args.output)
    _write_json(output, payload)
    markdown_output = Path(args.markdown_output) if args.markdown_output else output.with_suffix(".md")
    markdown_output.write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
