#!/usr/bin/env python3
"""Run a bounded paper-only Bitget short-overlay observation loop.

The observer combines three read-only diagnostics:
- Bitget public external-alpha shadow candidates and mature outcomes.
- Long-failure short-overlay matching against local paper50 decisions.
- Paper50 long/short scorecard refresh.
- Binance public major-coin 5m trend/leverage profile research.
- Forced paper-only pilots for blocked futures decisions.

It never calls private order endpoints and never places, tests, cancels, or
modifies exchange orders.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "quant_runtime_paper50" / "bitget_external_alpha_shadow"
DEFAULT_DECISION_ROOT = ROOT / "quant_runtime_paper50"
DEFAULT_BASE_CONFIG = ROOT / "quant_runtime_paper50" / "paper50_multi_symbol_filters.json"
DEFAULT_STATUS = DEFAULT_OUTPUT_DIR / "observer_status.json"
DEFAULT_LOG = DEFAULT_OUTPUT_DIR / "observer_cycle_log.jsonl"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _run(args: list[str], *, cwd: Path) -> dict[str, Any]:
    started = datetime.now(UTC)
    proc = subprocess.run(
        args,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {
        "args": args,
        "returncode": proc.returncode,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
    }


def _paper50_safety(decision_root: Path) -> dict[str, Any]:
    status = _read_json(decision_root / "_monitor_status.json")
    heartbeats = dict(status.get("heartbeats") or {})
    live_orders = int(heartbeats.get("live_orders") or status.get("live_order_count") or 0)
    tested_orders = int(heartbeats.get("tested_orders") or status.get("tested_order_count") or 0)
    return {
        "status_ts": status.get("ts") or status.get("updated_at"),
        "decisions": int(heartbeats.get("decisions") or status.get("decision_count") or 0),
        "live_orders": live_orders,
        "tested_orders": tested_orders,
        "bitget_positions": list(dict(status.get("bitget") or {}).get("positions") or []),
        "safe": live_orders == 0 and tested_orders == 0,
    }


def _snapshot(output_dir: Path) -> dict[str, Any]:
    alpha = _read_json(output_dir / "status.json")
    overlay = _read_json(output_dir / "long_failure_overlay_check" / "long_failure_short_overlay_report.json")
    scorecard = _read_json(ROOT / "quant_runtime_paper50" / "artifacts" / "paper50_side_scorecard_latest.json")
    major_5m = _read_json(ROOT / "quant_runtime_paper50" / "artifacts" / "major_5m_leverage_research_latest.json")
    forced_pilot = _read_json(ROOT / "quant_runtime_paper50" / "artifacts" / "paper50_forced_pilot_latest.json")
    return {
        "external_alpha": {
            "candidate_count": alpha.get("candidate_count"),
            "mature_outcome_count": alpha.get("mature_outcome_count"),
            "candidate_counts": alpha.get("candidate_counts", {}),
            "best_mature_candidates": list(alpha.get("best_mature_candidates") or [])[:8],
        },
        "long_failure_overlay": {
            "verdict": overlay.get("verdict"),
            "matched_outcome_count": overlay.get("matched_outcome_count"),
            "enabled_legs": list((overlay.get("long_failure_short_overlay") or {}).get("legs") or []),
            "leg_stats": list(overlay.get("leg_stats") or [])[:8],
        },
        "side_scorecard": {
            "fallback_long_failure_enters_short": dict(scorecard.get("fallback_semantics") or {}).get(
                "long_failure_enters_short"
            ),
            "long_recommendation": dict(dict(scorecard.get("sides") or {}).get("long") or {}).get("recommendation"),
            "short_recommendation": dict(dict(scorecard.get("sides") or {}).get("short") or {}).get("recommendation"),
        },
        "major_5m_leverage": {
            "overall_action": major_5m.get("overall_action"),
            "signal_counts": major_5m.get("signal_counts"),
            "top_profiles": list(major_5m.get("top_profiles") or [])[:5],
            "five_x_hold_assessment_count": len(dict(major_5m.get("five_x_hold_assessment") or {})),
        },
        "forced_pilot": {
            "summary": forced_pilot.get("summary"),
            "active_count": len(list(forced_pilot.get("active_pilots") or [])),
            "completed_recent_count": len(list(forced_pilot.get("completed_recent") or [])),
            "opened_pilot": forced_pilot.get("opened_pilot"),
            "active_pilots": list(forced_pilot.get("active_pilots") or [])[:3],
        },
    }


def run_cycle(
    *,
    cycle: int,
    output_dir: Path,
    decision_root: Path,
    base_config: Path,
    status_path: Path,
    log_path: Path,
    insecure_ssl: bool,
) -> dict[str, Any]:
    safety = _paper50_safety(decision_root)
    cycle_result: dict[str, Any] = {
        "cycle": cycle,
        "generated_at": datetime.now(UTC).isoformat(),
        "paper_only": True,
        "public_endpoints_only": True,
        "safety": safety,
        "commands": [],
    }
    if not safety["safe"]:
        cycle_result["verdict"] = "halt_safety_violation"
        _write_json(status_path, cycle_result)
        _append_jsonl(log_path, cycle_result)
        return cycle_result

    commands = [
        [
            sys.executable,
            "scripts/quant_bitget_external_alpha_monitor.py",
            "--output-dir",
            str(output_dir),
            *(["--insecure-ssl"] if insecure_ssl else []),
        ],
        [
            sys.executable,
            "scripts/quant_paper50_counterfactual.py",
            "--output-base",
            str(decision_root),
            "--write-latest",
            "--per-symbol-limit",
            "12",
            "--min-age-minutes",
            "16",
        ],
        [
            sys.executable,
            "scripts/quant_paper50_futures_signal_outcomes.py",
            "--decisions-path",
            str(decision_root / "forensics" / "decisions.jsonl"),
        ],
        [
            sys.executable,
            "scripts/quant_paper50_forced_pilot.py",
            "--decisions-path",
            str(decision_root / "forensics" / "decisions.jsonl"),
            "--state",
            str(decision_root / "artifacts" / "paper50_forced_pilot_state.json"),
            "--output",
            str(decision_root / "artifacts" / "paper50_forced_pilot_latest.json"),
            "--open-new",
            "--max-active",
            "1",
        ],
        [sys.executable, "scripts/quant_paper50_side_scorecard.py"],
        [
            sys.executable,
            "scripts/quant_bitget_long_failure_short_overlay.py",
            "--decision-root",
            str(decision_root),
            "--external-root",
            str(output_dir),
            "--base-config",
            str(base_config),
            "--output-dir",
            str(output_dir / "long_failure_overlay_check"),
            "--match-window-minutes",
            "7.5",
        ],
        [
            sys.executable,
            "scripts/quant_paper50_post_tune_feedback.py",
            "--filters",
            str(base_config),
            "--state",
            str(decision_root / "artifacts" / "paper50_filter_guard_state.json"),
            "--audit",
            str(decision_root / "artifacts" / "paper50_filter_guard_audit.jsonl"),
            "--counterfactual",
            str(decision_root / "artifacts" / "paper50_counterfactual_latest.json"),
            "--futures-outcomes",
            str(decision_root / "artifacts" / "paper50_futures_signal_outcomes_latest.json"),
            "--output",
            str(decision_root / "artifacts" / "paper50_post_tune_feedback_latest.json"),
        ],
        [
            sys.executable,
            "scripts/quant_paper50_market_regime.py",
            "--output",
            str(decision_root / "artifacts" / "paper50_market_regime_latest.json"),
        ],
        [
            sys.executable,
            "scripts/quant_major_5m_leverage_research.py",
            "--output",
            str(decision_root / "artifacts" / "major_5m_leverage_research_latest.json"),
        ],
        [
            sys.executable,
            "scripts/quant_paper50_promotion_checklist.py",
            "--alpha-status",
            str(output_dir / "status.json"),
            "--overlay-report",
            str(output_dir / "long_failure_overlay_check" / "long_failure_short_overlay_report.json"),
            "--side-scorecard",
            str(decision_root / "artifacts" / "paper50_side_scorecard_latest.json"),
            "--filter-guard-state",
            str(decision_root / "artifacts" / "paper50_filter_guard_state.json"),
            "--filter-guard-latest",
            str(decision_root / "artifacts" / "paper50_filter_guard_latest.json"),
            "--post-tune-feedback",
            str(decision_root / "artifacts" / "paper50_post_tune_feedback_latest.json"),
            "--market-regime",
            str(decision_root / "artifacts" / "paper50_market_regime_latest.json"),
            "--forced-pilot",
            str(decision_root / "artifacts" / "paper50_forced_pilot_latest.json"),
            "--monitor-status",
            str(decision_root / "_monitor_status.json"),
            "--output",
            str(decision_root / "artifacts" / "paper50_promotion_checklist_latest.json"),
        ],
    ]
    for command in commands:
        result = _run(command, cwd=ROOT)
        cycle_result["commands"].append(result)

    failed = [item for item in cycle_result["commands"] if item["returncode"] != 0]
    cycle_result["snapshot"] = _snapshot(output_dir)
    cycle_result["verdict"] = "cycle_error" if failed else "observing"
    _write_json(status_path, cycle_result)
    _append_jsonl(log_path, cycle_result)
    return cycle_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--decision-root", default=str(DEFAULT_DECISION_ROOT))
    parser.add_argument("--base-config", default=str(DEFAULT_BASE_CONFIG))
    parser.add_argument("--status-path", default=str(DEFAULT_STATUS))
    parser.add_argument("--log-path", default=str(DEFAULT_LOG))
    parser.add_argument("--duration-minutes", type=int, default=180)
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--insecure-ssl", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    decision_root = Path(args.decision_root)
    base_config = Path(args.base_config)
    status_path = Path(args.status_path)
    log_path = Path(args.log_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    ends_at = datetime.now(UTC) + timedelta(minutes=max(args.duration_minutes, 1))
    cycle = 0
    while True:
        cycle += 1
        result = run_cycle(
            cycle=cycle,
            output_dir=output_dir,
            decision_root=decision_root,
            base_config=base_config,
            status_path=status_path,
            log_path=log_path,
            insecure_ssl=args.insecure_ssl,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
        if args.once or result.get("verdict") == "halt_safety_violation" or datetime.now(UTC) >= ends_at:
            break
        remaining = max((ends_at - datetime.now(UTC)).total_seconds(), 0.0)
        time.sleep(min(max(args.interval_seconds, 1), remaining))

    final = _read_json(status_path)
    final.update({"completed_at": datetime.now(UTC).isoformat(), "ends_at": ends_at.isoformat()})
    _write_json(status_path, final)
    return 0 if final.get("verdict") != "halt_safety_violation" else 2


if __name__ == "__main__":
    raise SystemExit(main())
