#!/usr/bin/env python3
"""Build a paper-only long-failure short overlay candidate.

The overlay is intentionally conservative:
- it never places, tests, cancels, or modifies exchange orders;
- it only studies public external-alpha candidates/outcomes;
- it requires a same-symbol blocked long decision near the short alpha signal.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


FOCUS_LEGS = (
    "BTCUSDT|oi_exhaustion_reversion|short",
    "ETHUSDT|oi_exhaustion_reversion|short",
    "SOLUSDT|crowded_long_unwind|short",
)

LONG_BLOCK_REASONS = {
    "BUYING_INTO_RESISTANCE",
    "DIRECTION_CONFLICT",
    "EDGE_BELOW_COST",
    "EDGE_TOO_THIN",
    "FEE_EDGE_BUFFER_CONFIRMATION_REQUIRED",
    "POLICY_ALIGNMENT_CONFIRMATION_REQUIRED",
    "SYMBOL_PROFILE_EDGE_COST_TOO_THIN",
    "SYMBOL_PROFILE_EDGE_TOO_THIN",
    "SYMBOL_PROFILE_EXPECTED_PROFIT_TOO_SMALL",
    "SYMBOL_PROFILE_SCORE_TOO_LOW",
    "SYMBOL_PROFILE_VOLUME_TOO_WEAK",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _key(row: dict[str, Any]) -> str:
    return f"{row.get('symbol')}|{row.get('strategy')}|{row.get('side')}"


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _is_blocked_long(row: dict[str, Any]) -> bool:
    if str(row.get("final_mode") or "").lower() != "cash":
        return False
    if _safe_float(row.get("order_intent_notional_usd")) > 0.0:
        return False
    if int(_safe_float(row.get("trend_direction"), 0.0)) <= 0:
        return False
    if str(row.get("candidate_mode") or "").lower() not in {"futures", "spot"}:
        return False
    reasons = set(str(item) for item in row.get("rejection_reasons") or [])
    return bool(reasons.intersection(LONG_BLOCK_REASONS))


def load_blocked_longs(decision_roots: list[Path]) -> dict[str, list[dict[str, Any]]]:
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_paths: set[Path] = set()
    for root in decision_roots:
        paths = [root] if root.is_file() else list(root.rglob("decisions.jsonl"))
        for path in paths:
            resolved = path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            for row in _load_jsonl(path):
                timestamp = _parse_time(row.get("timestamp"))
                if timestamp is None or not _is_blocked_long(row):
                    continue
                copy = dict(row)
                copy["timestamp_dt"] = timestamp
                copy["source_decisions"] = str(path)
                by_symbol[str(row.get("symbol") or "").upper()].append(copy)
    for rows in by_symbol.values():
        rows.sort(key=lambda item: item["timestamp_dt"])
    return by_symbol


def load_external_outcomes(external_roots: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    for root in external_roots:
        paths = [root / "external_alpha_outcomes.json"] if root.is_dir() else [root]
        if root.is_dir() and not paths[0].exists():
            paths = list(root.rglob("external_alpha_outcomes.json"))
        for path in paths:
            resolved = path.resolve()
            if resolved in seen_paths or not path.exists():
                continue
            seen_paths.add(resolved)
            payload = _read_json(path)
            for row in payload.get("outcomes") or []:
                if not isinstance(row, dict):
                    continue
                timestamp = _parse_time(row.get("timestamp"))
                if timestamp is None:
                    continue
                copy = dict(row)
                copy["timestamp_dt"] = timestamp
                copy["source_outcomes"] = str(path)
                rows.append(copy)
    return sorted(rows, key=lambda item: item["timestamp_dt"])


def _nearest_blocked_long(
    rows: list[dict[str, Any]],
    timestamp: datetime,
    *,
    window: timedelta,
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_delta: timedelta | None = None
    for row in rows:
        delta = abs(row["timestamp_dt"] - timestamp)
        if delta <= window and (best_delta is None or delta < best_delta):
            best = row
            best_delta = delta
    return best


def build_overlay_report(
    *,
    decision_roots: list[Path],
    external_roots: list[Path],
    focus_legs: list[str],
    match_window_minutes: float,
) -> dict[str, Any]:
    blocked_longs = load_blocked_longs(decision_roots)
    outcomes = load_external_outcomes(external_roots)
    window = timedelta(minutes=match_window_minutes)
    matched: list[dict[str, Any]] = []
    blocked_counts = {symbol: len(rows) for symbol, rows in sorted(blocked_longs.items())}

    for outcome in outcomes:
        key = _key(outcome)
        if key not in focus_legs:
            continue
        symbol = str(outcome.get("symbol") or "").upper()
        blocked = _nearest_blocked_long(blocked_longs.get(symbol, []), outcome["timestamp_dt"], window=window)
        if blocked is None:
            continue
        matched.append(
            {
                "key": key,
                "symbol": symbol,
                "strategy": outcome.get("strategy"),
                "side": outcome.get("side"),
                "timestamp": outcome["timestamp_dt"].isoformat(),
                "ret5_bps": outcome.get("ret5_bps"),
                "ret10_bps": outcome.get("ret10_bps"),
                "ret15_bps": outcome.get("ret15_bps"),
                "score": outcome.get("score"),
                "reference_price": outcome.get("reference_price"),
                "blocked_long_timestamp": blocked["timestamp_dt"].isoformat(),
                "blocked_long_rejections": blocked.get("rejection_reasons") or [],
                "blocked_long_predictability_score": blocked.get("predictability_score"),
                "blocked_long_net_expected_edge_bps": blocked.get("net_expected_edge_bps"),
                "source_outcomes": outcome.get("source_outcomes"),
                "source_decisions": blocked.get("source_decisions"),
            }
        )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in matched:
        grouped[row["key"]].append(row)

    leg_stats: list[dict[str, Any]] = []
    for key in focus_legs:
        rows = grouped.get(key, [])
        values = [_safe_float(row.get("ret15_bps")) for row in rows]
        count = len(values)
        avg = sum(values) / count if values else None
        win = sum(1 for value in values if value > 0.0) / count if values else None
        worst = min(values) if values else None
        verdict = "reject_or_shadow_only"
        if count >= 2 and avg is not None and win is not None and worst is not None and avg >= 8.0 and win >= 0.75 and worst > -10.0:
            verdict = "paper_short_overlay_watch"
        elif count >= 1 and avg is not None and win is not None and avg > 0.0 and win >= 0.5:
            verdict = "shadow_watch"
        symbol, strategy, side = key.split("|")
        leg_stats.append(
            {
                "key": key,
                "symbol": symbol,
                "strategy": strategy,
                "side": side,
                "matched_count": count,
                "avg_ret15_bps": round(avg, 6) if avg is not None else None,
                "win15_rate": round(win, 6) if win is not None else None,
                "worst_ret15_bps": round(worst, 6) if worst is not None else None,
                "latest_ret15_bps": round(values[-1], 6) if values else None,
                "verdict": verdict,
            }
        )
    leg_stats.sort(
        key=lambda row: (
            {"paper_short_overlay_watch": 2, "shadow_watch": 1, "reject_or_shadow_only": 0}[row["verdict"]],
            _safe_float(row.get("avg_ret15_bps"), -999.0),
            int(row.get("matched_count") or 0),
        ),
        reverse=True,
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "paper_only": True,
        "live_ready": False,
        "match_window_minutes": match_window_minutes,
        "focus_legs": focus_legs,
        "blocked_long_counts": blocked_counts,
        "external_outcome_count": len(outcomes),
        "matched_outcome_count": len(matched),
        "leg_stats": leg_stats,
        "matched_outcomes": matched,
        "verdict": "paper_only_overlay_candidate" if any(row["verdict"] != "reject_or_shadow_only" for row in leg_stats) else "needs_more_matched_evidence",
    }


def build_candidate_config(base_config: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    config = dict(base_config)
    legs = []
    for row in report.get("leg_stats") or []:
        if row.get("verdict") == "reject_or_shadow_only":
            continue
        legs.append(
            {
                "symbol": row["symbol"],
                "strategy": row["strategy"],
                "side": row["side"],
                "trigger": "same_symbol_blocked_long_near_external_alpha",
                "match_window_minutes": report["match_window_minutes"],
                "paper_only": True,
                "matched_count": row["matched_count"],
                "avg_ret15_bps": row["avg_ret15_bps"],
                "win15_rate": row["win15_rate"],
                "worst_ret15_bps": row["worst_ret15_bps"],
                "verdict": row["verdict"],
            }
        )
    config["long_failure_short_overlay"] = {
        "enabled": bool(legs),
        "paper_only": True,
        "description": "When a same-symbol long candidate is blocked, record a paper-only short overlay if the focused external alpha confirms exhaustion/unwind.",
        "no_live_use_without_separate_approval": True,
        "no_order_side_effects": True,
        "conflict_policy": "do_not_open_short_if_long_is_active_or_accepted",
        "legs": legs,
    }
    overlay = dict(config.get("bitget_entry_overlay") or {})
    overlay.update(
        {
            "enabled": True,
            "paper_only": True,
            "long_failure_short_overlay_enabled": bool(legs),
            "long_failure_short_overlay_source": "quant_bitget_long_failure_short_overlay.py",
        }
    )
    config["bitget_entry_overlay"] = overlay
    return config


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Bitget Long-Failure Short Overlay",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "Paper-only. No live order, order test, cancel, or private order action is implied.",
        "",
        f"- Verdict: `{report['verdict']}`",
        f"- External mature outcomes scanned: `{report['external_outcome_count']}`",
        f"- Matched long-failure short outcomes: `{report['matched_outcome_count']}`",
        f"- Match window minutes: `{report['match_window_minutes']}`",
        "",
        "## Leg Stats",
        "",
    ]
    for row in report.get("leg_stats") or []:
        lines.append(
            f"- `{row['key']}`: matched `{row['matched_count']}`, avg15 `{row['avg_ret15_bps']}`, "
            f"win `{row['win15_rate']}`, worst `{row['worst_ret15_bps']}`, verdict `{row['verdict']}`"
        )
    lines.extend(["", "## Blocked Long Counts", ""])
    for symbol, count in sorted((report.get("blocked_long_counts") or {}).items()):
        lines.append(f"- `{symbol}`: `{count}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build paper-only long-failure short overlay candidate.")
    parser.add_argument("--decision-root", action="append", required=True)
    parser.add_argument("--external-root", action="append", required=True)
    parser.add_argument("--base-config", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--match-window-minutes", type=float, default=7.5)
    parser.add_argument("--focus-leg", action="append", dest="focus_legs")
    args = parser.parse_args()

    report = build_overlay_report(
        decision_roots=[Path(path) for path in args.decision_root],
        external_roots=[Path(path) for path in args.external_root],
        focus_legs=args.focus_legs or list(FOCUS_LEGS),
        match_window_minutes=args.match_window_minutes,
    )
    base_config = _read_json(Path(args.base_config))
    candidate_config = build_candidate_config(base_config, report)
    output_dir = Path(args.output_dir)
    _write_json(output_dir / "long_failure_short_overlay_report.json", report)
    _write_json(output_dir / "paper50_multi_symbol_filters.long_failure_short_overlay.json", candidate_config)
    (output_dir / "long_failure_short_overlay_report.md").write_text(_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "verdict": report["verdict"],
                "matched_outcome_count": report["matched_outcome_count"],
                "enabled_legs": candidate_config["long_failure_short_overlay"]["legs"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
