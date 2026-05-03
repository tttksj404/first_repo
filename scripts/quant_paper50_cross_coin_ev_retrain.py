#!/usr/bin/env python3
"""Retrain the cross-coin OI quadrant EV table from recent paper50 forensics.

Reads:
  - quant_runtime_paper50/bitget_external_alpha_shadow/cycle_*/metrics.json (cycle states)
  - quant_runtime_paper50/forensics/decisions.jsonl (decisions w/ reference_price + timestamp)
  - Bitget kline cache (forward returns; built on the fly, cached)

Produces:
  - quant_runtime_paper50/cross_coin_ev_table.candidate.json (new candidate table)
  - quant_runtime_paper50/cross_coin_ev_table.retrain_report.json (diff vs live table)

The script is intentionally non-destructive — it does NOT overwrite the live
`cross_coin_ev_table.json`. The operator inspects the candidate + report, then
manually copies the candidate over the live file when satisfied.

Schema of candidate file matches `cross_coin_ev_table.json`:
  schema_version, ev_threshold_bps, stale_minutes, leader_per_symbol,
  scenarios[], blockers[]
"""

from __future__ import annotations

import json
import statistics
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.quant_paper50_counterfactual import (  # type: ignore[import-not-found]
    fetch_klines_cached,
    _parse_timestamp,
    _safe_float,
)
from quant_binance.execution.client_factory import build_exchange_rest_client  # type: ignore[import-not-found]


SHADOW_ROOT = ROOT / "quant_runtime_paper50" / "bitget_external_alpha_shadow"
DECISIONS = ROOT / "quant_runtime_paper50" / "forensics" / "decisions.jsonl"
KLINE_CACHE = ROOT / "quant_runtime_paper50" / "cache" / "klines"
LIVE_TABLE = ROOT / "quant_runtime_paper50" / "cross_coin_ev_table.json"
CANDIDATE = ROOT / "quant_runtime_paper50" / "cross_coin_ev_table.candidate.json"
REPORT = ROOT / "quant_runtime_paper50" / "cross_coin_ev_table.retrain_report.json"

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "PEPEUSDT"]
LEADER_PER_SYMBOL = {
    "BTCUSDT": "ETHUSDT",
    "ETHUSDT": "BTCUSDT",
    "SOLUSDT": "BTCUSDT",
    "DOGEUSDT": "BTCUSDT",
    "PEPEUSDT": "BTCUSDT",
}

# Retrain hyperparameters (tweak as needed; mirror values currently shipped in live table).
EV_THRESHOLD_BPS = 5.0
STALE_MINUTES = 15
MIN_SAMPLES_SCENARIO = 20
MIN_SAMPLES_BLOCKER = 20
BLOCKER_FWD_FLOOR_BPS = -10.0  # scenarios with mean fwd_60m below this become blockers
FORWARD_MINUTES = 60


def _quadrant(p_up: bool, oi_up: bool) -> str:
    if p_up and oi_up:
        return "newLongs"
    if p_up and not oi_up:
        return "shortCover"
    if not p_up and oi_up:
        return "newShorts"
    return "longUnwind"


def _direction(p_up: bool) -> str:
    return "up" if p_up else "down"


def _forward_ret(client, *, symbol, ref_ts, ref_price, forward_minutes):
    if ref_price <= 0.0:
        return None
    ts = _parse_timestamp(ref_ts)
    start_ms = int(ts.timestamp() * 1000)
    end_ms = int((ts + timedelta(minutes=forward_minutes + 1)).timestamp() * 1000)
    try:
        bars = sorted(
            fetch_klines_cached(
                client.get_klines, symbol=symbol, start_ms=start_ms, end_ms=end_ms,
                forward_minutes=forward_minutes, cache_dir=KLINE_CACHE,
            ),
            key=lambda x: int(x.get("open_time") or 0),
        )
    except Exception:
        return None
    if not bars:
        return None
    target_ms = start_ms + forward_minutes * 60_000
    after = [b for b in bars if int(b.get("open_time") or 0) >= target_ms] or [bars[-1]]
    close = _safe_float(after[0].get("close_price"), 0.0)
    if close <= 0.0:
        return None
    return (close / ref_price - 1.0) * 10000.0


