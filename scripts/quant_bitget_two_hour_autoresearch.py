#!/usr/bin/env python3
"""Run a bounded Bitget paper-only AutoResearch monitor loop.

The loop observes local read-only paper decisions, refreshes the high
probability gate summary, computes mature forward outcomes from public Bitget
candles, and writes paper-only tuning candidates. It never calls private
exchange endpoints and never places, tests, cancels, or modifies orders.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.quant_bitget_high_probability_monitor import build_summary  # noqa: E402
from scripts.quant_bitget_outcome_feedback import (  # noqa: E402
    _bucket_stats,
    _read_json,
    _write_json,
    build_feedback_config,
    build_forward_outcomes,
)


def _jsonl_count(path: Path) -> tuple[int, str | None]:
    count = 0
    latest: str | None = None
    if not path.exists():
        return count, latest
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            count += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            latest = str(row.get("timestamp") or row.get("ts") or latest or "")
    return count, latest


def _preflight_safety(path: Path) -> dict[str, Any]:
    rows = 0
    live_order_count = 0
    send_order_hits = 0
    latest: str | None = None
    if path.exists():
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                rows += 1
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                latest = str(row.get("timestamp") or row.get("ts") or latest or "")
                live_order_count += int(row.get("live_order_count") or 0)
                if row.get("send_order") or row.get("place_order"):
                    send_order_hits += 1
    return {
        "execution_preflight_rows": rows,
        "latest": latest,
        "live_order_count": live_order_count,
        "send_order_hits": send_order_hits,
    }


def _fingerprint(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _selected_stats(bucket_stats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    selected = {
        key: value
        for key, value in bucket_stats.items()
        if "|admit_paper|" in key or "|confirm_only|" in key
    }
    values = [float(value.get("avg_net15_bps") or 0.0) for value in selected.values()]
    wins = [float(value.get("win15_rate") or 0.0) for value in selected.values()]
    return {
        "selected_bucket_count": len(selected),
        "selected_avg_net15_bps": round(sum(values) / len(values), 6) if values else None,
        "selected_avg_win15_rate": round(sum(wins) / len(wins), 6) if wins else None,
        "selected_buckets": selected,
    }


def _write_cycle(
    *,
    output_dir: Path,
    cycle: int,
    decisions_path: Path,
    overlay_path: Path,
    base_config_path: Path,
    insecure_ssl: bool,
    previous_config_hash: str | None,
) -> dict[str, Any]:
    cycle_dir = output_dir / f"cycle_{cycle:02d}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    cycle_dir.mkdir(parents=True, exist_ok=True)
    gate_summary_path = cycle_dir / "high_probability_gate_summary.json"
    outcome_report_path = cycle_dir / "outcome_feedback_report.json"
    tuned_config_path = cycle_dir / "paper50_multi_symbol_filters.outcome_feedback.json"

    gate_summary = build_summary(decisions_path=decisions_path, overlay_path=overlay_path)
    _write_json(gate_summary_path, gate_summary)

    outcomes = build_forward_outcomes(
        decisions_path=decisions_path,
        gate_summary_path=gate_summary_path,
        allow_insecure_ssl=insecure_ssl,
    )
    bucket_stats = _bucket_stats(outcomes)
    base_config = _read_json(base_config_path)
    tuned, actions = build_feedback_config(base_config=base_config, bucket_stats=bucket_stats)
    tuned_hash = _fingerprint(tuned)
    material_change = bool(actions) and tuned_hash != previous_config_hash
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "paper_only": True,
        "cycle": cycle,
        "decision_count": gate_summary.get("decision_count"),
        "decision_count_with_mature_outcomes": len(outcomes),
        "state_counts": gate_summary.get("state_counts", {}),
        "symbol_state_counts": gate_summary.get("symbol_state_counts", {}),
        "bucket_stats": bucket_stats,
        "selected_stats": _selected_stats(bucket_stats),
        "actions": actions,
        "verdict": "candidate_tighten" if material_change else ("hold_existing_tightening" if actions else "hold"),
        "material_config_change": material_change,
        "base_config": str(base_config_path),
        "tuned_config": str(tuned_config_path),
    }
    _write_json(outcome_report_path, report)
    _write_json(tuned_config_path, tuned)
    cycle_summary = {
        "cycle": cycle,
        "cycle_dir": str(cycle_dir),
        "gate_summary": str(gate_summary_path),
        "outcome_report": str(outcome_report_path),
        "tuned_config": str(tuned_config_path),
        "decision_count": gate_summary.get("decision_count"),
        "decision_count_with_mature_outcomes": len(outcomes),
        "state_counts": gate_summary.get("state_counts", {}),
        "action_count": len(actions),
        "verdict": report["verdict"],
        "material_config_change": material_change,
        "config_hash": tuned_hash,
    }
    _write_json(cycle_dir / "cycle_summary.json", cycle_summary)
    return cycle_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded Bitget paper-only AutoResearch loop.")
    parser.add_argument("--run-base", required=True)
    parser.add_argument("--overlay", default="quant_runtime_paper50/bitget_overlay_tuning/bitget_overlay_tuning_report.json")
    parser.add_argument("--base-config", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--duration-minutes", type=int, default=120)
    parser.add_argument("--interval-seconds", type=int, default=900)
    parser.add_argument("--insecure-ssl", action="store_true")
    args = parser.parse_args()

    run_base = Path(args.run_base)
    decisions_path = run_base / "forensics" / "decisions.jsonl"
    preflight_path = run_base / "forensics" / "execution_preflight.jsonl"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "status.json"
    cycle_log_path = output_dir / "cycle_log.jsonl"
    ends_at = datetime.now(UTC) + timedelta(minutes=args.duration_minutes)
    previous_config_hash: str | None = None
    cycle = 0

    while datetime.now(UTC) < ends_at:
        cycle += 1
        decision_count, latest_decision = _jsonl_count(decisions_path)
        safety = _preflight_safety(preflight_path)
        cycle_summary: dict[str, Any]
        if safety["live_order_count"] or safety["send_order_hits"]:
            cycle_summary = {
                "cycle": cycle,
                "generated_at": datetime.now(UTC).isoformat(),
                "verdict": "halt_safety_violation",
                "decision_count": decision_count,
                "latest_decision": latest_decision,
                "safety": safety,
            }
            _write_json(output_dir / f"cycle_{cycle:02d}_halt.json", cycle_summary)
            _write_json(status_path, cycle_summary)
            with cycle_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(cycle_summary, ensure_ascii=False, sort_keys=True) + "\n")
            return 2

        cycle_summary = _write_cycle(
            output_dir=output_dir,
            cycle=cycle,
            decisions_path=decisions_path,
            overlay_path=Path(args.overlay),
            base_config_path=Path(args.base_config),
            insecure_ssl=args.insecure_ssl,
            previous_config_hash=previous_config_hash,
        )
        previous_config_hash = str(cycle_summary.get("config_hash") or previous_config_hash or "")
        cycle_summary.update(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "latest_decision": latest_decision,
                "safety": safety,
                "ends_at": ends_at.isoformat(),
                "next_cycle_after_seconds": args.interval_seconds,
            }
        )
        _write_json(status_path, cycle_summary)
        with cycle_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(cycle_summary, ensure_ascii=False, sort_keys=True) + "\n")
        print(json.dumps(cycle_summary, ensure_ascii=False, sort_keys=True), flush=True)
        remaining = (ends_at - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            break
        time.sleep(min(args.interval_seconds, max(1, int(remaining))))

    final_status = _read_json(status_path) if status_path.exists() else {}
    final_status.update({"completed_at": datetime.now(UTC).isoformat(), "verdict": "completed"})
    _write_json(status_path, final_status)
    print(json.dumps(final_status, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
