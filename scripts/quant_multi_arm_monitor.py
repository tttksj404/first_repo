#!/usr/bin/env python3
"""Snapshot multi-arm experiment health + cumulative metrics.

Reads each arm's forensics/decisions.jsonl + paper trade logs and emits a
single JSON summary row appended to `quant_runtime/multi_arm_log.jsonl` and
also written to `quant_runtime/multi_arm_latest.json` for quick inspection.

Usage:
  scripts/quant_python.sh scripts/quant_multi_arm_monitor.py
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ARMS = {
    "A_live": ROOT / "quant_runtime_paper50",
    "E_aggressive": ROOT / "quant_runtime_armE",
    "F_lev_strong": ROOT / "quant_runtime_armF",
    "G_fut_active": ROOT / "quant_runtime_armG",
    "H_guard_on": ROOT / "quant_runtime_armH",
}
# All five arms are configured for the full 6-symbol universe; mismatch
# would indicate the daemon picked up a stale override file.
_FULL_UNIVERSE = frozenset(
    {"PEPEUSDT", "DOGEUSDT", "XRPUSDT", "SOLUSDT", "ETHUSDT", "BTCUSDT"}
)
EXPECTED_UNIVERSES = {
    "A_live": _FULL_UNIVERSE,
    "E_aggressive": _FULL_UNIVERSE,
    "F_lev_strong": _FULL_UNIVERSE,
    "G_fut_active": _FULL_UNIVERSE,
    "H_guard_on": _FULL_UNIVERSE,
}
OUTPUT_LATEST = ROOT / "quant_runtime" / "multi_arm_latest.json"
OUTPUT_LOG = ROOT / "quant_runtime" / "multi_arm_log.jsonl"


def _safe_load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open() as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return rows


def _process_alive(out_log: Path) -> dict[str, Any]:
    """Return health based on heartbeat freshness (no PID lookup)."""
    if not out_log.exists():
        return {"alive": False, "reason": "no_log"}
    try:
        mtime = out_log.stat().st_mtime
    except OSError:
        return {"alive": False, "reason": "stat_failed"}
    age_sec = time.time() - mtime
    return {
        "alive": age_sec < 120.0,  # heartbeat every ~5s; 2 min threshold
        "log_age_sec": round(age_sec, 1),
    }


def _latest_cycle_symbols(decisions: list[dict[str, Any]]) -> dict[str, Any] | None:
    latest_timestamp = ""
    latest_symbols: set[str] = set()
    for decision in decisions:
        timestamp = str(decision.get("timestamp") or "")
        symbol = str(decision.get("symbol") or "")
        if not timestamp or not symbol:
            continue
        if timestamp > latest_timestamp:
            latest_timestamp = timestamp
            latest_symbols = {symbol}
        elif timestamp == latest_timestamp:
            latest_symbols.add(symbol)
    if not latest_timestamp:
        return None
    return {
        "timestamp": latest_timestamp,
        "symbols": sorted(latest_symbols),
    }


def _universe_mismatch(name: str, latest_cycle: dict[str, Any] | None) -> dict[str, Any] | None:
    expected = EXPECTED_UNIVERSES.get(name)
    if not expected or not latest_cycle:
        return None
    observed = set(str(symbol) for symbol in latest_cycle.get("symbols", []) if symbol)
    unexpected = sorted(observed - expected)
    missing = sorted(expected - observed)
    if not unexpected and not missing:
        return {
            "detected": False,
            "expected_symbols": sorted(expected),
            "observed_symbols": sorted(observed),
            "latest_timestamp": latest_cycle.get("timestamp", ""),
            "unexpected_symbols": [],
            "missing_symbols": [],
        }
    return {
        "detected": True,
        "expected_symbols": sorted(expected),
        "observed_symbols": sorted(observed),
        "latest_timestamp": latest_cycle.get("timestamp", ""),
        "unexpected_symbols": unexpected,
        "missing_symbols": missing,
    }


def _summarize_arm(name: str, base: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"name": name, "base": str(base)}

    # Heartbeat alive check
    log_files = sorted(base.glob("_*.out.log"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    if log_files:
        out["health"] = _process_alive(log_files[0])
        out["log_path"] = str(log_files[0])
    else:
        out["health"] = {"alive": False, "reason": "no_logs"}

    # Forensics decisions
    decisions_path = base / "forensics" / "decisions.jsonl"
    decisions = _safe_load_jsonl(decisions_path)
    out["decisions_total"] = len(decisions)
    if decisions:
        sides: dict[str, int] = {}
        modes: dict[str, int] = {}
        cross_blocked = 0
        cross_priority = 0
        cross_boost = 0
        notional_sum = 0.0
        rejection_counter: dict[str, int] = {}
        for d in decisions:
            sides[d.get("side", "")] = sides.get(d.get("side", ""), 0) + 1
            modes[d.get("final_mode", "")] = modes.get(d.get("final_mode", ""), 0) + 1
            for r in (d.get("rejection_reasons") or ()):
                rejection_counter[r] = rejection_counter.get(r, 0) + 1
                if "CROSS_COIN_OI_QUADRANT_BLOCKED" in r:
                    cross_blocked += 1
            if d.get("cross_coin_is_top_priority"):
                cross_priority += 1
            for r in (d.get("size_boost_reasons") or ()):
                if "CROSS_COIN_EV_BOOST" in r:
                    cross_boost += 1
            notional_sum += float(d.get("order_intent_notional_usd", 0.0) or 0.0)

        out["sides"] = sides
        out["final_modes"] = modes
        out["cross_coin_blocked"] = cross_blocked
        out["cross_coin_top_priority_decisions"] = cross_priority
        out["cross_coin_size_boosted"] = cross_boost
        out["total_intent_notional_usd"] = round(notional_sum, 2)
        out["top_rejection_reasons"] = dict(sorted(rejection_counter.items(), key=lambda kv: -kv[1])[:5])
        latest_cycle = _latest_cycle_symbols(decisions)
        if latest_cycle:
            out["latest_cycle"] = latest_cycle
        mismatch = _universe_mismatch(name, latest_cycle)
        if mismatch is not None:
            out["universe_mismatch"] = mismatch
            if mismatch["detected"]:
                out["health"]["reason"] = "universe_mismatch"
                out["actionable_issue"] = (
                    "latest decision cycle symbols do not match the configured arm universe"
                )

    # Closed paper trades
    trades_path = base / "closed_trades.jsonl"
    trades = _safe_load_jsonl(trades_path)
    if trades:
        wins = sum(1 for t in trades if float(t.get("realized_pnl_usd", 0.0) or 0.0) > 0)
        losses = sum(1 for t in trades if float(t.get("realized_pnl_usd", 0.0) or 0.0) <= 0)
        pnl = sum(float(t.get("realized_pnl_usd", 0.0) or 0.0) for t in trades)
        exit_counter: dict[str, int] = {}
        for t in trades:
            r = str(t.get("exit_reason", "") or "")
            exit_counter[r] = exit_counter.get(r, 0) + 1
        out["closed_trades"] = len(trades)
        out["wins"] = wins
        out["losses"] = losses
        out["win_rate"] = round(wins / max(len(trades), 1), 3)
        out["realized_pnl_usd"] = round(pnl, 4)
        out["top_exit_reasons"] = dict(sorted(exit_counter.items(), key=lambda kv: -kv[1])[:5])
    else:
        out["closed_trades"] = 0
        out["realized_pnl_usd"] = 0.0

    # Open paper positions
    summary_state_path = base / "latest" / "summary.state.json"
    if summary_state_path.exists():
        try:
            ss = json.loads(summary_state_path.read_text())
            out["open_positions"] = len(ss.get("paper_positions", {}) or {})
            out["unrealized_pnl_usd_estimate"] = round(
                sum(float(p.get("unrealized_pnl_usd", 0.0) or 0.0) for p in ss.get("paper_positions", {}).values()),
                4,
            )
        except (OSError, json.JSONDecodeError):
            pass

    return out


def main() -> None:
    ts = datetime.now(timezone.utc).isoformat()
    summary = {"timestamp": ts, "arms": {}}
    for name, base in ARMS.items():
        summary["arms"][name] = _summarize_arm(name, base)

    OUTPUT_LATEST.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_LATEST.write_text(json.dumps(summary, indent=2, sort_keys=True))
    with OUTPUT_LOG.open("a") as f:
        f.write(json.dumps(summary) + "\n")

    # Print compact one-liner per arm
    print(f"=== {ts} ===")
    for name, row in summary["arms"].items():
        h = row.get("health", {})
        status = "OK"
        if not h.get("alive"):
            status = "DEAD"
        elif (row.get("universe_mismatch") or {}).get("detected"):
            status = "DRIFT"
        d = row.get("decisions_total", 0)
        ct = row.get("closed_trades", 0)
        wr = row.get("win_rate", 0.0)
        pnl = row.get("realized_pnl_usd", 0.0)
        cross = row.get("cross_coin_blocked", 0)
        boost = row.get("cross_coin_size_boosted", 0)
        op = row.get("open_positions", 0)
        issue = row.get("actionable_issue", "")
        print(
            f"  {name:11s} {status:5s} decisions={d:>5d}  trades={ct:>3d}  wr={wr:.2f}  pnl={pnl:>+9.2f}  cross_blocked={cross:>3d}  boosted={boost:>3d}  open={op}{'  issue=' + issue if issue else ''}"
        )


if __name__ == "__main__":
    main()
