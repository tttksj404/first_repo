#!/usr/bin/env python3
"""Generate a paper-only Bitget outcome-feedback tuning candidate.

The script reads local read-only paper decisions, fetches public Bitget candles
for mature forward outcomes, and writes:

- an outcome feedback report
- a tightened paper-only strategy override candidate

It never calls private endpoints and never places, tests, cancels, or modifies
exchange orders.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_binance.execution.client_factory import build_exchange_rest_client  # noqa: E402


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _gate_lookup(path: Path) -> dict[tuple[str, str], str]:
    if not path.exists():
        return {}
    payload = _read_json(path)
    lookup: dict[tuple[str, str], str] = {}
    for row in list(payload.get("classified_decisions") or []):
        timestamp = str(row.get("timestamp") or "")
        symbol = str(row.get("symbol") or "").upper()
        gate = str(dict(row.get("high_probability_gate") or {}).get("state") or "unknown")
        if timestamp and symbol:
            lookup[(timestamp, symbol)] = gate
    return lookup


def _direction(row: dict[str, Any]) -> str:
    return "short" if _safe_float(row.get("trend_direction")) < 0.0 else "long"


def build_forward_outcomes(
    *,
    decisions_path: Path,
    gate_summary_path: Path,
    horizon_minutes: tuple[int, ...] = (5, 10, 15),
    min_age_minutes: int = 15,
    max_decisions: int | None = None,
    allow_insecure_ssl: bool = False,
) -> list[dict[str, Any]]:
    rows = _load_jsonl(decisions_path)
    if max_decisions is not None and max_decisions > 0:
        rows = sorted(rows, key=lambda row: str(row.get("timestamp") or ""))[-max_decisions:]
    gate_by_key = _gate_lookup(gate_summary_path)
    client = build_exchange_rest_client(
        exchange="bitget",
        allow_insecure_ssl=allow_insecure_ssl,
        allow_missing_credentials=True,
    )
    now = datetime.now(UTC)
    outcomes: list[dict[str, Any]] = []
    max_horizon = max(horizon_minutes)
    for row in rows:
        try:
            timestamp = datetime.fromisoformat(str(row.get("timestamp") or "").replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            continue
        if timestamp > now - timedelta(minutes=min_age_minutes):
            continue
        symbol = str(row.get("symbol") or "").upper()
        reference_price = _safe_float(row.get("reference_price"))
        cost_bps = _safe_float(row.get("estimated_round_trip_cost_bps"))
        if not symbol or reference_price <= 0.0:
            continue
        start_ms = int(timestamp.timestamp() * 1000)
        end_ms = int((timestamp + timedelta(minutes=max_horizon + 1)).timestamp() * 1000)
        try:
            bars = client.get_klines(
                market="futures",
                symbol=symbol,
                interval="1m",
                limit=max(25, max_horizon + 5),
                start_time=start_ms,
                end_time=end_ms,
            )
        except Exception:
            continue
        bars = sorted(bars, key=lambda item: int(item.get("open_time") or 0))
        if not bars:
            continue
        direction = _direction(row)
        sign = -1.0 if direction == "short" else 1.0
        outcome = {
            "timestamp": row.get("timestamp"),
            "symbol": symbol,
            "gate": gate_by_key.get((str(row.get("timestamp") or ""), symbol), "unknown"),
            "final_mode": row.get("final_mode") or row.get("mode"),
            "direction": direction,
            "score": round(_safe_float(row.get("predictability_score")), 6),
            "volume_confirmation": round(_safe_float(row.get("volume_confirmation")), 6),
            "net_expected_edge_bps": round(_safe_float(row.get("net_expected_edge_bps")), 6),
            "estimated_round_trip_cost_bps": round(cost_bps, 6),
            "rejection_reasons": list(row.get("rejection_reasons") or []),
        }
        ok = True
        for minutes in horizon_minutes:
            target_ms = int((timestamp + timedelta(minutes=minutes)).timestamp() * 1000)
            candidates = [bar for bar in bars if int(bar.get("open_time") or 0) <= target_ms]
            if not candidates:
                ok = False
                break
            close = _safe_float(candidates[-1].get("close_price"))
            ret = sign * ((close / reference_price) - 1.0) * 10000.0
            outcome[f"ret{minutes}_bps"] = round(ret, 6)
            outcome[f"net{minutes}_bps"] = round(ret - cost_bps, 6)
        if ok:
            outcomes.append(outcome)
    return outcomes


def _bucket_stats(outcomes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in outcomes:
        key = "|".join([str(row["symbol"]), str(row["gate"]), str(row["direction"])])
        grouped[key].append(row)
    stats: dict[str, dict[str, Any]] = {}
    for key, rows in sorted(grouped.items()):
        net15 = [_safe_float(row.get("net15_bps")) for row in rows]
        net10 = [_safe_float(row.get("net10_bps")) for row in rows]
        net5 = [_safe_float(row.get("net5_bps")) for row in rows]
        recent = net15[-5:]
        stats[key] = {
            "count": len(rows),
            "win15_count": sum(1 for value in net15 if value > 0.0),
            "win15_rate": round(sum(1 for value in net15 if value > 0.0) / len(net15), 6) if net15 else 0.0,
            "avg_net5_bps": round(sum(net5) / len(net5), 6) if net5 else 0.0,
            "avg_net10_bps": round(sum(net10) / len(net10), 6) if net10 else 0.0,
            "avg_net15_bps": round(sum(net15) / len(net15), 6) if net15 else 0.0,
            "recent5_net15_bps": [round(value, 6) for value in recent],
            "recent5_win15_count": sum(1 for value in recent if value > 0.0),
            "latest_net15_bps": round(net15[-1], 6) if net15 else None,
        }
    return stats


def _tighten_profile(profile: dict[str, Any], *, severity: str) -> dict[str, Any]:
    tuned = copy.deepcopy(profile)
    if severity == "high":
        tuned["min_predictability_score"] = round(_safe_float(tuned.get("min_predictability_score")) + 2.0, 6)
        tuned["min_volume_confirmation"] = round(_safe_float(tuned.get("min_volume_confirmation")) + 0.03, 6)
        tuned["min_net_edge_bps"] = round(_safe_float(tuned.get("min_net_edge_bps")) + 4.0, 6)
        tuned["min_edge_to_cost"] = round(_safe_float(tuned.get("min_edge_to_cost")) + 0.35, 6)
        tuned["size_multiplier"] = min(_safe_float(tuned.get("size_multiplier"), 1.0), 0.45)
    else:
        tuned["min_predictability_score"] = round(_safe_float(tuned.get("min_predictability_score")) + 1.0, 6)
        tuned["min_volume_confirmation"] = round(_safe_float(tuned.get("min_volume_confirmation")) + 0.015, 6)
        tuned["min_net_edge_bps"] = round(_safe_float(tuned.get("min_net_edge_bps")) + 2.0, 6)
        tuned["min_edge_to_cost"] = round(_safe_float(tuned.get("min_edge_to_cost")) + 0.15, 6)
        tuned["size_multiplier"] = min(_safe_float(tuned.get("size_multiplier"), 1.0), 0.65)
    return tuned


def build_feedback_config(
    *,
    base_config: dict[str, Any],
    bucket_stats: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tuned = copy.deepcopy(base_config)
    profiles = dict(tuned.get("symbol_filter_profiles") or {})
    actions: list[dict[str, Any]] = []

    for symbol, profile in sorted(profiles.items()):
        symbol_keys = {key: value for key, value in bucket_stats.items() if key.startswith(f"{symbol}|")}
        if not symbol_keys:
            continue
        admit_or_confirm = {
            key: value
            for key, value in symbol_keys.items()
            if "|admit_paper|" in key or "|confirm_only|" in key
        }
        all_avg = [value["avg_net15_bps"] for value in admit_or_confirm.values()] or [
            value["avg_net15_bps"] for value in symbol_keys.values()
        ]
        worst_recent_loss = min(
            (min(value["recent5_net15_bps"]) for value in symbol_keys.values() if value["recent5_net15_bps"]),
            default=0.0,
        )
        avg_net = sum(all_avg) / len(all_avg)
        severity = ""
        if avg_net < -15.0 or worst_recent_loss < -50.0:
            severity = "high"
        elif avg_net < 0.0:
            severity = "medium"
        if not severity:
            continue
        profiles[symbol] = _tighten_profile(dict(profile), severity=severity)
        actions.append(
            {
                "symbol": symbol,
                "action": f"tighten_{severity}",
                "reason": "negative_mature_outcome_feedback",
                "avg_selected_net15_bps": round(avg_net, 6),
                "worst_recent_net15_bps": round(worst_recent_loss, 6),
                "baseline_profile": profile,
                "tuned_profile": profiles[symbol],
            }
        )

    tuned["symbol_filter_profiles"] = profiles
    overlay = dict(tuned.get("bitget_entry_overlay") or {})
    overlay.update(
        {
            "paper_only": True,
            "outcome_feedback_enabled": True,
            "description": "Paper-only outcome-feedback tightened override; do not use for live without separate approval.",
        }
    )
    tuned["bitget_entry_overlay"] = overlay
    tuned["outcome_feedback_gate"] = {
        "enabled": True,
        "paper_only": True,
        "rules": {
            "block_direction_when_avg_net15_negative": True,
            "require_recent5_win_count_for_short_exception": 3,
            "require_avg_net15_positive_for_admission": True,
        },
    }
    return tuned, actions


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Bitget paper-only outcome feedback override.")
    parser.add_argument("--decisions", required=True)
    parser.add_argument("--gate-summary", required=True)
    parser.add_argument("--base-config", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-decisions", type=int)
    parser.add_argument("--insecure-ssl", action="store_true")
    args = parser.parse_args()

    outcomes = build_forward_outcomes(
        decisions_path=Path(args.decisions),
        gate_summary_path=Path(args.gate_summary),
        max_decisions=args.max_decisions,
        allow_insecure_ssl=args.insecure_ssl,
    )
    stats = _bucket_stats(outcomes)
    tuned, actions = build_feedback_config(base_config=_read_json(Path(args.base_config)), bucket_stats=stats)

    output_dir = Path(args.output_dir)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "paper_only": True,
        "max_decisions": args.max_decisions,
        "decision_count_with_mature_outcomes": len(outcomes),
        "bucket_stats": stats,
        "actions": actions,
        "verdict": "tighten" if actions else "hold",
    }
    report_path = output_dir / "outcome_feedback_report.json"
    config_path = output_dir / "paper50_multi_symbol_filters.outcome_feedback.json"
    _write_json(report_path, report)
    _write_json(config_path, tuned)
    print(json.dumps({"report": str(report_path), "tuned_filters": str(config_path), "action_count": len(actions)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
