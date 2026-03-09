from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkspaceLayout:
    root: Path
    output_root: Path
    artifact_root: Path
    oracle_root: Path
    manifest_root: Path


def initialize_workspace(base_dir: str | Path) -> WorkspaceLayout:
    root = Path(base_dir)
    output_root = root / "output"
    artifact_root = root / "artifacts"
    oracle_root = root / "oracle"
    manifest_root = root / "manifests"

    for path in (
        output_root / "replay",
        output_root / "paper-live",
        output_root / "paper-live-test-order",
        output_root / "paper-live-shell",
        artifact_root,
        oracle_root,
        manifest_root,
    ):
        path.mkdir(parents=True, exist_ok=True)

    return WorkspaceLayout(
        root=root,
        output_root=output_root,
        artifact_root=artifact_root,
        oracle_root=oracle_root,
        manifest_root=manifest_root,
    )
