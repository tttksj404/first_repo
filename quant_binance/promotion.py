from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from quant_binance.auto_mode import apply_auto_mode_runtime_overrides
from quant_binance.env import resolve_strategy_profile
from quant_binance.policy_evidence import (
    baseline_control_replay_provenance,
    build_replay_provenance,
    checkpoint_replay_provenance,
)
from quant_binance.policy_lineage import build_policy_state_lineage_snapshot, policy_lineage_alignment

_log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"
_MAJOR_PRIORITY_SYMBOLS = {"BTCUSDT", "ETHUSDT"}


def proposal_paths(base_dir: str | Path = "quant_runtime") -> dict[str, Path]:
    root = Path(base_dir) / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    return {
        "pending": root / "strategy_override.pending.json",
        "approved": root / "strategy_override.approved.json",
        "report": root / "strategy_override.report.json",
        "optimization_latest": root / "optimization" / "latest.json",
    }


def _latest_file_under(root: Path, name: str) -> Path | None:
    matches = sorted(root.rglob(name), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _runtime_profile_config() -> dict[str, Any]:
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    profile = resolve_strategy_profile() or "live-ultra-aggressive"
    profile_overrides = raw.get("strategy_profiles", {}).get(profile, {})
    raw = _deep_merge(raw, profile_overrides)
    raw["strategy_profile"] = profile
    return raw


def _bucket_aware_positive_priority_ranks(
    symbol_lifecycle: list[dict[str, Any]] | None,
) -> dict[str, int]:
    ranks: dict[str, int] = {}
    for item in list(symbol_lifecycle or []):
        payload = dict(item)
        symbol = str(payload.get("symbol", "") or "")
        if not symbol:
            continue
        if str(payload.get("symbol_evidence_source", "") or "") != "policy_context_bucket":
            continue
        if not bool(payload.get("policy_context_bucket_evidence_available")):
            continue
        recommended_action = str(payload.get("recommended_action", "keep") or "keep")
        target_state = str(payload.get("target_state", "baseline") or "baseline")
        recommendation = str(payload.get("recommendation", "keep") or "keep")
        rank: int | None = None
        if recommended_action == "cautious_repromote" or target_state == "cautious_repromotion":
            rank = 0
        elif recommendation == "promote" and target_state == "promoted":
            rank = 1
        elif recommendation == "promote" and recommended_action == "keep":
            rank = 2
        if rank is None:
            continue
        previous_rank = ranks.get(symbol)
        if previous_rank is None or rank < previous_rank:
            ranks[symbol] = rank
    return ranks


def _reprioritize_symbols(
    symbols: list[str],
    *,
    positive_priority_ranks: dict[str, int],
) -> list[str]:
    indexed_symbols = {
        str(symbol): index
        for index, symbol in enumerate(symbols)
        if str(symbol)
    }
    return sorted(
        [str(symbol) for symbol in symbols if str(symbol)],
        key=lambda symbol: (
            0 if symbol in positive_priority_ranks and symbol in _MAJOR_PRIORITY_SYMBOLS else
            1 if symbol in _MAJOR_PRIORITY_SYMBOLS else
            2 if symbol in positive_priority_ranks else
            3,
            positive_priority_ranks.get(symbol, 99),
            indexed_symbols.get(symbol, 0),
        ),
    )


def _derived_runtime_overrides(
    *,
    pruning_recommendations: list[dict[str, Any]],
    symbol_lifecycle: list[dict[str, Any]] | None = None,
    auto_mode: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = _runtime_profile_config()
    prune_symbols = {
        str(item.get("symbol"))
        for item in pruning_recommendations
        if item.get("recommendation") == "prune" and item.get("symbol")
    }
    deprioritized_symbols = {
        str(item.get("symbol"))
        for item in pruning_recommendations
        if item.get("recommendation") in {"prune", "demote", "observe_only"} and item.get("symbol")
    }
    for item in list(symbol_lifecycle or []):
        symbol = str(item.get("symbol", "") or "")
        target_state = str(item.get("target_state", "baseline") or "baseline")
        lifecycle_action = str(item.get("recommended_action", "keep") or "keep")
        if not symbol:
            continue
        if target_state == "demoted" and lifecycle_action in {"rollback", "hold"}:
            prune_symbols.add(symbol)
            deprioritized_symbols.add(symbol)
        elif target_state in {"observe_only", "re_review"} or lifecycle_action in {"hold", "re_review"}:
            deprioritized_symbols.add(symbol)
    positive_priority_ranks = _bucket_aware_positive_priority_ranks(symbol_lifecycle)
    overrides: dict[str, Any] = {}
    if prune_symbols:
        universe = [symbol for symbol in base.get("universe", []) if symbol not in prune_symbols]
        overrides["universe"] = universe
    futures_priority = _reprioritize_symbols(
        [
            symbol
            for symbol in base.get("futures_exposure", {}).get("priority_symbols", [])
            if symbol not in deprioritized_symbols
        ],
        positive_priority_ranks=positive_priority_ranks,
    )
    spot_priority = _reprioritize_symbols(
        [
            symbol
            for symbol in base.get("spot_support", {}).get("priority_symbols", [])
            if symbol not in deprioritized_symbols
        ],
        positive_priority_ranks=positive_priority_ranks,
    )
    if futures_priority:
        overrides.setdefault("futures_exposure", {})["priority_symbols"] = futures_priority
    if spot_priority:
        overrides.setdefault("spot_support", {})["priority_symbols"] = spot_priority
    overrides = _deep_merge(
        overrides,
        apply_auto_mode_runtime_overrides(base_config=base, auto_mode=auto_mode),
    )
    return overrides


def _simple_baseline_gate_from_comparison(baseline_control_comparison: dict[str, Any]) -> dict[str, Any]:
    baseline = dict(baseline_control_comparison or {})
    verdict = str(baseline.get("verdict", "not_available") or "not_available")
    gate = str(baseline.get("expansion_gate", "") or "")
    if not gate:
        if verdict == "supportive":
            gate = "pass"
        elif verdict in {"parity", "caution"}:
            gate = "block"
        else:
            gate = "not_available"
    return {
        "status": gate,
        "verdict": verdict,
        "reason": str(baseline.get("expansion_gate_reason", "") or ""),
        "bucket_replay_ready": bool(baseline.get("bucket_replay_ready")),
        "bucket_replay_reference_bucket": str(baseline.get("bucket_replay_reference_bucket", "not_available") or "not_available"),
        "bucket_replay_reason": str(baseline.get("bucket_replay_reason", "") or ""),
        "baseline_control_comparison": baseline,
    }


def _proposal_status_from_gates(
    *,
    checkpoint_auto_judge: dict[str, Any],
    baseline_gate: dict[str, Any],
    executive_operating_verdict: dict[str, Any] | None = None,
    live_evidence_rejudge: dict[str, Any] | None = None,
    lineage_status: str = "",
) -> str:
    if lineage_status in {"mismatch", "stale"}:
        return "proposal_pending"
    checkpoint_verdict = str(checkpoint_auto_judge.get("verdict", "") or "")
    checkpoint_evidence_source = str(checkpoint_auto_judge.get("evidence_source", "") or "")
    checkpoint_evidence_policy_bucket = str(checkpoint_auto_judge.get("evidence_policy_bucket", "") or "")
    if checkpoint_verdict == "expand" and (
        checkpoint_evidence_source != "policy_bucket"
        or checkpoint_evidence_policy_bucket != "staged_candidate"
    ):
        return "proposal_pending"
    executive_verdict = str(dict(executive_operating_verdict or {}).get("verdict", "") or "")
    if executive_verdict == "rollback":
        return "proposal_blocked"
    if executive_verdict in {"tighten", "hold", "rebuild_evidence"}:
        return "proposal_pending"
    if str(dict(live_evidence_rejudge or {}).get("status", "") or "") in {"waiting", "blocked"}:
        return "proposal_pending"
    if not checkpoint_auto_judge and str(baseline_gate.get("status", "not_available") or "not_available") != "pass":
        return "proposal_pending"
    if checkpoint_verdict == "rollback":
        return "proposal_blocked"
    if checkpoint_verdict in {"tighten", "hold"}:
        return "proposal_pending"
    if str(baseline_gate.get("status", "")) == "block":
        return "proposal_pending"
    return "proposal_ready"


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _log.warning("failed to read promotion data %s", path, exc_info=True)
        return {}
    return payload if isinstance(payload, dict) else {}


def _comparison_policy_lineage(payload: dict[str, Any]) -> dict[str, Any]:
    evidence = dict(payload.get("evidence", {}) or {})
    lineage_attribution = dict(payload.get("lineage_attribution", evidence.get("lineage_attribution", {})) or {})
    explicit = dict(
        payload.get(
            "current_policy_lineage",
            evidence.get("current_policy_lineage", lineage_attribution.get("current_policy_lineage", {})),
        )
        or {}
    )
    return explicit


def _executive_operating_verdict_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(
        payload.get(
            "executive_operating_verdict",
            dict(payload.get("evidence", {}) or {}).get("executive_operating_verdict", {}),
        )
        or {}
    )


def _live_evidence_rejudge_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    executive_operating_verdict = _executive_operating_verdict_from_payload(payload)
    return dict(
        payload.get(
            "live_evidence_rejudge",
            executive_operating_verdict.get("live_evidence_rejudge", {}),
        )
        or {}
    )


def _primary_proposal_replay_provenance(
    executive_operating_verdict: dict[str, Any] | None,
    checkpoint_auto_judge: dict[str, Any] | None,
    baseline_control_comparison: dict[str, Any] | None,
) -> dict[str, Any]:
    executive_payload = dict(executive_operating_verdict or {})
    executive_provenance = dict(executive_payload.get("replay_provenance", {}) or {})
    primary = dict(executive_provenance.get("primary", {}) or {})
    if str(primary.get("classification", "not_available") or "not_available") != "not_available":
        return primary
    checkpoint_provenance = dict(checkpoint_auto_judge or {}).get("replay_provenance", {})
    if not checkpoint_provenance:
        checkpoint_provenance = checkpoint_replay_provenance(checkpoint_auto_judge)
    checkpoint_entry = dict(checkpoint_provenance or {})
    if str(checkpoint_entry.get("classification", "not_available") or "not_available") != "not_available":
        checkpoint_entry["decision_surface"] = "checkpoint_auto_judge"
        return checkpoint_entry
    baseline_provenance = dict(baseline_control_comparison or {}).get("replay_provenance", {})
    if not baseline_provenance:
        baseline_provenance = baseline_control_replay_provenance(baseline_control_comparison)
    baseline_entry = dict(baseline_provenance or {})
    if str(baseline_entry.get("classification", "not_available") or "not_available") != "not_available":
        baseline_entry["decision_surface"] = "baseline_control"
        return baseline_entry
    fallback = build_replay_provenance()
    fallback["decision_surface"] = "not_available"
    return fallback


def _load_checkpoint_auto_judge(*, base_dir: str | Path) -> dict[str, Any]:
    root = Path(base_dir) / "output" / "paper-live-shell"
    latest_policy_state_path = _latest_file_under(root, "policy_state.json")
    latest_policy_state_payload = _read_json(latest_policy_state_path)
    latest_executive_operating_verdict = _executive_operating_verdict_from_payload(latest_policy_state_payload)
    latest_live_evidence_rejudge = _live_evidence_rejudge_from_payload(latest_policy_state_payload)
    active_policy_lineage = build_policy_state_lineage_snapshot(
        latest_policy_state_payload,
        source="proposal_latest_policy_state",
    )
    latest_policy_comparison_path = _latest_file_under(root, "policy_comparison.json")
    if latest_policy_comparison_path is not None:
        payload = _read_json(latest_policy_comparison_path)
        judge = dict(payload.get("checkpoint_auto_judge", {}) or {})
        baseline_control_comparison = dict(payload.get("baseline_control_comparison", {}) or {})
        symbol_lifecycle = list(payload.get("symbol_lifecycle", payload.get("evidence", {}).get("symbol_lifecycle", [])) or [])
        comparison_lineage = _comparison_policy_lineage(payload)
        lineage_alignment = policy_lineage_alignment(active_policy_lineage, comparison_lineage)
        if bool(active_policy_lineage.get("available")) and bool(comparison_lineage.get("available")) and not bool(lineage_alignment.get("aligned")):
            return {
                "judge": {},
                "baseline_control_comparison": {},
                "symbol_lifecycle": [],
                "auto_mode": {},
                "executive_operating_verdict": latest_executive_operating_verdict,
                "live_evidence_rejudge": latest_live_evidence_rejudge,
                "source_path": str(latest_policy_comparison_path),
                "source_type": "policy_comparison",
                "lineage_status": str(lineage_alignment.get("status", "mismatch") or "mismatch"),
                "lineage_reason": str(lineage_alignment.get("reason", "POLICY_LINEAGE_MISMATCH") or "POLICY_LINEAGE_MISMATCH"),
            }
        if judge:
            return {
                "judge": judge,
                "baseline_control_comparison": baseline_control_comparison,
                "symbol_lifecycle": symbol_lifecycle,
                "auto_mode": dict(payload.get("auto_mode", {}) or {}),
                "executive_operating_verdict": (
                    _executive_operating_verdict_from_payload(payload) or latest_executive_operating_verdict
                ),
                "live_evidence_rejudge": (
                    _live_evidence_rejudge_from_payload(payload) or latest_live_evidence_rejudge
                ),
                "source_path": str(latest_policy_comparison_path),
                "source_type": "policy_comparison",
                "lineage_status": "aligned" if bool(lineage_alignment.get("aligned")) else "unknown",
                "lineage_reason": str(lineage_alignment.get("reason", "") or ""),
            }
        if baseline_control_comparison:
            return {
                "judge": {},
                "baseline_control_comparison": baseline_control_comparison,
                "symbol_lifecycle": symbol_lifecycle,
                "auto_mode": dict(payload.get("auto_mode", {}) or {}),
                "executive_operating_verdict": (
                    _executive_operating_verdict_from_payload(payload) or latest_executive_operating_verdict
                ),
                "live_evidence_rejudge": (
                    _live_evidence_rejudge_from_payload(payload) or latest_live_evidence_rejudge
                ),
                "source_path": str(latest_policy_comparison_path),
                "source_type": "policy_comparison",
                "lineage_status": "aligned" if bool(lineage_alignment.get("aligned")) else "unknown",
                "lineage_reason": str(lineage_alignment.get("reason", "") or ""),
            }
    if latest_policy_state_path is not None:
        payload = latest_policy_state_payload
        judge = dict(payload.get("checkpoint_auto_judge", {}) or {})
        baseline_control_comparison = dict(
            judge.get("baseline_control_comparison", payload.get("baseline_control_comparison", {})) or {}
        )
        symbol_lifecycle = list(payload.get("symbol_lifecycle", []) or [])
        if judge:
            return {
                "judge": judge,
                "baseline_control_comparison": baseline_control_comparison,
                "symbol_lifecycle": symbol_lifecycle,
                "auto_mode": dict(payload.get("auto_mode", dict(judge.get("auto_mode", {})) or {}) or {}),
                "executive_operating_verdict": (
                    _executive_operating_verdict_from_payload(payload) or latest_executive_operating_verdict
                ),
                "live_evidence_rejudge": (
                    _live_evidence_rejudge_from_payload(payload) or latest_live_evidence_rejudge
                ),
                "source_path": str(latest_policy_state_path),
                "source_type": "policy_state",
                "lineage_status": "aligned",
                "lineage_reason": "POLICY_STATE_CURRENT",
            }
        if baseline_control_comparison:
            return {
                "judge": {},
                "baseline_control_comparison": baseline_control_comparison,
                "symbol_lifecycle": symbol_lifecycle,
                "auto_mode": dict(payload.get("auto_mode", {}) or {}),
                "executive_operating_verdict": (
                    _executive_operating_verdict_from_payload(payload) or latest_executive_operating_verdict
                ),
                "live_evidence_rejudge": (
                    _live_evidence_rejudge_from_payload(payload) or latest_live_evidence_rejudge
                ),
                "source_path": str(latest_policy_state_path),
                "source_type": "policy_state",
                "lineage_status": "aligned",
                "lineage_reason": "POLICY_STATE_CURRENT",
            }
    return {
        "judge": {},
        "baseline_control_comparison": {},
        "symbol_lifecycle": [],
        "auto_mode": {},
        "executive_operating_verdict": latest_executive_operating_verdict,
        "live_evidence_rejudge": latest_live_evidence_rejudge,
        "source_path": "",
        "source_type": "",
        "lineage_status": "unknown",
        "lineage_reason": "",
    }


def build_strategy_proposal(*, base_dir: str | Path = "quant_runtime") -> dict[str, Any]:
    paths = proposal_paths(base_dir)
    latest = paths["optimization_latest"]
    if not latest.exists():
        payload = {"status": "no_optimization_artifact"}
        paths["report"].write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload
    optimization = json.loads(latest.read_text(encoding="utf-8"))
    best = optimization.get("best_candidate") or {}
    base_root = Path(base_dir)
    latest_performance_path = _latest_file_under(base_root / "output" / "paper-live-shell", "performance_report.json")
    latest_recent_comparison_path = _latest_file_under(base_root / "output" / "strategy-comparison-recent", "comparison.json")
    performance = json.loads(latest_performance_path.read_text(encoding="utf-8")) if latest_performance_path else {}
    comparison = json.loads(latest_recent_comparison_path.read_text(encoding="utf-8")) if latest_recent_comparison_path else {}
    pruning_recommendations = performance.get("pruning_recommendations") or []
    risky_symbols = [
        item.get("symbol")
        for item in pruning_recommendations
        if item.get("recommendation") in {"prune", "demote", "observe_only"}
    ]
    strategies = comparison.get("strategies") or []
    best_comparison = None
    if strategies:
        best_comparison = max(strategies, key=lambda item: float(item.get("total_pnl_usd", 0.0)))
    checkpoint_judge_context = _load_checkpoint_auto_judge(base_dir=base_dir)
    checkpoint_auto_judge = dict(checkpoint_judge_context.get("judge", {}) or {})
    baseline_control_comparison = dict(checkpoint_judge_context.get("baseline_control_comparison", {}) or {})
    symbol_lifecycle = list(checkpoint_judge_context.get("symbol_lifecycle", []) or [])
    auto_mode = dict(checkpoint_judge_context.get("auto_mode", {}) or {})
    executive_operating_verdict = dict(checkpoint_judge_context.get("executive_operating_verdict", {}) or {})
    live_evidence_rejudge = dict(checkpoint_judge_context.get("live_evidence_rejudge", {}) or {})
    lifecycle_block_rows = [
        dict(item)
        for item in symbol_lifecycle
        if str(item.get("recommended_action", "keep") or "keep") in {"rollback", "hold", "re_review"}
    ]
    lifecycle_cautious_rows = [
        dict(item)
        for item in symbol_lifecycle
        if str(item.get("recommended_action", "keep") or "keep") == "cautious_repromote"
    ]
    runtime_overrides = _derived_runtime_overrides(
        pruning_recommendations=pruning_recommendations,
        symbol_lifecycle=symbol_lifecycle,
        auto_mode=auto_mode,
    )
    merged_overrides = _deep_merge(best.get("overrides", {}), runtime_overrides)
    baseline_gate = _simple_baseline_gate_from_comparison(baseline_control_comparison)
    checkpoint_verdict = str(checkpoint_auto_judge.get("verdict", "") or "")
    checkpoint_provenance = dict(
        checkpoint_auto_judge.get("replay_provenance", {}) or checkpoint_replay_provenance(checkpoint_auto_judge)
    )
    baseline_provenance = dict(
        baseline_control_comparison.get("replay_provenance", {}) or baseline_control_replay_provenance(baseline_control_comparison)
    )
    executive_replay_provenance = dict(executive_operating_verdict.get("replay_provenance", {}) or {})
    primary_replay_provenance = _primary_proposal_replay_provenance(
        executive_operating_verdict=executive_operating_verdict,
        checkpoint_auto_judge=checkpoint_auto_judge,
        baseline_control_comparison=baseline_control_comparison,
    )
    proposal_status = _proposal_status_from_gates(
        checkpoint_auto_judge=checkpoint_auto_judge,
        baseline_gate=baseline_gate,
        executive_operating_verdict=executive_operating_verdict,
        live_evidence_rejudge=live_evidence_rejudge,
        lineage_status=str(checkpoint_judge_context.get("lineage_status", "") or ""),
    )
    proposal = {
        "status": proposal_status,
        "candidate_name": best.get("name"),
        "objective_score": best.get("objective_score"),
        "overrides": merged_overrides,
        "generated_at": optimization.get("generated_at"),
        "checkpoint_auto_judge": checkpoint_auto_judge,
        "baseline_control_comparison": baseline_control_comparison,
        "auto_mode": auto_mode,
        "executive_operating_verdict": executive_operating_verdict,
        "live_evidence_rejudge": live_evidence_rejudge,
        "replay_provenance": {
            "primary": primary_replay_provenance,
            "checkpoint_auto_judge": checkpoint_provenance,
            "simple_baseline_gate": baseline_provenance,
            "executive_operating_verdict": executive_replay_provenance,
        },
        "symbol_lifecycle": symbol_lifecycle,
        "supporting_artifacts": {
            "optimization_latest": str(latest),
            "performance_report": str(latest_performance_path) if latest_performance_path else "",
            "recent_comparison": str(latest_recent_comparison_path) if latest_recent_comparison_path else "",
            "checkpoint_auto_judge_source": str(checkpoint_judge_context.get("source_path", "") or ""),
            "checkpoint_auto_judge_lineage_status": str(checkpoint_judge_context.get("lineage_status", "unknown") or "unknown"),
            "checkpoint_auto_judge_lineage_reason": str(checkpoint_judge_context.get("lineage_reason", "") or ""),
        },
        "gates": {
            "performance_report_present": bool(latest_performance_path),
            "recent_comparison_present": bool(latest_recent_comparison_path),
            "checkpoint_auto_judge_present": bool(checkpoint_auto_judge),
            "checkpoint_auto_judge_verdict": checkpoint_verdict or "not_available",
            "checkpoint_auto_judge_confidence": str(checkpoint_auto_judge.get("confidence", "") or ""),
            "checkpoint_auto_judge_reason_codes": list(checkpoint_auto_judge.get("reason_codes", []) or []),
            "checkpoint_evidence_source": str(checkpoint_auto_judge.get("evidence_source", "not_available") or "not_available"),
            "checkpoint_evidence_policy_bucket": str(
                checkpoint_auto_judge.get("evidence_policy_bucket", "not_available") or "not_available"
            ),
            "checkpoint_replay_provenance": str(
                checkpoint_provenance.get("summary", "not_available") or "not_available"
            ),
            "simple_baseline_gate_status": str(baseline_gate.get("status", "not_available") or "not_available"),
            "simple_baseline_gate_verdict": str(baseline_gate.get("verdict", "not_available") or "not_available"),
            "simple_baseline_gate_reason": str(baseline_gate.get("reason", "") or ""),
            "simple_baseline_gate_present": bool(baseline_control_comparison),
            "simple_baseline_bucket_replay_ready": bool(baseline_gate.get("bucket_replay_ready")),
            "simple_baseline_bucket_replay_reference_bucket": str(
                baseline_gate.get("bucket_replay_reference_bucket", "not_available") or "not_available"
            ),
            "simple_baseline_bucket_replay_reason": str(baseline_gate.get("bucket_replay_reason", "") or ""),
            "simple_baseline_replay_provenance": str(
                baseline_provenance.get("summary", "not_available") or "not_available"
            ),
            "checkpoint_auto_judge_lineage_status": str(checkpoint_judge_context.get("lineage_status", "unknown") or "unknown"),
            "checkpoint_auto_judge_lineage_reason": str(checkpoint_judge_context.get("lineage_reason", "") or ""),
            "auto_mode": str(auto_mode.get("mode", "normal") or "normal"),
            "auto_mode_reason_codes": list(auto_mode.get("reason_codes", []) or []),
            "executive_operating_verdict": str(executive_operating_verdict.get("verdict", "not_available") or "not_available"),
            "executive_operating_reasons": list(executive_operating_verdict.get("reasons", []) or []),
            "executive_operating_confidence": str(executive_operating_verdict.get("confidence", "") or ""),
            "executive_replay_provenance": str(
                dict(executive_replay_provenance.get("primary", {}) or {}).get("summary", "not_available") or "not_available"
            ),
            "proposal_primary_replay_provenance": str(
                primary_replay_provenance.get("summary", "not_available") or "not_available"
            ),
            "live_evidence_rejudge_status": str(live_evidence_rejudge.get("status", "not_available") or "not_available"),
            "live_evidence_rejudge_reasons": list(live_evidence_rejudge.get("reason_codes", []) or []),
            "live_evidence_lineage_status": str(live_evidence_rejudge.get("policy_lineage_status", "unknown") or "unknown"),
            "fresh_live_evidence_accumulated": bool(live_evidence_rejudge.get("fresh_evidence_accumulated")),
            "simple_baseline_strategy": str(
                dict(baseline_control_comparison.get("best_simple_baseline", {}) or {}).get("strategy_name", "") or ""
            ),
            "risky_symbols": risky_symbols,
            "lifecycle_blocked_symbols": sorted(
                str(item.get("symbol", "") or "")
                for item in lifecycle_block_rows
                if str(item.get("symbol", "") or "")
            ),
            "lifecycle_cautious_repromotion_symbols": sorted(
                str(item.get("symbol", "") or "")
                for item in lifecycle_cautious_rows
                if str(item.get("symbol", "") or "")
            ),
            "auto_pruned_symbols": sorted(
                str(symbol)
                for symbol in merged_overrides.get("universe", [])
            )
            if "universe" in merged_overrides
            else [],
            "best_comparison_strategy": (best_comparison or {}).get("strategy_name") if best_comparison else None,
            "best_comparison_total_pnl_usd": (best_comparison or {}).get("total_pnl_usd") if best_comparison else None,
        },
    }
    paths["pending"].write_text(json.dumps(proposal, indent=2, sort_keys=True), encoding="utf-8")
    paths["report"].write_text(json.dumps(proposal, indent=2, sort_keys=True), encoding="utf-8")
    return proposal


def apply_strategy_proposal(*, base_dir: str | Path = "quant_runtime") -> dict[str, Any]:
    paths = proposal_paths(base_dir)
    pending = paths["pending"]
    if not pending.exists():
        return {"status": "no_pending_proposal"}
    proposal = json.loads(pending.read_text(encoding="utf-8"))
    if str(proposal.get("status", "proposal_ready") or "proposal_ready") != "proposal_ready":
        return {
            "status": "proposal_not_ready",
            "proposal_status": str(proposal.get("status", "") or ""),
            "checkpoint_auto_judge": dict(proposal.get("checkpoint_auto_judge", {}) or {}),
            "baseline_control_comparison": dict(proposal.get("baseline_control_comparison", {}) or {}),
            "executive_operating_verdict": dict(proposal.get("executive_operating_verdict", {}) or {}),
            "symbol_lifecycle": list(proposal.get("symbol_lifecycle", []) or []),
        }
    overrides = proposal.get("overrides", {})
    paths["approved"].write_text(json.dumps(overrides, indent=2, sort_keys=True), encoding="utf-8")
    pending.unlink()
    subprocess.run(["sh", "scripts/quant_stop.sh"], check=False)
    subprocess.run(["sh", "scripts/quant_run_live_orders.sh", str(base_dir)], check=False)
    return {"status": "applied", "approved_path": str(paths["approved"])}


def reject_strategy_proposal(*, base_dir: str | Path = "quant_runtime") -> dict[str, Any]:
    paths = proposal_paths(base_dir)
    if paths["pending"].exists():
        paths["pending"].unlink()
    latest = paths["optimization_latest"]
    if latest.exists():
        optimization_dir = latest.parent
        for artifact in optimization_dir.glob("sandbox-optimization-*.json"):
            if artifact.name != latest.name:
                artifact.unlink(missing_ok=True)
    return {"status": "rejected"}


def cleanup_runtime_artifacts(*, base_dir: str | Path = "quant_runtime") -> dict[str, Any]:
    root = Path(base_dir)
    removed: list[str] = []
    for path in [root / "output", root / "oracle", root / "manifests"]:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
            path.mkdir(parents=True, exist_ok=True)
            removed.append(str(path))
    return {"status": "cleaned", "removed": removed}
