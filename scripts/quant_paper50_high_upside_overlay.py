#!/usr/bin/env python3
"""Paper-only high-upside overlay research for focused crypto candidates.

The report ranks focused external-alpha legs by upside-tail quality under
small leveraged "sleeve" profiles. It only reads local paper/public-data
artifacts and never places, tests, cancels, or modifies exchange orders.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_ALPHA_OUTCOMES = Path("quant_runtime_paper50/bitget_external_alpha_shadow/external_alpha_outcomes.json")
DEFAULT_MONITOR_STATUS = Path("quant_runtime_paper50/_monitor_status.json")
DEFAULT_OUTPUT = Path("quant_runtime_paper50/artifacts/paper50_high_upside_overlay_latest.json")
DEFAULT_FOCUS_KEYS = (
    "DOGEUSDT|oi_exhaustion_reversion|short",
    "DOGEUSDT|flow_momentum|long",
    "PEPEUSDT|oi_exhaustion_reversion|short",
)
DEFAULT_LEVERAGES = (3, 5, 10)
ROUND_TRIP_COST_BPS = 8.0
NEAR_MISS_SHORT_STRATEGIES = {
    "crowded_long_unwind",
    "flow_momentum",
    "oi_momentum_breakout",
    "oi_price_fallback_momentum",
}
EXHAUSTION_FAMILY_SHORT_STRATEGIES = {
    "crowded_long_unwind",
    "oi_exhaustion_reversion",
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


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


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 6)
    rank = (len(ordered) - 1) * max(0.0, min(pct, 100.0)) / 100.0
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return round(ordered[lower], 6)
    weight = rank - lower
    return round((ordered[lower] * (1.0 - weight)) + (ordered[upper] * weight), 6)


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 6) if values else None


def _key(row: dict[str, Any]) -> str:
    return f"{row.get('symbol')}|{row.get('strategy')}|{row.get('side')}"


def _paper50_safety(status_path: Path) -> dict[str, Any]:
    status = _read_json(status_path)
    heartbeats = dict(status.get("heartbeats") or {})
    bitget = dict(status.get("bitget") or {})
    live_orders = _safe_int(heartbeats.get("live_orders") or status.get("live_order_count"))
    tested_orders = _safe_int(heartbeats.get("tested_orders") or status.get("tested_order_count"))
    positions = list(bitget.get("positions") or [])
    return {
        "safe": live_orders == 0 and not positions,
        "status_ts": status.get("ts") or status.get("updated_at"),
        "decisions": _safe_int(heartbeats.get("decisions") or status.get("decision_count")),
        "live_orders": live_orders,
        "tested_orders": tested_orders,
        "bitget_positions": positions,
    }


def _rows_for_key(outcomes: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return [row for row in outcomes if _key(row) == key and row.get("ret15_bps") is not None]


def _net_returns(rows: list[dict[str, Any]], *, cost_bps: float) -> dict[str, list[float]]:
    horizons: dict[str, list[float]] = {"5m": [], "10m": [], "15m": [], "fast": [], "runner": []}
    for row in rows:
        ret5 = _safe_float(row.get("ret5_bps")) - cost_bps
        ret10 = _safe_float(row.get("ret10_bps")) - cost_bps
        ret15 = _safe_float(row.get("ret15_bps")) - cost_bps
        horizons["5m"].append(ret5)
        horizons["10m"].append(ret10)
        horizons["15m"].append(ret15)
        horizons["fast"].append(max(ret5, ret10))
        # Approximate a runner sleeve with the best available hold among 10m/15m,
        # while still charging the same round-trip cost.
        horizons["runner"].append(max(ret10, ret15))
    return horizons


def _summarize_returns(values: list[float]) -> dict[str, Any]:
    wins = [value for value in values if value > 0.0]
    losses = [value for value in values if value <= 0.0]
    return {
        "count": len(values),
        "avg_net_bps": _avg(values),
        "median_net_bps": _median(values),
        "win_rate": round(len(wins) / len(values), 6) if values else None,
        "loss_rate": round(len(losses) / len(values), 6) if values else None,
        "p75_net_bps": _percentile(values, 75),
        "p90_net_bps": _percentile(values, 90),
        "p95_net_bps": _percentile(values, 95),
        "worst_net_bps": round(min(values), 6) if values else None,
        "best_net_bps": round(max(values), 6) if values else None,
        "recent5_net_bps": [round(value, 6) for value in values[-5:]],
    }


def _profile_decision(
    *,
    count: int,
    avg_net_bps: float,
    win_rate: float,
    p90_net_bps: float,
    worst_net_bps: float,
    high_upside_score: float,
    leverage: int,
    min_sample: int,
) -> tuple[str, list[str]]:
    blockers: list[str] = []
    if count < min_sample:
        blockers.append("sample_lt_min")
    if avg_net_bps <= 0.0:
        blockers.append("avg_net_lte_0")
    if win_rate < 0.55:
        blockers.append("win_rate_lt_55pct")
    if p90_net_bps < 12.0:
        blockers.append("p90_upside_lt_12bps")
    if worst_net_bps <= -35.0:
        blockers.append("worst_tail_lte_-35bps")
    if leverage >= 10 and worst_net_bps <= -20.0:
        blockers.append("ten_x_tail_too_wide")
    if high_upside_score < 10.0:
        blockers.append("high_upside_score_lt_10")

    if blockers:
        if count < min_sample and high_upside_score >= 18.0 and worst_net_bps > -25.0:
            return "lottery_watch_only", blockers
        return "watch_or_reject", blockers
    if leverage >= 5 and high_upside_score >= 18.0 and p90_net_bps >= 18.0:
        return "paper_high_upside_candidate", blockers
    return "paper_watch", blockers


def _profile_for_leg(
    *,
    key: str,
    rows: list[dict[str, Any]],
    leverage: int,
    cost_bps: float,
    min_sample: int,
    tier: str = "A",
    profile_type: str = "exact",
    primary_horizon: str = "15m",
) -> dict[str, Any]:
    horizons = _net_returns(rows, cost_bps=cost_bps)
    fifteen = _summarize_returns(horizons["15m"])
    primary_key = primary_horizon if primary_horizon in horizons else "15m"
    primary = _summarize_returns(horizons[primary_key])
    runner = _summarize_returns(horizons["runner"])
    count = _safe_int(primary["count"])
    avg = _safe_float(primary["avg_net_bps"])
    win_rate = _safe_float(primary["win_rate"])
    p90 = _safe_float(primary["p90_net_bps"])
    p95_runner = _safe_float(runner["p95_net_bps"])
    worst = _safe_float(primary["worst_net_bps"])
    loss_rate = _safe_float(primary["loss_rate"])
    tail_penalty = abs(min(worst, 0.0)) * 0.9
    sample_penalty = max(min_sample - count, 0) * 0.75
    tier_penalty = {"A": 0.0, "B": 4.0, "C": 7.0, "D": 10.0}.get(tier, 10.0)
    high_upside_score = round((p90 * 0.65) + (p95_runner * 0.45) + (avg * 0.35) - tail_penalty - sample_penalty, 6)
    high_upside_score = round(high_upside_score - tier_penalty, 6)
    expected_roe_bps = round(avg * leverage, 6)
    p90_roe_bps = round(p90 * leverage, 6)
    worst_roe_bps = round(worst * leverage, 6)
    half_tp_runner_bps = [((ret15 * 0.5) + (run * 0.5)) for ret15, run in zip(horizons["15m"], horizons["runner"], strict=False)]
    scale_out = _summarize_returns(half_tp_runner_bps)
    scale_out_expected_roe_bps = (
        round(_safe_float(scale_out["avg_net_bps"]) * leverage, 6) if scale_out["avg_net_bps"] is not None else None
    )
    action, blockers = _profile_decision(
        count=count,
        avg_net_bps=avg,
        win_rate=win_rate,
        p90_net_bps=p90,
        worst_net_bps=worst,
        high_upside_score=high_upside_score,
        leverage=leverage,
        min_sample=min_sample,
    )
    return {
        "id": f"{key}|lev{leverage}x|{primary_key}_runner",
        "key": key,
        "tier": tier,
        "profile_type": profile_type,
        "primary_horizon": primary_key,
        "leverage": leverage,
        "action": action,
        "blockers": blockers,
        "high_upside_score": high_upside_score,
        "expected_roe_bps": expected_roe_bps,
        "p90_roe_bps": p90_roe_bps,
        "worst_roe_bps": worst_roe_bps,
        "tail_to_upside_ratio": round(abs(worst) / p90, 6) if p90 > 0.0 else None,
        "loss_rate": round(loss_rate, 6),
        "primary": primary,
        "five_minute": _summarize_returns(horizons["5m"]),
        "ten_minute": _summarize_returns(horizons["10m"]),
        "fifteen_minute": fifteen,
        "fast": _summarize_returns(horizons["fast"]),
        "runner": runner,
        "scale_out_half_15m_half_runner": {
            **scale_out,
            "expected_roe_bps": scale_out_expected_roe_bps,
        },
        "paper_only": True,
        "live_ready": False,
        "no_order_side_effects": True,
    }


def _expanded_groups(outcomes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    doge_near_miss = [
        row
        for row in outcomes
        if row.get("symbol") == "DOGEUSDT"
        and row.get("side") == "short"
        and row.get("strategy") in NEAR_MISS_SHORT_STRATEGIES
        and row.get("ret15_bps") is not None
    ]
    exhaustion_family = [
        row
        for row in outcomes
        if row.get("side") == "short"
        and row.get("strategy") in EXHAUSTION_FAMILY_SHORT_STRATEGIES
        and row.get("ret15_bps") is not None
    ]
    doge_fast_family = [
        row
        for row in outcomes
        if row.get("symbol") == "DOGEUSDT" and row.get("side") == "short" and row.get("ret15_bps") is not None
    ]
    return [
        {
            "key": "DOGEUSDT|short|near_miss_exhaustion_family",
            "tier": "B",
            "profile_type": "near_miss",
            "primary_horizon": "15m",
            "rows": doge_near_miss,
            "description": "DOGE short rows that share OI/crowding/momentum exhaustion ingredients but are not exact oi_exhaustion_reversion signals.",
        },
        {
            "key": "ALL|short|exhaustion_family",
            "tier": "C",
            "profile_type": "family",
            "primary_horizon": "15m",
            "rows": exhaustion_family,
            "description": "Cross-symbol short exhaustion/unwind family used to validate whether the pattern class has edge.",
        },
        {
            "key": "DOGEUSDT|short|fast_5m10m_family",
            "tier": "D",
            "profile_type": "fast_label_family",
            "primary_horizon": "fast",
            "rows": doge_fast_family,
            "description": "DOGE short family scored on max(5m, 10m) for faster high-upside signal triage.",
        },
    ]


def build_report(
    outcomes_payload: dict[str, Any],
    *,
    focus_keys: list[str] | tuple[str, ...] = DEFAULT_FOCUS_KEYS,
    leverages: list[int] | tuple[int, ...] = DEFAULT_LEVERAGES,
    cost_bps: float = ROUND_TRIP_COST_BPS,
    min_sample: int = 40,
    monitor_status: dict[str, Any] | None = None,
    include_expanded: bool = True,
) -> dict[str, Any]:
    outcomes = [row for row in list(outcomes_payload.get("outcomes") or []) if isinstance(row, dict)]
    safety = monitor_status or {"safe": True, "live_orders": 0, "tested_orders": 0, "bitget_positions": []}
    profiles: list[dict[str, Any]] = []
    legs: list[dict[str, Any]] = []
    for key in focus_keys:
        rows = _rows_for_key(outcomes, key)
        leg_profiles = [
            _profile_for_leg(key=key, rows=rows, leverage=leverage, cost_bps=cost_bps, min_sample=min_sample)
            for leverage in leverages
        ]
        leg_profiles.sort(key=lambda row: _safe_float(row.get("high_upside_score")), reverse=True)
        profiles.extend(leg_profiles)
        best = leg_profiles[0] if leg_profiles else {}
        legs.append(
            {
                "key": key,
                "tier": "A",
                "profile_type": "exact",
                "sample_count": len(rows),
                "best_action": best.get("action"),
                "best_profile_id": best.get("id"),
                "best_high_upside_score": best.get("high_upside_score"),
                "best_blockers": best.get("blockers"),
            }
        )
    if include_expanded:
        for group in _expanded_groups(outcomes):
            rows = list(group["rows"])
            if not rows:
                continue
            group_profiles = [
                _profile_for_leg(
                    key=str(group["key"]),
                    rows=rows,
                    leverage=leverage,
                    cost_bps=cost_bps,
                    min_sample=min_sample,
                    tier=str(group["tier"]),
                    profile_type=str(group["profile_type"]),
                    primary_horizon=str(group["primary_horizon"]),
                )
                for leverage in leverages
            ]
            group_profiles.sort(key=lambda row: _safe_float(row.get("high_upside_score")), reverse=True)
            profiles.extend(group_profiles)
            best = group_profiles[0] if group_profiles else {}
            legs.append(
                {
                    "key": group["key"],
                    "tier": group["tier"],
                    "profile_type": group["profile_type"],
                    "primary_horizon": group["primary_horizon"],
                    "sample_count": len(rows),
                    "best_action": best.get("action"),
                    "best_profile_id": best.get("id"),
                    "best_high_upside_score": best.get("high_upside_score"),
                    "best_blockers": best.get("blockers"),
                    "description": group["description"],
                }
            )
    profiles.sort(key=lambda row: _safe_float(row.get("high_upside_score")), reverse=True)
    candidate_count = sum(1 for row in profiles if row.get("action") == "paper_high_upside_candidate")
    watch_count = sum(1 for row in profiles if row.get("action") in {"paper_watch", "lottery_watch_only"})
    overall_action = "paper_high_upside_candidate" if candidate_count else "collect_more_samples" if watch_count else "reject_current_focus"
    if not safety.get("safe", True):
        overall_action = "halt_safety_violation"
    return {
        "mode": "paper50_high_upside_overlay",
        "generated_at": datetime.now(UTC).isoformat(),
        "paper_only": True,
        "no_order_side_effects": True,
        "live_ready": False,
        "overall_action": overall_action,
        "cost_bps": cost_bps,
        "min_sample": min_sample,
        "focus_keys": list(focus_keys),
        "leverages": list(leverages),
        "safety": safety,
        "leg_summaries": legs,
        "top_profiles": profiles[:12],
        "profiles": profiles,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alpha-outcomes", default=str(DEFAULT_ALPHA_OUTCOMES))
    parser.add_argument("--monitor-status", default=str(DEFAULT_MONITOR_STATUS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--focus-key", action="append", dest="focus_keys")
    parser.add_argument("--leverage", action="append", type=int, dest="leverages")
    parser.add_argument("--cost-bps", type=float, default=ROUND_TRIP_COST_BPS)
    parser.add_argument("--min-sample", type=int, default=40)
    parser.add_argument("--no-expanded", action="store_true")
    args = parser.parse_args()

    focus_keys = args.focus_keys or list(DEFAULT_FOCUS_KEYS)
    leverages = args.leverages or list(DEFAULT_LEVERAGES)
    report = build_report(
        _read_json(Path(args.alpha_outcomes)),
        focus_keys=focus_keys,
        leverages=leverages,
        cost_bps=max(args.cost_bps, 0.0),
        min_sample=max(args.min_sample, 1),
        monitor_status=_paper50_safety(Path(args.monitor_status)),
        include_expanded=not args.no_expanded,
    )
    _write_json(Path(args.output), report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 2 if report["overall_action"] == "halt_safety_violation" else 0


if __name__ == "__main__":
    raise SystemExit(main())
