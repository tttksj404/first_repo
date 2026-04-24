#!/usr/bin/env python3
"""Rank focused Bitget external-alpha combo legs across paper-only runs."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_FOCUS_LEGS = (
    "BTCUSDT|oi_exhaustion_reversion|short",
    "ETHUSDT|oi_exhaustion_reversion|short",
    "SOLUSDT|crowded_long_unwind|short",
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _outcome_key(row: dict[str, Any]) -> str:
    return f"{row.get('symbol')}|{row.get('strategy')}|{row.get('side')}"


def _load_outcomes(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "external_alpha_outcomes.json"
    if not path.exists():
        return []
    payload = _read_json(path)
    rows = payload.get("outcomes") or []
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        copy = dict(row)
        copy["source_run"] = run_dir.name
        out.append(copy)
    return out


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sorted(rows, key=lambda row: str(row.get("timestamp") or ""))
    values = [_safe_float(row.get("ret15_bps")) for row in rows]
    if not values:
        return {
            "count": 0,
            "avg_ret15_bps": None,
            "win15_rate": None,
            "worst_ret15_bps": None,
            "latest_ret15_bps": None,
            "recent5_ret15_bps": [],
            "score": -999.0,
        }
    count = len(values)
    avg = sum(values) / count
    win = sum(1 for value in values if value > 0.0) / count
    worst = min(values)
    recent5 = values[-5:]
    score = avg * min(1.0, math.sqrt(count / 5.0)) + (win - 0.5) * 10.0 + min(0.0, worst) * 0.15
    return {
        "count": count,
        "avg_ret15_bps": round(avg, 6),
        "win15_rate": round(win, 6),
        "worst_ret15_bps": round(worst, 6),
        "latest_ret15_bps": round(values[-1], 6),
        "recent5_ret15_bps": [round(value, 6) for value in recent5],
        "score": round(score, 6),
    }


def _verdict(stats: dict[str, Any]) -> str:
    count = int(stats.get("count") or 0)
    avg = _safe_float(stats.get("avg_ret15_bps"))
    win = _safe_float(stats.get("win15_rate"))
    worst = _safe_float(stats.get("worst_ret15_bps"), 0.0)
    if count >= 10 and avg > 4.0 and win >= 0.58 and worst > -20.0:
        return "paper_promotable_after_more_runtime_checks"
    if count >= 2 and avg >= 8.0 and win >= 0.75 and worst > -10.0:
        return "strong_watch"
    if count >= 1 and avg > 0.0 and win >= 0.5:
        return "watch"
    return "reject_or_shadow_only"


def build_report(base_dir: Path, current_run_dir: Path | None, focus_legs: list[str]) -> dict[str, Any]:
    run_dirs = [
        path
        for path in sorted(base_dir.iterdir())
        if path.is_dir() and (path.name.startswith("external_alpha_shadow") or path.name.startswith("external_alpha_focused_combo"))
    ]
    all_rows: list[dict[str, Any]] = []
    current_rows: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        rows = _load_outcomes(run_dir)
        all_rows.extend(rows)
        if current_run_dir and run_dir.resolve() == current_run_dir.resolve():
            current_rows.extend(rows)

    def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            key = _outcome_key(row)
            if key in focus_legs:
                grouped[key].append(row)
        ranked = []
        for key in focus_legs:
            symbol, strategy, side = key.split("|")
            stats = _stats(grouped.get(key, []))
            ranked.append(
                {
                    "key": key,
                    "symbol": symbol,
                    "strategy": strategy,
                    "side": side,
                    "verdict": _verdict(stats),
                    "source_runs": sorted({str(row.get("source_run")) for row in grouped.get(key, [])}),
                    **stats,
                }
            )
        ranked.sort(key=lambda row: (_safe_float(row.get("score"), -999.0), int(row.get("count") or 0)), reverse=True)
        return ranked

    cumulative = summarize(all_rows)
    current = summarize(current_rows)
    best = cumulative[0] if cumulative else None
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "paper_only": True,
        "live_ready": False,
        "live_ready_reason": "Focused combo evidence is paper-only and still below live promotion requirements.",
        "base_dir": str(base_dir),
        "current_run_dir": str(current_run_dir) if current_run_dir else None,
        "focus_legs": focus_legs,
        "total_external_outcomes": len(all_rows),
        "current_run_outcomes": len(current_rows),
        "best_cumulative_leg": best,
        "cumulative_focus_rankings": cumulative,
        "current_run_focus_rankings": current,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Bitget Focused Combo Ranking",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "Paper-only. No live order, order test, cancel, or private order action is implied.",
        "",
        "## Best Cumulative Leg",
        "",
    ]
    best = report.get("best_cumulative_leg") or {}
    lines.append(
        f"- `{best.get('key')}`: count `{best.get('count')}`, avg15 `{best.get('avg_ret15_bps')}`, "
        f"win `{best.get('win15_rate')}`, worst `{best.get('worst_ret15_bps')}`, verdict `{best.get('verdict')}`"
    )
    lines.extend(["", "## Cumulative Focus Rankings", ""])
    for row in report.get("cumulative_focus_rankings") or []:
        lines.append(
            f"- `{row['key']}`: count `{row['count']}`, avg15 `{row['avg_ret15_bps']}`, "
            f"win `{row['win15_rate']}`, worst `{row['worst_ret15_bps']}`, latest `{row['latest_ret15_bps']}`, "
            f"verdict `{row['verdict']}`"
        )
    lines.extend(["", "## Current Run Focus Rankings", ""])
    for row in report.get("current_run_focus_rankings") or []:
        lines.append(
            f"- `{row['key']}`: count `{row['count']}`, avg15 `{row['avg_ret15_bps']}`, "
            f"win `{row['win15_rate']}`, worst `{row['worst_ret15_bps']}`, latest `{row['latest_ret15_bps']}`, "
            f"verdict `{row['verdict']}`"
        )
    lines.extend(["", "## Live Readiness", ""])
    lines.append(f"- Live ready: `{report.get('live_ready')}`")
    lines.append(f"- Reason: {report.get('live_ready_reason')}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank focused external-alpha combo legs across paper-only runs.")
    parser.add_argument("--base-dir", required=True)
    parser.add_argument("--current-run-dir")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--focus-leg", action="append", dest="focus_legs")
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    current_run_dir = Path(args.current_run_dir) if args.current_run_dir else None
    focus_legs = args.focus_legs or list(DEFAULT_FOCUS_LEGS)
    report = build_report(base_dir, current_run_dir, focus_legs)
    output_dir = Path(args.output_dir)
    _write_json(output_dir / "focused_combo_ranking.json", report)
    (output_dir / "focused_combo_ranking.md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir), "best_cumulative_leg": report["best_cumulative_leg"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
