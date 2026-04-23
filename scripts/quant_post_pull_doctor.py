#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_binance.bootstrap import initialize_workspace


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cross-host post-pull doctor for quant runtime bootstrap.",
    )
    parser.add_argument("--base-dir", default="quant_runtime")
    parser.add_argument("--paper-base", default="quant_runtime_paper50")
    parser.add_argument("--exchange", default="bitget")
    args = parser.parse_args()

    base_layout = initialize_workspace(args.base_dir)
    paper_layout = initialize_workspace(args.paper_base)

    def log(message: str) -> None:
        print(message, flush=True)

    log(f"[DOCTOR] repo_root={ROOT}")
    log(f"[DOCTOR] python={sys.executable}")
    log(f"[DOCTOR] workspace initialized: {base_layout.root}, {paper_layout.root}")
    log(f"[DOCTOR] running env-check (exchange={args.exchange})")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "quant_binance.runtime",
            "--mode",
            "env-check",
            "--exchange",
            args.exchange,
        ],
        cwd=ROOT,
        check=False,
    )

    filters_path = Path(args.paper_base) / "paper50_multi_symbol_filters.json"
    if filters_path.exists():
        try:
            payload = json.loads(filters_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            log(f"[DOCTOR] filter parse error: {filters_path} ({exc})")
            return 1
        profiles = payload.get("symbol_filter_profiles") or {}
        universe = payload.get("universe") or []
        log(f"[DOCTOR] paper50 filters ok: profiles={len(profiles)} universe={len(universe)}")
    else:
        log(
            f"[DOCTOR] warning: {filters_path} is missing "
            "(paper50 will use runtime defaults until created)"
        )

    log("[DOCTOR] done")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
