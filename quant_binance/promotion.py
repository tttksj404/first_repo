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


def _derived_runtime_overrides(*, pruning_recommendations: list[dict[str, Any]]) -> dict[str, Any]:
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
    runtime_overrides = _derived_runtime_overrides(pruning_recommendations=pruning_recommendations)
    strategies = comparison.get("strategies") or []
    best_comparison = None
    if strategies:
        best_comparison = max(strategies, key=lambda item: float(item.get("total_pnl_usd", 0.0)))
    merged_overrides = _deep_merge(best.get("overrides", {}), runtime_overrides)
    proposal = {
        "status": "proposal_ready",
        "candidate_name": best.get("name"),
        "objective_score": best.get("objective_score"),
        "overrides": merged_overrides,
        "generated_at": optimization.get("generated_at"),
        "supporting_artifacts": {
            "optimization_latest": str(latest),
            "performance_report": str(latest_performance_path) if latest_performance_path else "",
            "recent_comparison": str(latest_recent_comparison_path) if latest_recent_comparison_path else "",
        },
        "gates": {
            "performance_report_present": bool(latest_performance_path),
            "recent_comparison_present": bool(latest_recent_comparison_path),
            "risky_symbols": risky_symbols,
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