def _cycles_by_symbol() -> dict[str, list[dict[str, Any]]]:
    cycles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cdir in sorted(SHADOW_ROOT.glob("cycle_*")):
        mfile = cdir / "metrics.json"
        if not mfile.exists():
            continue
        try:
            payload = json.loads(mfile.read_text())
        except json.JSONDecodeError:
            continue
        for row in payload.get("rows", []):
            sym = (row.get("symbol") or "").upper()
            if sym not in SYMS:
                continue
            ts = row.get("timestamp")
            if not ts:
                continue
            try:
                ts_ms = int(_parse_timestamp(ts).timestamp() * 1000)
            except Exception:
                continue
            cycles[sym].append({
                "ts_ms": ts_ms,
                "open_interest": _safe_float(row.get("open_interest")),
                "last_price": _safe_float(row.get("last_price")),
            })
    for sym in SYMS:
        cycles[sym].sort(key=lambda r: r["ts_ms"])
    return cycles


def _state_at(cycles: list[dict[str, Any]], idx: int) -> dict[str, Any] | None:
    if idx < 1:
        return None
    cur = cycles[idx]
    prv = cycles[idx - 1]
    if cur["open_interest"] <= 0 or prv["open_interest"] <= 0 or cur["last_price"] <= 0 or prv["last_price"] <= 0:
        return None
    oi_d_pct = (cur["open_interest"] / prv["open_interest"] - 1.0) * 100.0
    p_d_bps = (cur["last_price"] / prv["last_price"] - 1.0) * 10000.0
    return {
        "ts_ms": cur["ts_ms"],
        "own_quadrant": _quadrant(p_d_bps > 0, oi_d_pct > 0),
        "own_dir": _direction(p_d_bps > 0),
        "oi_delta_pct": oi_d_pct,
        "price_delta_bps": p_d_bps,
    }


