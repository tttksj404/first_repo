from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def proposal_paths(base_dir: str | Path = "quant_runtime") -> dict[str, Path]:
    root = Path(base_dir) / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    return {
        "pending": root / "strategy_override.pending.json",
        "approved": root / "strategy_override.approved.json",
        "report": root / "strategy_override.report.json",
        "optimization_latest": root / "optimization" / "latest.json",
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
    proposal = {
        "status": "proposal_ready",
        "candidate_name": best.get("name"),
        "objective_score": best.get("objective_score"),
        "overrides": best.get("overrides", {}),
        "generated_at": optimization.get("generated_at"),
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
