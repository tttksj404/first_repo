#!/usr/bin/env python3
"""Backtest entry filter against actual market forward returns.

For every decision in `quant_runtime_paper50/forensics/decisions.jsonl`,
fetch the 15m forward return from market data, then evaluate per-symbol
whether each gate (predictability/edge/liquidity/volume + min_expected_profit)
discriminates winners from losers.

Output:
- per-symbol gate discrimination table
- which gates are correct (pass → higher forward return)
- which gates are inverted (pass → worse forward return; gate is killing winners)
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.quant_paper50_counterfactual import (  # type: ignore[import-not-found]
    fetch_klines_cached,
    _parse_timestamp,
    _safe_float,
)
from quant_binance.execution.client_factory import build_exchange_rest_client  # type: ignore[import-not-found]


DECISIONS = ROOT / "quant_runtime_paper50" / "forensics" / "decisions.jsonl"
FILTERS = ROOT / "quant_runtime_paper50" / "paper50_multi_symbol_filters.json"
KLINE_CACHE = ROOT / "quant_runtime_paper50" / "cache" / "klines"
OUT = ROOT / "quant_runtime_paper50" / "artifacts" / "paper50_filter_backtest_latest.json"


def _forward_ret_bps(client, *, symbol: str, ref_ts: str, ref_price: float, forward_minutes: int) -> float | None:
    if ref_price <= 0.0:
        return None
    ts = _parse_timestamp(ref_ts)
    start_ms = int(ts.timestamp() * 1000)
    end_ms = int((ts + timedelta(minutes=forward_minutes + 1)).timestamp() * 1000)
    try:
        bars = sorted(
            fetch_klines_cached(
                client.get_klines,
                symbol=symbol,
                start_ms=start_ms,
                end_ms=end_ms,
                forward_minutes=forward_minutes,
                cache_dir=KLINE_CACHE,
            ),
            key=lambda item: int(item.get("open_time") or 0),
        )
    except Exception:
        return None
    if not bars:
        return None
    target_ms = start_ms + forward_minutes * 60_000
    after = [b for b in bars if int(b.get("open_time") or 0) >= target_ms]
    if not after:
        after = [bars[-1]]
    close = _safe_float(after[0].get("close_price"), 0.0)
    if close <= 0.0:
        return None
    return (close / ref_price - 1.0) * 10000.0


def _signed_ret(forward_bps: float | None, side: str) -> float | None:
    if forward_bps is None:
        return None
    if side == "long":
        return forward_bps
    if side == "short":
        return -forward_bps
    return forward_bps  # for analysis purposes when intent is flat, treat raw


def main() -> None:
    profiles = json.loads(FILTERS.read_text())["symbol_filter_profiles"]
    client = build_exchange_rest_client(exchange="bitget", allow_insecure_ssl=True, allow_missing_credentials=True)

    rows = []
    with DECISIONS.open() as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            sym = (d.get("symbol") or "").upper()
            if sym not in profiles:
                continue
            rows.append(d)

    print(f"loaded {len(rows)} decisions across {len(profiles)} symbols")

    forward_15 = []
    forward_60 = []
    for i, d in enumerate(rows):
        sym = d["symbol"].upper()
        ref_price = _safe_float(d.get("reference_price"), 0.0)
        ts = d.get("timestamp", "")
        f15 = _forward_ret_bps(client, symbol=sym, ref_ts=ts, ref_price=ref_price, forward_minutes=15)
        f60 = _forward_ret_bps(client, symbol=sym, ref_ts=ts, ref_price=ref_price, forward_minutes=60)
        forward_15.append(f15)
        forward_60.append(f60)
        if (i + 1) % 200 == 0:
            print(f"  ... {i+1}/{len(rows)}")

    # group by symbol
    out: dict[str, Any] = {"per_symbol": {}, "summary": {}}
    for sym in sorted(profiles):
        prof = profiles[sym]
        sym_rows = [(d, f15, f60) for d, f15, f60 in zip(rows, forward_15, forward_60) if (d.get("symbol") or "").upper() == sym]
        if not sym_rows:
            continue
        gates = {
            "edge": ("net_expected_edge_bps", float(prof.get("min_net_edge_bps", 0.0)), True),
            "predictability": ("predictability_score", float(prof.get("min_predictability_score", 0.0)), True),
            "liquidity": ("liquidity_score", float(prof.get("min_liquidity_score", 0.0)), True),
            "volume": ("volume_confirmation", float(prof.get("min_volume_confirmation", 0.0)), True),
            "edge_to_cost": ("__edge_to_cost__", float(prof.get("min_edge_to_cost", 0.0)), True),
            "stop_distance": ("stop_distance_bps", float(prof.get("max_stop_distance_bps", 0.0)), False),
        }
        per_gate: dict[str, Any] = {}

        for gate_name, (field, threshold, geq) in gates.items():
            if threshold <= 0.0:
                continue
            pass_rets15: list[float] = []
            fail_rets15: list[float] = []
            pass_rets60: list[float] = []
            fail_rets60: list[float] = []
            for d, f15, f60 in sym_rows:
                if field == "__edge_to_cost__":
                    cost = _safe_float(d.get("estimated_round_trip_cost_bps"), 0.0)
                    if cost <= 0.0:
                        continue
                    val = _safe_float(d.get("net_expected_edge_bps"), 0.0) / cost
                else:
                    val = _safe_float(d.get(field), 0.0)
                # interpret intent direction from trend_direction (since rejected→side='flat')
                td = d.get("trend_direction", 0)
                intent_side = "long" if td > 0 else ("short" if td < 0 else "long")
                signed15 = _signed_ret(f15, intent_side)
                signed60 = _signed_ret(f60, intent_side)
                if geq:
                    passed = val >= threshold
                else:
                    passed = val <= threshold
                if signed15 is not None:
                    (pass_rets15 if passed else fail_rets15).append(signed15)
                if signed60 is not None:
                    (pass_rets60 if passed else fail_rets60).append(signed60)

            def _stats(arr: list[float]) -> dict[str, Any]:
                if not arr:
                    return {"n": 0}
                return {
                    "n": len(arr),
                    "mean_bps": round(statistics.mean(arr), 3),
                    "median_bps": round(statistics.median(arr), 3),
                    "winrate": round(sum(1 for x in arr if x > 0) / len(arr), 3),
                }

            per_gate[gate_name] = {
                "threshold": threshold,
                "field": field,
                "geq": geq,
                "pass15": _stats(pass_rets15),
                "fail15": _stats(fail_rets15),
                "pass60": _stats(pass_rets60),
                "fail60": _stats(fail_rets60),
                "discrimination_15bps": (
                    round(statistics.mean(pass_rets15) - statistics.mean(fail_rets15), 3)
                    if pass_rets15 and fail_rets15 else None
                ),
                "discrimination_60bps": (
                    round(statistics.mean(pass_rets60) - statistics.mean(fail_rets60), 3)
                    if pass_rets60 and fail_rets60 else None
                ),
            }

        # also compute overall: pass-all-gates (relevant ones) vs fail-any
        all_pass15: list[float] = []
        all_fail15: list[float] = []
        all_pass60: list[float] = []
        all_fail60: list[float] = []
        for d, f15, f60 in sym_rows:
            ok = True
            for gate_name, (field, threshold, geq) in gates.items():
                if threshold <= 0.0:
                    continue
                if field == "__edge_to_cost__":
                    cost = _safe_float(d.get("estimated_round_trip_cost_bps"), 0.0)
                    if cost <= 0.0:
                        ok = False
                        break
                    val = _safe_float(d.get("net_expected_edge_bps"), 0.0) / cost
                else:
                    val = _safe_float(d.get(field), 0.0)
                if geq and val < threshold:
                    ok = False
                    break
                if (not geq) and val > threshold:
                    ok = False
                    break
            td = d.get("trend_direction", 0)
            intent_side = "long" if td > 0 else ("short" if td < 0 else "long")
            s15 = _signed_ret(f15, intent_side)
            s60 = _signed_ret(f60, intent_side)
            if s15 is not None:
                (all_pass15 if ok else all_fail15).append(s15)
            if s60 is not None:
                (all_pass60 if ok else all_fail60).append(s60)

        def _stats(arr: list[float]) -> dict[str, Any]:
            if not arr:
                return {"n": 0}
            return {
                "n": len(arr),
                "mean_bps": round(statistics.mean(arr), 3),
                "median_bps": round(statistics.median(arr), 3),
                "winrate": round(sum(1 for x in arr if x > 0) / len(arr), 3),
            }

        out["per_symbol"][sym] = {
            "n_decisions": len(sym_rows),
            "all_gates_pass15": _stats(all_pass15),
            "all_gates_fail15": _stats(all_fail15),
            "all_gates_pass60": _stats(all_pass60),
            "all_gates_fail60": _stats(all_fail60),
            "discrimination_all_15bps": (
                round(statistics.mean(all_pass15) - statistics.mean(all_fail15), 3)
                if all_pass15 and all_fail15 else None
            ),
            "discrimination_all_60bps": (
                round(statistics.mean(all_pass60) - statistics.mean(all_fail60), 3)
                if all_pass60 and all_fail60 else None
            ),
            "per_gate": per_gate,
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
