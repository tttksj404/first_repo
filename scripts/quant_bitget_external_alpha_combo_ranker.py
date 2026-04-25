#!/usr/bin/env python3
"""Rank Bitget external-alpha strategy combinations from shadow outcomes."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


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


def _summary_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [_safe_float(row.get("ret15_bps")) for row in rows]
    if not values:
        return {
            "count": 0,
            "avg_ret15_bps": 0.0,
            "win15_rate": 0.0,
            "worst_ret15_bps": None,
            "latest_ret15_bps": None,
            "recent5_ret15_bps": [],
        }
    return {
        "count": len(values),
        "avg_ret15_bps": round(sum(values) / len(values), 6),
        "win15_rate": round(sum(1 for value in values if value > 0.0) / len(values), 6),
        "worst_ret15_bps": round(min(values), 6),
        "latest_ret15_bps": round(values[-1], 6),
        "recent5_ret15_bps": [round(value, 6) for value in values[-5:]],
    }


def _verdict(stats: dict[str, Any]) -> str:
    count = int(stats["count"])
    avg = _safe_float(stats["avg_ret15_bps"])
    win = _safe_float(stats["win15_rate"])
    worst = _safe_float(stats["worst_ret15_bps"], 0.0)
    if count >= 10 and avg > 0.0 and win >= 0.55 and worst > -25.0:
        return "paper_promotable_after_more_runtime_checks"
    if count >= 2 and avg >= 8.0 and win >= 0.75 and worst > -10.0:
        return "strong_watch"
    if count >= 1 and avg > 0.0 and win >= 0.5:
        return "watch"
    return "reject_or_shadow_only"


def rank_combinations(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in outcomes:
        key = f"{row.get('symbol')}|{row.get('strategy')}|{row.get('side')}"
        grouped[key].append(row)
        by_symbol[str(row.get("symbol"))].append(row)

    strategy_rows: list[dict[str, Any]] = []
    for key, rows in sorted(grouped.items()):
        symbol, strategy, side = key.split("|")
        stats = _summary_stats(rows)
        strategy_rows.append(
            {
                "key": key,
                "symbol": symbol,
                "strategy": strategy,
                "side": side,
                "verdict": _verdict(stats),
                **stats,
            }
        )
    strategy_rows.sort(
        key=lambda row: (
            {"paper_promotable_after_more_runtime_checks": 4, "strong_watch": 3, "watch": 2, "reject_or_shadow_only": 1}[row["verdict"]],
            row["avg_ret15_bps"],
            row["win15_rate"],
            row["count"],
        ),
        reverse=True,
    )

    per_symbol: dict[str, Any] = {}
    for symbol in sorted(by_symbol):
        rows = [row for row in strategy_rows if row["symbol"] == symbol]
        per_symbol[symbol] = {
            "best": rows[0] if rows else None,
            "runners_up": rows[1:4],
        }

    strong = [row for row in strategy_rows if row["verdict"] == "strong_watch"]
    watch = [row for row in strategy_rows if row["verdict"] == "watch"]
    reversion = [
        row
        for row in strategy_rows
        if row["strategy"] == "oi_exhaustion_reversion" and row["side"] == "short" and row["verdict"] in {"strong_watch", "watch"}
    ]
    breakout = [
        row
        for row in strategy_rows
        if "breakout" in row["strategy"] and row["verdict"] in {"strong_watch", "watch"}
    ]

    def combo_stats(name: str, legs: list[dict[str, Any]]) -> dict[str, Any]:
        if not legs:
            return {"name": name, "legs": [], "leg_count": 0, "avg_leg_ret15_bps": None, "min_leg_win15_rate": None, "status": "empty"}
        avg = sum(_safe_float(row["avg_ret15_bps"]) for row in legs) / len(legs)
        min_win = min(_safe_float(row["win15_rate"]) for row in legs)
        min_count = min(int(row["count"]) for row in legs)
        worst = min(_safe_float(row["worst_ret15_bps"], 0.0) for row in legs)
        status = "shadow_only"
        if len(legs) >= 2 and avg >= 12.0 and min_win >= 0.75 and min_count >= 2 and worst > -10.0:
            status = "best_current_combo"
        elif avg > 0.0:
            status = "watch"
        return {
            "name": name,
            "leg_count": len(legs),
            "legs": legs,
            "avg_leg_ret15_bps": round(avg, 6),
            "min_leg_win15_rate": round(min_win, 6),
            "min_leg_count": min_count,
            "worst_leg_ret15_bps": round(worst, 6),
            "status": status,
        }

    combos = [
        combo_stats("core_oi_exhaustion_reversion_shorts", reversion[:4]),
        combo_stats("all_strong_watch", strong),
        combo_stats("breakout_watch", breakout),
        combo_stats("broad_watch_basket", strong + watch[: max(0, 6 - len(strong))]),
    ]
    combos.sort(
        key=lambda row: (
            {"best_current_combo": 3, "watch": 2, "shadow_only": 1, "empty": 0}[row["status"]],
            _safe_float(row.get("avg_leg_ret15_bps"), -999.0),
            int(row.get("leg_count") or 0),
        ),
        reverse=True,
    )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mature_outcome_count": len(outcomes),
        "strategy_rankings": strategy_rows,
        "per_symbol": per_symbol,
        "combos": combos,
        "best_combo": combos[0] if combos else None,
        "live_ready": False,
        "live_ready_reason": "All results are paper-only shadow outcomes and sample sizes are below live promotion thresholds.",
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Bitget External Alpha Combo Ranking",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "This is paper-only. No live order, order test, cancel, or private order action is implied.",
        "",
        "## Best Combo",
        "",
    ]
    combo = report.get("best_combo") or {}
    lines.append(f"- Name: `{combo.get('name')}`")
    lines.append(f"- Status: `{combo.get('status')}`")
    lines.append(f"- Avg leg ret15 bps: `{combo.get('avg_leg_ret15_bps')}`")
    lines.append(f"- Min win15 rate: `{combo.get('min_leg_win15_rate')}`")
    lines.append("")
    lines.append("## Legs")
    lines.append("")
    for leg in combo.get("legs") or []:
        lines.append(
            f"- `{leg['symbol']}` `{leg['strategy']}` `{leg['side']}`: "
            f"count `{leg['count']}`, avg15 `{leg['avg_ret15_bps']}`, win `{leg['win15_rate']}`, verdict `{leg['verdict']}`"
        )
    lines.append("")
    lines.append("## Per Symbol Best")
    lines.append("")
    for symbol, item in sorted((report.get("per_symbol") or {}).items()):
        best = item.get("best") or {}
        lines.append(
            f"- `{symbol}`: `{best.get('strategy')}` `{best.get('side')}`, "
            f"count `{best.get('count')}`, avg15 `{best.get('avg_ret15_bps')}`, "
            f"win `{best.get('win15_rate')}`, verdict `{best.get('verdict')}`"
        )
    lines.append("")
    lines.append("## Live Readiness")
    lines.append("")
    lines.append(f"- Live ready: `{report.get('live_ready')}`")
    lines.append(f"- Reason: {report.get('live_ready_reason')}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank external-alpha strategy combos.")
    parser.add_argument("--external-alpha-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    base = Path(args.external_alpha_dir)
    payload = _read_json(base / "external_alpha_outcomes.json")
    outcomes = list(payload.get("outcomes") or [])
    report = rank_combinations(outcomes)
    output_dir = Path(args.output_dir)
    _write_json(output_dir / "external_alpha_combo_ranking.json", report)
    (output_dir / "external_alpha_combo_ranking.md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir), "best_combo": report.get("best_combo")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
