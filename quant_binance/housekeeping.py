from __future__ import annotations

import shutil
from pathlib import Path


def prune_old_run_directories(*, mode_root: Path, keep_recent_runs: int) -> None:
    """Keep only the most recent run directories under the given mode root."""
    if keep_recent_runs <= 0 or not mode_root.exists():
        return

    run_dirs = [path for path in mode_root.iterdir() if path.is_dir()]
    run_dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for old_dir in run_dirs[keep_recent_runs:]:
        shutil.rmtree(old_dir, ignore_errors=True)
