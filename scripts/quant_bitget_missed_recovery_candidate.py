#!/usr/bin/env python3
"""Build a paper-only missed-entry recovery candidate config.

This is intentionally conservative: it does not broadly relax symbol filters.
It can add a side-specific paper recovery gate when missed-entry evidence shows
at least one stable winner, while outcome feedback still blocks broad
admission.
"""

from __future__ import annotations

import argparse
import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _btc_short_recovery_from_misses(missed: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any] | None:
    btc = dict(dict(missed.get("by_symbol") or {}).get("BTCUSDT") or {})
    winners = [
        row
        for row in list(btc.get("top") or [])
        if str(row.get("direction")) == "short"
        and _safe_float(row.get("net5")) > 0.0
        and _safe_float(row.get("net10")) > 0.0
        and _safe_float(row.get("net15")) >= 8.0
    ]
    if not winners:
        return None

    # If the broader BTC short bucket is not yet positive, allow only a stricter
    # future setup than the observed miss. This prevents one lucky short from
    # turning into broad BTC admission.
    bucket = dict(dict(outcome.get("bucket_stats") or {}).get("BTCUSDT|confirm_only|short") or {})
    avg_net15 = _safe_float(bucket.get("avg_net15_bps"))
    win_rate = _safe_float(bucket.get("win15_rate"))
    best = max(winners, key=lambda row: _safe_float(row.get("net15")))
    strict = avg_net15 <= 0.0 or win_rate < 0.60
    score = max(_safe_float(best.get("score")) + (4.0 if strict else 1.5), 72.0 if strict else 70.0)
    volume = max(_safe_float(best.get("volume")) + (0.03 if strict else 0.01), 0.52 if strict else 0.50)
    edge = max(_safe_float(best.get("edge")) + (6.0 if strict else 2.0), 30.0 if strict else 26.0)
    cost = _safe_float(best.get("cost"))
    edge_to_cost = edge / cost if cost > 0.0 else 4.0
    return {
        "enabled": True,
        "paper_only": True,
        "symbol": "BTCUSDT",
        "side": "short",
        "basis": "stable_positive_missed_entry_with_negative_bucket_guard",
        "observed_best_miss": best,
        "bucket_avg_net15_bps": round(avg_net15, 6),
        "bucket_win15_rate": round(win_rate, 6),
        "strict_mode": strict,
        "profile_fields": {
            "paper_recovery_enabled": True,
            "paper_recovery_side": "short",
            "paper_recovery_min_score": round(score, 6),
            "paper_recovery_min_volume_confirmation": round(volume, 6),
            "paper_recovery_min_net_edge_bps": round(edge, 6),
            "paper_recovery_min_edge_to_cost": round(max(edge_to_cost, 3.6 if strict else 3.1), 6),
            "paper_recovery_max_cost_bps": round(max(cost + 0.6, 8.75), 6),
            "paper_recovery_allowed_rejections": [
                "SYMBOL_PROFILE_SCORE_TOO_LOW",
                "SYMBOL_PROFILE_EDGE_TOO_THIN",
                "SYMBOL_PROFILE_EDGE_COST_TOO_THIN",
                "SYMBOL_PROFILE_VOLUME_TOO_WEAK",
                "SYMBOL_PROFILE_EXPECTED_PROFIT_TOO_SMALL",
            ],
            "paper_recovery_reason": "PAPER_BTC_SHORT_MISSED_RECOVERY",
        },
    }


def build_candidate(*, base_config: dict[str, Any], missed: dict[str, Any], outcome: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = copy.deepcopy(base_config)
    profiles = dict(candidate.get("symbol_filter_profiles") or {})
    recovery = _btc_short_recovery_from_misses(missed, outcome)
    actions: list[dict[str, Any]] = []
    if recovery:
        btc_profile = dict(profiles.get("BTCUSDT") or {})
        btc_profile.update(recovery["profile_fields"])
        # Keep base profile tight for BTC generally; recovery is a narrow paper
        # exception, not a broad relaxation.
        btc_profile["size_multiplier"] = min(_safe_float(btc_profile.get("size_multiplier"), 1.0), 0.35)
        profiles["BTCUSDT"] = btc_profile
        actions.append(
            {
                "action": "add_paper_btc_short_recovery_gate",
                "symbol": "BTCUSDT",
                "side": "short",
                "reason": recovery["basis"],
                "profile_fields": recovery["profile_fields"],
            }
        )
    candidate["symbol_filter_profiles"] = profiles
    overlay = dict(candidate.get("bitget_entry_overlay") or {})
    overlay.update(
        {
            "paper_only": True,
            "missed_entry_recovery_enabled": bool(recovery),
            "description": "Paper-only missed-entry recovery candidate; not live-approved.",
        }
    )
    candidate["bitget_entry_overlay"] = overlay
    candidate["missed_entry_recovery"] = {
        "paper_only": True,
        "generated_at": datetime.now(UTC).isoformat(),
        "recoveries": [recovery] if recovery else [],
        "rules": {
            "no_live_use_without_separate_approval": True,
            "recovery_requires_paper_verification_mode": True,
            "broad_relaxation_allowed": False,
        },
    }
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "paper_only": True,
        "action_count": len(actions),
        "actions": actions,
        "verdict": "paper_recovery_candidate" if actions else "hold_no_recovery",
        "rationale": "Use narrow side-specific recovery for stable missed entries; keep broad gates tight.",
    }
    return candidate, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a Bitget paper-only missed-entry recovery candidate.")
    parser.add_argument("--base-config", required=True)
    parser.add_argument("--missed-good", required=True)
    parser.add_argument("--outcome-report", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    candidate, report = build_candidate(
        base_config=_read_json(Path(args.base_config)),
        missed=_read_json(Path(args.missed_good)),
        outcome=_read_json(Path(args.outcome_report)),
    )
    output_dir = Path(args.output_dir)
    config_path = output_dir / "paper50_multi_symbol_filters.missed_recovery.json"
    report_path = output_dir / "missed_recovery_report.json"
    _write_json(config_path, candidate)
    _write_json(report_path, report)
    print(json.dumps({"report": str(report_path), "candidate_config": str(config_path), **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
