#!/usr/bin/env python3
"""Run a bounded parallel paper-only research sweep for paper50.

The sweep fans out the safe research surfaces that can be evaluated from local
paper logs and public market data, then writes one ranked summary. It never
places, tests, cancels, or modifies exchange orders.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DECISION_ROOT = ROOT / "quant_runtime_paper50"
DEFAULT_ALPHA_DIR = DEFAULT_DECISION_ROOT / "bitget_external_alpha_shadow"
DEFAULT_FILTERS = DEFAULT_DECISION_ROOT / "paper50_multi_symbol_filters.json"
DEFAULT_OUTPUT_DIR = DEFAULT_DECISION_ROOT / "artifacts" / "parallel_research"
DEFAULT_LATEST = DEFAULT_DECISION_ROOT / "artifacts" / "paper50_parallel_research_latest.json"


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
            "stdout_tail": proc.stdout[-3000:],
            "stderr_tail": proc.stderr[-3000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "args": args,
            "returncode": 124,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "stdout_tail": (exc.stdout or "")[-3000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-3000:] if isinstance(exc.stderr, str) else "",
            "timed_out": True,
            "timeout_seconds": timeout_seconds,
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


def _latest_cycle_dir(alpha_dir: Path) -> Path | None:
    cycles = [path for path in alpha_dir.glob("cycle_*") if path.is_dir()]
    if not cycles:
        return None
    return max(cycles, key=lambda path: path.name)


def _parallel(commands: list[tuple[str, list[str]]], *, max_workers: int, timeout_seconds: int) -> list[dict[str, Any]]:
    if not commands:
        return []
    workers = max(1, min(max_workers, len(commands)))
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_run, name, args, timeout_seconds=timeout_seconds) for name, args in commands]
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda row: str(row.get("name") or ""))


def _top_external_alpha(alpha_dir: Path) -> list[dict[str, Any]]:
    status = _read_json(alpha_dir / "status.json")
    rows = list(status.get("best_mature_candidates") or [])
    return [
        {
            "id": row.get("key"),
            "symbol": str(row.get("key") or "").split("|")[0],
            "source": "external_alpha",
            "action": "watch" if _safe_float(row.get("avg_ret15_bps")) > 0 else "hold",
            "score": round(
                _safe_float(row.get("avg_ret15_bps"))
                + (_safe_float(row.get("win15_rate")) * 10.0)
                + min(_safe_int(row.get("count")), 12) * 0.4
                + min(_safe_float(row.get("latest_ret15_bps")), 25.0) * 0.2,
                6,
            ),
            "metrics": row,
        }
        for row in rows[:12]
    ]


def _top_combo(output_dir: Path) -> list[dict[str, Any]]:
    combo = dict(_read_json(output_dir / "external_alpha_combo" / "external_alpha_combo_ranking.json").get("best_combo") or {})
    if not combo:
        return []
    status_score = {"best_current_combo": 35.0, "watch": 20.0, "shadow_only": 5.0, "empty": 0.0}
    return [
        {
            "id": f"combo:{combo.get('name')}",
            "source": "external_alpha_combo",
            "action": "watch" if combo.get("status") in {"best_current_combo", "watch"} else "hold",
            "score": round(status_score.get(str(combo.get("status")), 0.0) + _safe_float(combo.get("avg_leg_ret15_bps")), 6),
            "metrics": combo,
        }
    ]


def _forced_pilot(decision_root: Path) -> list[dict[str, Any]]:
    forced = _read_json(decision_root / "artifacts" / "paper50_forced_pilot_latest.json")
    summary = dict(forced.get("summary") or {})
    active = list(forced.get("active_pilots") or [])
    completed = list(forced.get("completed_recent") or [])
    avg = _safe_float(summary.get("avg_net_bps"))
    action = str(summary.get("action") or "keep_collecting")
    if action == "review_small_live_pilot_candidate":
        verdict = "paper_candidate"
        score = 80.0 + avg
    elif completed or active:
        verdict = "watch" if avg > 0 else "hold"
        score = 25.0 + avg
    else:
        verdict = "hold"
        score = 0.0
    return [
        {
            "id": "forced_pilot:block_override_quality",
            "source": "forced_pilot",
            "action": verdict,
            "score": round(score, 6),
            "metrics": {
                "summary": summary,
                "active_head": active[0] if active else None,
                "completed_head": completed[0] if completed else None,
            },
        }
    ]


def _major_5m(decision_root: Path) -> list[dict[str, Any]]:
    payload = _read_json(decision_root / "artifacts" / "major_5m_leverage_research_latest.json")
    rows = []
    for row in list(payload.get("top_profiles") or [])[:8]:
        action = "watch" if row.get("decision") == "paper_watch" else "hold"
        penalty = 8.0 if row.get("five_pct_pain_count") else 0.0
        rows.append(
            {
                "id": f"major_5m:{row.get('id')}",
                "source": "major_5m_leverage",
                "action": action,
                "score": round(_safe_float(row.get("avg_net_bps")) + (_safe_float(row.get("win_rate")) * 12.0) - penalty, 6),
                "metrics": row,
            }
        )
    return rows


def _high_upside_overlay(decision_root: Path) -> list[dict[str, Any]]:
    payload = _read_json(decision_root / "artifacts" / "paper50_high_upside_overlay_latest.json")
    rows = []
    action_priority = {
        "paper_high_upside_candidate": "paper_candidate",
        "paper_watch": "watch",
        "lottery_watch_only": "watch",
        "watch_or_reject": "hold",
    }
    for row in list(payload.get("top_profiles") or [])[:8]:
        high_score = _safe_float(row.get("high_upside_score"))
        roe_bonus = min(max(_safe_float(row.get("p90_roe_bps")), 0.0), 500.0) / 20.0
        tail_penalty = min(abs(min(_safe_float(row.get("worst_roe_bps")), 0.0)), 500.0) / 50.0
        rows.append(
            {
                "id": f"high_upside:{row.get('id')}",
                "source": "high_upside_overlay",
                "action": action_priority.get(str(row.get("action")), "hold"),
                "score": round(high_score + roe_bonus - tail_penalty, 6),
                "metrics": row,
                "blockers": list(row.get("blockers") or []),
            }
        )
    return rows


def _promotion_candidates(decision_root: Path) -> list[dict[str, Any]]:
    payload = _read_json(decision_root / "artifacts" / "paper50_promotion_checklist_latest.json")
    priority = {
        "paper_candidate": 60.0,
        "paper_tune_candidate": 50.0,
        "watch_only": 25.0,
        "post_tune_watch": 20.0,
        "hold": 0.0,
    }
    rows = []
    for row in list(payload.get("candidates") or [])[:20]:
        metrics = dict(row.get("metrics") or {})
        rows.append(
            {
                "id": row.get("id"),
                "source": row.get("source"),
                "action": row.get("action"),
                "score": round(
                    priority.get(str(row.get("action")), 0.0)
                    + _safe_float(metrics.get("avg_ret15_bps"))
                    + _safe_float(metrics.get("avg_net_bps")),
                    6,
                ),
                "metrics": metrics,
                "blockers": list(row.get("blockers") or []),
            }
        )
    return rows


def build_summary(*, decision_root: Path, alpha_dir: Path, output_dir: Path, commands: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = []
    candidates.extend(_top_external_alpha(alpha_dir))
    candidates.extend(_top_combo(output_dir))
    candidates.extend(_forced_pilot(decision_root))
    candidates.extend(_major_5m(decision_root))
    candidates.extend(_high_upside_overlay(decision_root))
    candidates.extend(_promotion_candidates(decision_root))
    candidates.sort(key=lambda row: (_safe_float(row.get("score")), str(row.get("action") or "")), reverse=True)

    failed = [row for row in commands if int(row.get("returncode") or 0) != 0]
    best = candidates[0] if candidates else None
    if failed:
        overall = "research_partial_failure"
    elif best and best.get("action") in {"paper_candidate", "paper_tune_candidate"}:
        overall = "review_top_paper_candidate"
    elif any(row.get("action") in {"watch", "watch_only", "post_tune_watch"} for row in candidates):
        overall = "continue_parallel_observation"
    else:
        overall = "hold_all_candidates"

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "paper50_parallel_research",
        "paper_only": True,
        "no_order_side_effects": True,
        "overall_action": overall,
        "safety": _paper50_safety(decision_root),
        "command_count": len(commands),
        "failed_commands": failed,
        "top_candidates": candidates[:20],
        "artifacts": {
            "output_dir": str(output_dir),
            "latest": str(DEFAULT_LATEST),
            "promotion_checklist": str(decision_root / "artifacts" / "paper50_promotion_checklist_latest.json"),
            "forced_pilot": str(decision_root / "artifacts" / "paper50_forced_pilot_latest.json"),
            "major_5m": str(decision_root / "artifacts" / "major_5m_leverage_research_latest.json"),
            "high_upside_overlay": str(decision_root / "artifacts" / "paper50_high_upside_overlay_latest.json"),
        },
    }


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Paper50 Parallel Research",
        "",
        f"Generated: {payload['generated_at']}",
        f"Overall action: `{payload['overall_action']}`",
        f"Safety: `{'safe' if dict(payload.get('safety') or {}).get('safe') else 'blocked'}`",
        "",
        "Paper-only. No live orders, test orders, cancels, or position changes.",
        "",
        "## Top Candidates",
        "",
    ]
    for row in list(payload.get("top_candidates") or [])[:12]:
        blockers = ", ".join(row.get("blockers") or []) or "none"
        lines.append(
            f"- `{row.get('action')}` score `{row.get('score')}` `{row.get('id')}` "
            f"source `{row.get('source')}` blockers `{blockers}`"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision-root", default=str(DEFAULT_DECISION_ROOT))
    parser.add_argument("--alpha-dir", default=str(DEFAULT_ALPHA_DIR))
    parser.add_argument("--filters", default=str(DEFAULT_FILTERS))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--latest-output", default=str(DEFAULT_LATEST))
    parser.add_argument("--max-workers", type=int, default=6)
    parser.add_argument("--command-timeout-seconds", type=int, default=180)
    parser.add_argument("--insecure-ssl", action="store_true")
    args = parser.parse_args()

    decision_root = Path(args.decision_root)
    alpha_dir = Path(args.alpha_dir)
    filters = Path(args.filters)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    safety = _paper50_safety(decision_root)
    if not safety["safe"]:
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "mode": "paper50_parallel_research",
            "paper_only": True,
            "no_order_side_effects": True,
            "overall_action": "halt_safety_violation",
            "safety": safety,
            "top_candidates": [],
            "failed_commands": [],
        }
        _write_json(Path(args.latest_output), payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2

    py = sys.executable
    decisions = decision_root / "forensics" / "decisions.jsonl"
    current_cycle = _latest_cycle_dir(alpha_dir)
    stage1 = [
        (
            "counterfactual",
            [
                py,
                "scripts/quant_paper50_counterfactual.py",
                "--output-base",
                str(decision_root),
                "--write-latest",
                "--per-symbol-limit",
                "12",
                "--min-age-minutes",
                "16",
            ],
        ),
        (
            "futures_signal_outcomes",
            [py, "scripts/quant_paper50_futures_signal_outcomes.py", "--decisions-path", str(decisions)],
        ),
        (
            "forced_pilot",
            [
                py,
                "scripts/quant_paper50_forced_pilot.py",
                "--decisions-path",
                str(decisions),
                "--open-new",
                "--max-active",
                "1",
            ],
        ),
        (
            "major_5m",
            [
                py,
                "scripts/quant_major_5m_leverage_research.py",
                "--output",
                str(decision_root / "artifacts" / "major_5m_leverage_research_latest.json"),
            ],
        ),
        (
            "external_alpha_combo",
            [
                py,
                "scripts/quant_bitget_external_alpha_combo_ranker.py",
                "--external-alpha-dir",
                str(alpha_dir),
                "--output-dir",
                str(output_dir / "external_alpha_combo"),
            ],
        ),
        (
            "focused_combo",
            [
                py,
                "scripts/quant_bitget_focused_combo_ranker.py",
                "--base-dir",
                str(alpha_dir),
                *(["--current-run-dir", str(current_cycle)] if current_cycle else []),
                "--output-dir",
                str(output_dir / "focused_combo"),
            ],
        ),
        (
            "overlay_tuner",
            [
                py,
                "scripts/quant_bitget_overlay_tuner.py",
                "--filters",
                str(filters),
                "--counterfactual",
                str(decision_root / "artifacts" / "paper50_counterfactual_latest.json"),
                "--output-dir",
                str(output_dir / "overlay_tuning"),
                "--iterations",
                "1",
                *(["--insecure-ssl"] if args.insecure_ssl else []),
            ],
        ),
        (
            "filter_guard_dry_run",
            [
                py,
                "scripts/quant_paper50_filter_guard.py",
                "--filters",
                str(filters),
                "--counterfactual",
                str(decision_root / "artifacts" / "paper50_counterfactual_latest.json"),
                "--state",
                str(decision_root / "artifacts" / "paper50_filter_guard_state.json"),
                "--audit",
                str(decision_root / "artifacts" / "paper50_filter_guard_audit.jsonl"),
            ],
        ),
        (
            "block_reason_validation",
            [
                py,
                "scripts/quant_paper50_block_reason_validation.py",
                "--decisions-path",
                str(decisions),
                "--max-evaluated",
                "60",
            ],
        ),
    ]
    results = _parallel(stage1, max_workers=args.max_workers, timeout_seconds=args.command_timeout_seconds)

    high_probability_output = output_dir / "high_probability" / "high_probability_summary.json"
    stage2 = [
        ("side_scorecard", [py, "scripts/quant_paper50_side_scorecard.py"]),
        (
            "post_tune_feedback",
            [
                py,
                "scripts/quant_paper50_post_tune_feedback.py",
                "--filters",
                str(filters),
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
        ),
        (
            "market_regime",
            [
                py,
                "scripts/quant_paper50_market_regime.py",
                "--output",
                str(decision_root / "artifacts" / "paper50_market_regime_latest.json"),
            ],
        ),
        (
            "high_probability",
            [
                py,
                "scripts/quant_bitget_high_probability_monitor.py",
                "--decisions",
                str(decisions),
                "--overlay",
                str(alpha_dir / "long_failure_overlay_check" / "long_failure_short_overlay_report.json"),
                "--output",
                str(high_probability_output),
            ],
        ),
        (
            "high_upside_overlay",
            [
                py,
                "scripts/quant_paper50_high_upside_overlay.py",
                "--alpha-outcomes",
                str(alpha_dir / "external_alpha_outcomes.json"),
                "--monitor-status",
                str(decision_root / "_monitor_status.json"),
                "--output",
                str(decision_root / "artifacts" / "paper50_high_upside_overlay_latest.json"),
                "--min-sample",
                "40",
                "--cost-bps",
                "8",
                "--leverage",
                "3",
                "--leverage",
                "5",
                "--leverage",
                "10",
            ],
        ),
    ]
    results.extend(_parallel(stage2, max_workers=min(args.max_workers, 4), timeout_seconds=args.command_timeout_seconds))

    stage3 = [
        (
            "outcome_feedback",
            [
                py,
                "scripts/quant_bitget_outcome_feedback.py",
                "--decisions",
                str(decisions),
                "--gate-summary",
                str(high_probability_output),
                "--base-config",
                str(filters),
                "--output-dir",
                str(output_dir / "outcome_feedback"),
                "--max-decisions",
                "180",
                *(["--insecure-ssl"] if args.insecure_ssl else []),
            ],
        ),
        (
            "promotion_checklist",
            [
                py,
                "scripts/quant_paper50_promotion_checklist.py",
                "--alpha-status",
                str(alpha_dir / "status.json"),
                "--overlay-report",
                str(alpha_dir / "long_failure_overlay_check" / "long_failure_short_overlay_report.json"),
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
        ),
    ]
    results.extend(_parallel(stage3, max_workers=2, timeout_seconds=args.command_timeout_seconds))

    payload = build_summary(decision_root=decision_root, alpha_dir=alpha_dir, output_dir=output_dir, commands=results)
    _write_json(Path(args.latest_output), payload)
    _write_json(output_dir / "parallel_research_report.json", payload)
    (output_dir / "parallel_research_report.md").write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 1 if payload["failed_commands"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
