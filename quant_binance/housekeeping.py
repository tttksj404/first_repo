from __future__ import annotations

from pathlib import Path


def prune_old_run_directories(*, mode_root: str | Path, keep_recent_runs: int) -> list[Path]:
    root = Path(mode_root)
    if not root.exists():
        return []
    run_dirs = sorted(
        [path for path in root.iterdir() if path.is_dir() and path.name != "latest"],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    removed: list[Path] = []
    for path in run_dirs[keep_recent_runs:]:
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        path.rmdir()
        removed.append(path)
    return removed
