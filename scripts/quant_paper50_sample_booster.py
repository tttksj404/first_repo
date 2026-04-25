#!/usr/bin/env python3
"""Boost paper-only sample collection for top paper50 candidates.

This loop repeatedly refreshes public external-alpha samples and the parallel
research ranking until priority candidates reach a target mature sample count.
It is paper-only and never calls private order endpoints.
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
DEFAULT_DECISION_ROOT = ROOT / "quant_runtime_paper50"
DEFAULT_ALPHA_DIR = DEFAULT_DECISION_ROOT / "bitget_external_alpha_shadow"
DEFAULT_OUTPUT_DIR = DEFAULT_DECISION_ROOT / "artifacts" / "sample_booster"
DEFAULT_STATUS = DEFAULT_DECISION_ROOT / "artifacts" / "paper50_sample_booster_status.json"
DEFAULT_LOG = DEFAULT_DECISION_ROOT / "artifacts" / "paper50_sample_booster_log.jsonl"
DEFAULT_PARALLEL_OUTPUT = DEFAULT_DECISION_ROOT / "artifacts" / "paper50_parallel_research_latest.json"
DEFAULT_TARGET_KEYS = (
    "PEPEUSDT|oi_exhaustion_reversion|short",
    "SOLUSDT|flow_momentum|long",
    "PEPEUSDT|oi_exhaustion_reversion|long",
    "XRPUSDT|oi_momentum_breakout|long",
    "DOGEUSDT|oi_momentum_breakout|long",
)


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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _run(name: str, args: list[str], *, timeout_seconds: int) -> dict[str, Any]:
    started = datetime.now(UTC)
    try:
        proc = subprocess.run(
            args,
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=max(timeout_seconds, 1),
        )
        return {
            "name": name,
            "args": args,
            "returncode": proc.returncode,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "args": args,
            "returncode": 124,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "timed_out": True,
            "timeout_seconds": timeout_seconds,
            "stdout_tail": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "",
        }


def _paper50_safety(decision_root: Path) -> dict[str, Any]:
    status = _read_json(decision_root / "_monitor_status.json")
    heartbeats = dict(status.get("heartbeats") or {})
    bitget = dict(status.get("bitget") or {})
    live_orders = _safe_int(heartbeats.get("live_orders") or status.get("live_order_count"))
    tested_orders = _safe_int(heartbeats.get("tested_orders") or status.get("tested_order_count"))
    positions = list(bitget.get("positions") or [])
    return {
        "safe": live_orders == 0 and tested_orders == 0 and not positions,
        "status_ts": status.get("ts") or status.get("updated_at"),
        "decisions": _safe_int(heartbeats.get("decisions") or status.get("decision_count")),
        "live_orders": live_orders,
        "tested_orders": tested_orders,
        "bitget_positions": positions,
    }


def _outcome_stats(alpha_dir: Path, target_keys: list[str]) -> dict[str, dict[str, Any]]:
    payload = _read_json(alpha_dir / "external_alpha_outcomes.json")
    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in target_keys}
    for row in list(payload.get("outcomes") or []):
        key = f"{row.get('symbol')}|{row.get('strategy')}|{row.get('side')}"
        if key in grouped:
            grouped[key].append(row)
    stats: dict[str, dict[str, Any]] = {}
    for key, rows in grouped.items():
        values = [_safe_float(row.get("ret15_bps")) for row in rows if row.get("ret15_bps") is not None]
        stats[key] = {
            "count": len(values),
            "avg_ret15_bps": round(sum(values) / len(values), 6) if values else None,
            "win15_rate": round(sum(1 for value in values if value > 0.0) / len(values), 6) if values else None,
            "worst_ret15_bps": round(min(values), 6) if values else None,
            "latest_ret15_bps": round(values[-1], 6) if values else None,
            "recent5_ret15_bps": [round(value, 6) for value in values[-5:]],
        }
    return stats


def _candidate_counts(alpha_dir: Path, target_keys: list[str]) -> dict[str, int]:
    status = _read_json(alpha_dir / "status.json")
    counts = dict(status.get("candidate_counts") or {})
    return {key: _safe_int(counts.get(key)) for key in target_keys}


def _next_action(stats: dict[str, dict[str, Any]], *, target_sample: int) -> str:
    reached = [row for row in stats.values() if _safe_int(row.get("count")) >= target_sample]
    promotable = [
        row
        for row in reached
        if _safe_float(row.get("avg_ret15_bps")) >= 4.0
        and _safe_float(row.get("win15_rate")) >= 0.65
        and _safe_float(row.get("worst_ret15_bps"), -999.0) > -25.0
    ]
    if promotable:
        return "review_paper_candidate"
    if reached:
        return "target_sample_reached_but_not_promotable"
    return "collect_more_samples"


def run_cycle(
    *,
    cycle: int,
    decision_root: Path,
    alpha_dir: Path,
    output_dir: Path,
    target_keys: list[str],
    target_sample: int,
    timeout_seconds: int,
    insecure_ssl: bool,
) -> dict[str, Any]:
    py = sys.executable
    safety = _paper50_safety(decision_root)
    result: dict[str, Any] = {
        "cycle": cycle,
        "generated_at": datetime.now(UTC).isoformat(),
        "paper_only": True,
        "no_order_side_effects": True,
        "target_sample": target_sample,
        "target_keys": target_keys,
        "safety": safety,
        "commands": [],
    }
    if not safety["safe"]:
        result["action"] = "halt_safety_violation"
        return result

    result["commands"].append(
        _run(
            "external_alpha_refresh",
            [
                py,
                "scripts/quant_bitget_external_alpha_monitor.py",
                "--output-dir",
                str(alpha_dir),
                *(["--insecure-ssl"] if insecure_ssl else []),
            ],
            timeout_seconds=timeout_seconds,
        )
    )
    result["commands"].append(
        _run(
            "parallel_research_refresh",
            [
                py,
                "scripts/quant_paper50_parallel_research.py",
                "--decision-root",
                str(decision_root),
                "--alpha-dir",
                str(alpha_dir),
                "--output-dir",
                str(output_dir / "parallel_research"),
                "--latest-output",
                str(DEFAULT_PARALLEL_OUTPUT),
                "--max-workers",
                "6",
                "--command-timeout-seconds",
                str(timeout_seconds),
                *(["--insecure-ssl"] if insecure_ssl else []),
            ],
            timeout_seconds=max(timeout_seconds * 3, timeout_seconds + 30),
        )
    )
    stats = _outcome_stats(alpha_dir, target_keys)
    result["target_outcomes"] = stats
    result["candidate_counts"] = _candidate_counts(alpha_dir, target_keys)
    result["failed_commands"] = [row for row in result["commands"] if _safe_int(row.get("returncode")) != 0]
    result["action"] = "cycle_error" if result["failed_commands"] else _next_action(stats, target_sample=target_sample)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-root", default=str(DEFAULT_DECISION_ROOT))
    parser.add_argument("--alpha-dir", default=str(DEFAULT_ALPHA_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--status-path", default=str(DEFAULT_STATUS))
    parser.add_argument("--log-path", default=str(DEFAULT_LOG))
    parser.add_argument("--target-key", action="append", dest="target_keys")
    parser.add_argument("--target-sample", type=int, default=12)
    parser.add_argument("--duration-minutes", type=int, default=180)
    parser.add_argument("--interval-seconds", type=int, default=120)
    parser.add_argument("--command-timeout-seconds", type=int, default=120)
    parser.add_argument("--insecure-ssl", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    decision_root = Path(args.decision_root)
    alpha_dir = Path(args.alpha_dir)
    output_dir = Path(args.output_dir)
    status_path = Path(args.status_path)
    log_path = Path(args.log_path)
    target_keys = args.target_keys or list(DEFAULT_TARGET_KEYS)
    ends_at = datetime.now(UTC) + timedelta(minutes=max(args.duration_minutes, 1))
    output_dir.mkdir(parents=True, exist_ok=True)

    cycle = 0
    final: dict[str, Any] = {}
    while True:
        cycle += 1
        final = run_cycle(
            cycle=cycle,
            decision_root=decision_root,
            alpha_dir=alpha_dir,
            output_dir=output_dir,
            target_keys=target_keys,
            target_sample=max(args.target_sample, 1),
            timeout_seconds=max(args.command_timeout_seconds, 1),
            insecure_ssl=args.insecure_ssl,
        )
        final["ends_at"] = ends_at.isoformat()
        _write_json(status_path, final)
        _append_jsonl(log_path, final)
        print(json.dumps(final, ensure_ascii=False, sort_keys=True), flush=True)
        if args.once or final.get("action") in {"halt_safety_violation", "review_paper_candidate"}:
            break
        if datetime.now(UTC) >= ends_at:
            break
        remaining = max((ends_at - datetime.now(UTC)).total_seconds(), 0.0)
        time.sleep(min(max(args.interval_seconds, 1), remaining))

    final["completed_at"] = datetime.now(UTC).isoformat()
    _write_json(status_path, final)
    return 2 if final.get("action") == "halt_safety_violation" else 0


if __name__ == "__main__":
    raise SystemExit(main())