def main() -> None:
    cycles = _cycles_by_symbol()
    print(f"loaded cycles: " + ", ".join(f"{s}={len(cycles[s])}" for s in SYMS))
    cycle_ts_by_sym = {sym: [r["ts_ms"] for r in cycles[sym]] for sym in SYMS}

    decisions: list[dict[str, Any]] = []
    if DECISIONS.exists():
        with DECISIONS.open() as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (d.get("symbol") or "").upper() in SYMS:
                    decisions.append(d)
    print(f"loaded {len(decisions)} decisions")

    client = build_exchange_rest_client(exchange="bitget", allow_insecure_ssl=True, allow_missing_credentials=True)

    # Aggregator: (symbol, side, own_quadrant, leader_quadrant, leader_dir) -> [fwd_60m_bps,...]
    agg: dict[tuple[str, str, str, str, str], list[float]] = defaultdict(list)

    for i, d in enumerate(decisions):
        sym = d["symbol"].upper()
        side = (d.get("side") or "").lower()
        if side not in {"long", "short"}:
            continue
        ts_ms = int(_parse_timestamp(d["timestamp"]).timestamp() * 1000)
        ref = _safe_float(d.get("reference_price"))
        if ref <= 0:
            continue

        idx_self = bisect_left(cycle_ts_by_sym[sym], ts_ms) - 1
        own = _state_at(cycles[sym], idx_self) if idx_self >= 1 else None
        if own is None:
            continue

        leader_sym = LEADER_PER_SYMBOL.get(sym, "")
        if leader_sym:
            idx_lead = bisect_left(cycle_ts_by_sym[leader_sym], ts_ms) - 1
            leader = _state_at(cycles[leader_sym], idx_lead) if idx_lead >= 1 else None
        else:
            leader = None

        f60 = _forward_ret(client, symbol=sym, ref_ts=d["timestamp"], ref_price=ref, forward_minutes=FORWARD_MINUTES)
        if f60 is None:
            continue

        # Sign-adjusted return: long benefits from positive, short from negative.
        signed = f60 if side == "long" else -f60

        leader_quad = leader["own_quadrant"] if leader else ""
        leader_dir = leader["own_dir"] if leader else ""
        agg[(sym, side, own["own_quadrant"], leader_quad, leader_dir)].append(signed)

        if (i + 1) % 500 == 0:
            print(f"  ... {i+1}/{len(decisions)}")

    print(f"\naggregator buckets: {len(agg)}")

    # Build scenarios + blockers
    scenarios: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []

    for (sym, side, own_q, lead_q, lead_d), arr in agg.items():
        if len(arr) < min(MIN_SAMPLES_SCENARIO, MIN_SAMPLES_BLOCKER):
            continue
        n = len(arr)
        mean_bps = round(statistics.mean(arr), 3)
        winrate = round(sum(1 for x in arr if x > 0) / n, 3)
        # Hand the simplified ev_bps: mean of positive returns minus mean of negative drawdowns.
        # We approximate ev as: mean_bps (already directional, signed by side).
        ev_bps = round(mean_bps, 2)
        record = {
            "symbol": sym,
            "side": side,
            "own_quadrant": own_q,
            "leader_quadrant": lead_q or None,
            "leader_dir": lead_d or None,
            "n": n,
            "fwd_60m_bps": mean_bps,
            "winrate": winrate,
            "ev_bps": ev_bps,
        }
        if ev_bps >= EV_THRESHOLD_BPS and n >= MIN_SAMPLES_SCENARIO:
            scenarios.append(record)
        elif ev_bps <= BLOCKER_FWD_FLOOR_BPS and n >= MIN_SAMPLES_BLOCKER:
            blocker_record = dict(record)
            blocker_record["reason"] = f"{sym}_{side}_{own_q}_negative_ev"
            blockers.append(blocker_record)

    scenarios.sort(key=lambda r: r["ev_bps"], reverse=True)
    for rank, s in enumerate(scenarios, start=1):
        s["rank"] = rank
    blockers.sort(key=lambda r: r["ev_bps"])

    candidate = {
        "schema_version": 1,
        "description": (
            f"Auto-retrained from {len(decisions)} decisions; "
            f"thresholds ev>={EV_THRESHOLD_BPS}bps, blocker<={BLOCKER_FWD_FLOOR_BPS}bps, "
            f"min_n={MIN_SAMPLES_SCENARIO}."
        ),
        "ev_threshold_bps": EV_THRESHOLD_BPS,
        "stale_minutes": STALE_MINUTES,
        "leader_per_symbol": LEADER_PER_SYMBOL,
        "scenarios": scenarios,
        "blockers": blockers,
    }

    CANDIDATE.parent.mkdir(parents=True, exist_ok=True)
    CANDIDATE.write_text(json.dumps(candidate, indent=2, sort_keys=True))
    print(f"\nwrote candidate -> {CANDIDATE}")
    print(f"  scenarios: {len(scenarios)} | blockers: {len(blockers)}")

    # Diff vs live
    live = {}
    if LIVE_TABLE.exists():
        try:
            live = json.loads(LIVE_TABLE.read_text())
        except json.JSONDecodeError:
            live = {}
    live_scenarios = {(s.get("symbol"), s.get("side"), s.get("own_quadrant"), s.get("leader_quadrant"), s.get("leader_dir")): s for s in live.get("scenarios", [])}
    candidate_scenarios = {(s.get("symbol"), s.get("side"), s.get("own_quadrant"), s.get("leader_quadrant"), s.get("leader_dir")): s for s in scenarios}

    new_keys = sorted(set(candidate_scenarios) - set(live_scenarios))
    removed_keys = sorted(set(live_scenarios) - set(candidate_scenarios))
    common_keys = sorted(set(candidate_scenarios) & set(live_scenarios))
    drift_rows = []
    for k in common_keys:
        live_row = live_scenarios[k]
        cand_row = candidate_scenarios[k]
        ev_diff = round(float(cand_row["ev_bps"]) - float(live_row.get("ev_bps", 0.0)), 2)
        if abs(ev_diff) >= 1.0:  # report >1bps drift
            drift_rows.append({
                "key": list(k),
                "live_ev_bps": live_row.get("ev_bps"),
                "candidate_ev_bps": cand_row["ev_bps"],
                "ev_drift_bps": ev_diff,
                "live_n": live_row.get("n"),
                "candidate_n": cand_row["n"],
            })

    report = {
        "candidate_path": str(CANDIDATE),
        "live_path": str(LIVE_TABLE),
        "decisions_processed": len(decisions),
        "scenarios_live": len(live_scenarios),
        "scenarios_candidate": len(candidate_scenarios),
        "blockers_live": len(live.get("blockers", [])),
        "blockers_candidate": len(blockers),
        "new_scenario_keys": [list(k) for k in new_keys],
        "removed_scenario_keys": [list(k) for k in removed_keys],
        "drift_rows_over_1bps": drift_rows,
        "manual_apply_command": f"cp {CANDIDATE} {LIVE_TABLE}",
    }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True))
    print(f"wrote report   -> {REPORT}")
    print("\nReview the report, then to apply:")
    print(f"  cp {CANDIDATE} {LIVE_TABLE}")


if __name__ == "__main__":
    main()
