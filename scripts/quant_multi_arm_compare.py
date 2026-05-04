#!/usr/bin/env python3
"""Final multi-arm comparison + winner selection.

Reads the rolling watchdog log (`quant_runtime/multi_arm_log.jsonl`) plus the
latest snapshot, ranks arms by composite score, and emits a markdown-style
report to stdout.

Composite score (higher = better):
    pnl_weight * realized_pnl_usd_normalized
  + edge_weight * unrealized_pnl_usd_estimate_normalized
  + selectivity_bonus * (cross_coin_blocked rate, only for arms w/ gate ON)
  - flatline_penalty (if decisions == 0 over the run)

Usage:
  scripts/quant_python.sh scripts/quant_multi_arm_compare.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "quant_runtime" / "multi_arm_latest.json"
LOG = ROOT / "quant_runtime" / "multi_arm_log.jsonl"


def _composite_score(arm: dict[str, Any]) -> float:
    pnl = float(arm.get("realized_pnl_usd", 0.0) or 0.0)
    unrealized = float(arm.get("unrealized_pnl_usd_estimate", 0.0) or 0.0)
    decisions = int(arm.get("decisions_total", 0) or 0)
    cross_blocked = int(arm.get("cross_coin_blocked", 0) or 0)
    cross_boosted = int(arm.get("cross_coin_size_boosted", 0) or 0)
    closed = int(arm.get("closed_trades", 0) or 0)
    win_rate = float(arm.get("win_rate", 0.0) or 0.0)

    # Base on PnL (10x weight on realized + 1x on unrealized estimate)
    score = pnl * 10.0 + unrealized * 1.0
    # Selectivity bonus when gate fires usefully (each block ≈ 0.05 pts, capped at 5pts)
    score += min(cross_blocked * 0.05, 5.0)
    # Boost effectiveness: each boost ≈ 0.1 pts (cap 5pts)
    score += min(cross_boosted * 0.1, 5.0)
    # Win rate bonus when we have ≥10 closed trades
    if closed >= 10:
        score += (win_rate - 0.5) * 20.0  # +/-10 pts swing
    # Flatline penalty: arm produced no decisions
    if decisions == 0:
        score -= 100.0
    return round(score, 3)


def _format_arm(name: str, row: dict[str, Any]) -> list[str]:
    out: list[str] = []
    health = row.get("health", {})
    alive = "alive" if health.get("alive") else "DEAD"
    out.append(f"### {name}  [{alive}]")
    out.append(f"- decisions_total       : {row.get('decisions_total', 0)}")
    out.append(f"- closed_trades         : {row.get('closed_trades', 0)}")
    out.append(f"- win_rate              : {row.get('win_rate', 0.0):.3f}")
    out.append(f"- realized_pnl_usd      : {row.get('realized_pnl_usd', 0.0):+.4f}")
    out.append(f"- unrealized_pnl_usd_est: {row.get('unrealized_pnl_usd_estimate', 0.0):+.4f}")
    out.append(f"- open_positions        : {row.get('open_positions', 0)}")
    out.append(f"- cross_coin_blocked    : {row.get('cross_coin_blocked', 0)}")
    out.append(f"- cross_coin_top_priority: {row.get('cross_coin_top_priority_decisions', 0)}")
    out.append(f"- cross_coin_size_boost : {row.get('cross_coin_size_boosted', 0)}")
    out.append(f"- intent_notional_usd   : {row.get('total_intent_notional_usd', 0.0):.2f}")
    out.append(f"- top_rejections        : {row.get('top_rejection_reasons', {})}")
    out.append(f"- top_exit_reasons      : {row.get('top_exit_reasons', {})}")
    return out


def main() -> None:
    if not LATEST.exists():
        print("FATAL: no multi_arm_latest.json yet")
        return
    snap = json.loads(LATEST.read_text())
    arms = snap.get("arms", {})

    print("# Multi-Arm Experiment — Final Comparison")
    print(f"snapshot_ts: {snap.get('timestamp', '')}\n")

    # First pass: scores
    scored = []
    for name, row in arms.items():
        score = _composite_score(row)
        scored.append((score, name, row))
    scored.sort(key=lambda x: -x[0])

    print("## Ranked composite score\n")
    for i, (score, name, _) in enumerate(scored, start=1):
        marker = " ← WINNER" if i == 1 else ""
        print(f"  {i}. {name:11s}  score={score:+.3f}{marker}")
    print()

    print("## Per-arm detail\n")
    for _, name, row in scored:
        for line in _format_arm(name, row):
            print(line)
        print()

    # Recommendation
    if scored:
        winner_score, winner_name, winner_row = scored[0]
        print("## Recommendation\n")
        if winner_score < -50.0:
            print("All arms underperformed (composite < -50). No deploy decision until next session.")
        elif scored[0][0] - (scored[1][0] if len(scored) > 1 else -1e9) < 1.0:
            print(f"Top two arms within 1.0 composite point — declare TIE between {scored[0][1]} and {scored[1][1]}.")
            print("Recommend running an additional cycle before promoting.")
        else:
            print(f"Promote arm: **{winner_name}** (composite {winner_score:+.3f})")
            print(f"  decisions={winner_row.get('decisions_total', 0)} closed={winner_row.get('closed_trades', 0)} pnl={winner_row.get('realized_pnl_usd', 0.0):+.4f}")

    # Watchdog log summary
    if LOG.exists():
        try:
            ticks = sum(1 for _ in LOG.open())
        except OSError:
            ticks = 0
        print(f"\nticks_in_log: {ticks}")


if __name__ == "__main__":
    main()
