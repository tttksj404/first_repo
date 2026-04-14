#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "quant_runtime" / "artifacts" / "strategy_runtime_gap_report.md"


def main() -> int:
    text = """# Strategy Runtime Gap Report

## Verified

- `funding_rate_strategy` configuration exists in `strategy_override.approved.json`
- candidate carry overrides are generated under `quant_runtime/artifacts/candidate_overrides/`
- `PaperTradingService` now loads `funding_rate_strategy` from the active override path
- funding-enabled symbols can emit funding-owned futures entries and funding-owned cash exits in the standard paper runtime path
- standalone carry validation can be run via `scripts/carry_runtime_validation.py`

## Remaining Gap

- `Settings.load(...)` still does not expose a first-class `funding_rate_strategy` field
- funding strategy is wired through the service/override path rather than the core typed settings contract
- reporting is still generic; runtime summaries do not yet surface funding-strategy-specific counters as first-class fields

## Impact

- carry candidates can now affect standard `paper-live` / session behavior through `STRATEGY_OVERRIDE_PATH`
- but funding strategy remains a partially integrated extension, not a fully typed top-level runtime subsystem

## Recommended next engineering step

1. Promote `funding_rate_strategy` into typed `Settings`
2. Add funding-strategy-specific fields to runtime summary/state/report artifacts
3. Add paper-shell or daemon regression coverage that proves open/hold/exit behavior end to end
"""
    OUTPUT.write_text(text, encoding="utf-8")
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
