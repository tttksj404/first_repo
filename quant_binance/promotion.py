from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from quant_binance.env import resolve_strategy_profile


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


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


def _derived_runtime_overrides(
    *,
    pruning_recommendations: list[dict[str, Any]],
    symbol_lifecycle: list[dict[str, Any]] | None = None,
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
    overrides: dict[str, Any] = {}
    if prune_symbols:
        universe = [symbol for symbol in base.get("universe", []) if symbol not in prune_symbols]
        overrides["universe"] = universe
    futures_priority = [
        symbol
        for symbol in base.get("futures_exposure", {}).get("priority_symbols", [])
        if symbol not in deprioritized_symbols
    ]
    spot_priority = [
        symbol
        for symbol in base.get("spot_support", {}).get("priority_symbols", [])
        if symbol not in deprioritized_symbols
    ]
    if futures_priority:
        overrides.setdefault("futures_exposure", {})["priority_symbols"] = futures_priority
    if spot_priority:
        overrides.setdefault("spot_support", {})["priority_symbols"] = spot_priority
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
        "baseline_control_comparison": baseline,
    }


def _proposal_status_from_gates(
    *,
    checkpoint_auto_judge: dict[str, Any],
    baseline_gate: dict[str, Any],
) -> str:
    checkpoint_verdict = str(checkpoint_auto_judge.get("verdict", "") or "")
    if checkpoint_verdict == "rollback":
        return "proposal_blocked"
    if checkpoint_verdict in {"tighten", "hold"}:
        return "proposal_pending"
    if str(baseline_gate.get("status", "")) == "block":
        return "proposal_pending"
    return "proposal_ready"


def _load_checkpoint_auto_judge(*, base_dir: str | Path) -> dict[str, Any]:
    root = Path(base_dir) / "output" / "paper-live-shell"
    latest_policy_comparison_path = _latest_file_under(root, "policy_comparison.json")
    if latest_policy_comparison_path is not None:
        payload = json.loads(latest_policy_comparison_path.read_text(encoding="utf-8"))
        judge = dict(payload.get("checkpoint_auto_judge", {}) or {})
        baseline_control_comparison = dict(payload.get("baseline_control_comparison", {}) or {})
        symbol_lifecycle = list(payload.get("symbol_lifecycle", payload.get("evidence", {}).get("symbol_lifecycle", [])) or [])
        if judge:
            return {
                "judge": judge,
                "baseline_control_comparison": baseline_control_comparison,
                "symbol_lifecycle": symbol_lifecycle,
                "source_path": str(latest_policy_comparison_path),
                "source_type": "policy_comparison",
            }
        if baseline_control_comparison:
            return {
                "judge": {},
                "baseline_control_comparison": baseline_control_comparison,
                "symbol_lifecycle": symbol_lifecycle,
                "source_path": str(latest_policy_comparison_path),
                "source_type": "policy_comparison",
            }
    latest_policy_state_path = _latest_file_under(root, "policy_state.json")
    if latest_policy_state_path is not None:
        payload = json.loads(latest_policy_state_path.read_text(encoding="utf-8"))
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
                "source_path": str(latest_policy_state_path),
                "source_type": "policy_state",
            }
        if baseline_control_comparison:
            return {
                "judge": {},
                "baseline_control_comparison": baseline_control_comparison,
                "symbol_lifecycle": symbol_lifecycle,
                "source_path": str(latest_policy_state_path),
                "source_type": "policy_state",
            }
    return {"judge": {}, "baseline_control_comparison": {}, "symbol_lifecycle": [], "source_path": "", "source_type": ""}


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
    )
    merged_overrides = _deep_merge(best.get("overrides", {}), runtime_overrides)
    baseline_gate = _simple_baseline_gate_from_comparison(baseline_control_comparison)
    checkpoint_verdict = str(checkpoint_auto_judge.get("verdict", "") or "")
    proposal_status = _proposal_status_from_gates(
        checkpoint_auto_judge=checkpoint_auto_judge,
        baseline_gate=baseline_gate,
    )
    proposal = {
        "status": proposal_status,
        "candidate_name": best.get("name"),
        "objective_score": best.get("objective_score"),
        "overrides": merged_overrides,
        "generated_at": optimization.get("generated_at"),
        "checkpoint_auto_judge": checkpoint_auto_judge,
        "baseline_control_comparison": baseline_control_comparison,
        "symbol_lifecycle": symbol_lifecycle,
        "supporting_artifacts": {
            "optimization_latest": str(latest),
            "performance_report": str(latest_performance_path) if latest_performance_path else "",
            "recent_comparison": str(latest_recent_comparison_path) if latest_recent_comparison_path else "",
            "checkpoint_auto_judge_source": str(checkpoint_judge_context.get("source_path", "") or ""),
        },
        "gates": {
            "performance_report_present": bool(latest_performance_path),
            "recent_comparison_present": bool(latest_recent_comparison_path),
            "checkpoint_auto_judge_present": bool(checkpoint_auto_judge),
            "checkpoint_auto_judge_verdict": checkpoint_verdict or "not_available",
            "checkpoint_auto_judge_confidence": str(checkpoint_auto_judge.get("confidence", "") or ""),
            "checkpoint_auto_judge_reason_codes": list(checkpoint_auto_judge.get("reason_codes", []) or []),
            "simple_baseline_gate_status": str(baseline_gate.get("status", "not_available") or "not_available"),
            "simple_baseline_gate_verdict": str(baseline_gate.get("verdict", "not_available") or "not_available"),
            "simple_baseline_gate_reason": str(baseline_gate.get("reason", "") or ""),
            "simple_baseline_gate_present": bool(baseline_control_comparison),
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
