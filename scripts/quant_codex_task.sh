#!/bin/sh
set -eu

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <status-check|capital-report|latest-run-review|strategy-review>" >&2
  exit 1
fi

TASK="$1"
ROOT="$(dirname "$0")/.."

cd "$ROOT"

python3 - <<'PY' "$TASK" "$ROOT"
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

task = sys.argv[1]
root = Path(sys.argv[2]).resolve()

prompts = {
    "status-check": "Review the latest quant_runtime summary/state/log files in this repository and answer concisely: 1) is the daemon alive, 2) are events arriving, 3) are live orders happening, 4) what is the main blocker right now.",
    "capital-report": "Read the latest capital report/state in this repository and answer concisely: 1) spot available balance, 2) futures available balance, 3) whether spot trading is allowed, 4) whether futures trading is allowed, 5) minimum and recommended capital.",
    "latest-run-review": "Inspect the latest quant_runtime run artifacts and summarize the current operating state, recent decisions, kill-switch state, and whether there are obvious runtime issues. Keep it concise.",
    "strategy-review": "Review the current quant_binance strategy implementation and summarize: 1) what quantitative signals it uses, 2) whether it is currently conservative or aggressive, 3) the top 3 risks or limitations.",
}

if task not in prompts:
    raise SystemExit(f"unknown codex task: {task}")

with tempfile.NamedTemporaryFile(delete=False) as handle:
    output_path = Path(handle.name)

try:
    subprocess.run(
        ["./codex", "exec", "-C", str(root), "-o", str(output_path), prompts[task]],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=180,
    )
    text = output_path.read_text(encoding="utf-8").strip()
    print(text or "codex returned no final message")
finally:
    output_path.unlink(missing_ok=True)
PY
