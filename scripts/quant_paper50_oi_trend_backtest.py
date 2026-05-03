#!/usr/bin/env python3
"""Signal C+ : Multi-cycle OI/price trend (3-step lookback).

Compare single-step quadrant vs 3-step consistent trend:
- "single_shortCover": only the most recent step is P↑+OI↓
- "consistent_shortCover": 3 of last 3 steps are P↑+OI↓ (real squeeze fake)
Same for newLongs / newShorts / longUnwind.

Hypothesis: consistent N-step pattern is much more reliable than single point.
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
OUT = ROOT / "quant_runtime_paper50" / "artifacts" / "paper50_oi_trend_backtest_latest.json"

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "PEPEUSDT"]
LOOKBACK = 3  # number of consecutive (cur-prev) steps required for "consistent"


def _stats(arr: list[float]) -> dict[str, Any]:
    if not arr:
        return {"n": 0}
    return {
        "n": len(arr),
        "mean_bps": round(statistics.mean(arr), 3),
        "median_bps": round(statistics.median(arr), 3),
        "winrate": round(sum(1 for x in arr if x > 0) / len(arr), 3),
    }


def _forward_ret_raw(client, *, symbol, ref_ts, ref_price, forward_minutes):
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


def _label_step(price_up: bool, oi_up: bool) -> str:
    if price_up and oi_up: return "newLongs"
    if price_up and not oi_up: return "shortCover"
    if not price_up and oi_up: return "newShorts"
    return "longUnwind"


def main() -> None:
    cycles_by_sym: dict[str, list[dict[str, Any]]] = defaultdict(list)
    cycle_dirs = sorted(SHADOW_ROOT.glob("cycle_*"))
    print(f"loading {len(cycle_dirs)} cycle dirs ...")
    for cdir in cycle_dirs:
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
            cycles_by_sym[sym].append({
                "ts_ms": ts_ms,
                "open_interest": _safe_float(row.get("open_interest")),
                "last_price": _safe_float(row.get("last_price")),
            })

    for sym in SYMS:
        cycles_by_sym[sym].sort(key=lambda r: r["ts_ms"])
        print(f"  {sym}: {len(cycles_by_sym[sym])} cycle snapshots")

    cycle_ts_by_sym = {sym: [r["ts_ms"] for r in cycles_by_sym[sym]] for sym in SYMS}

    decisions = []
    with DECISIONS.open() as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            sym = (d.get("symbol") or "").upper()
            if sym in SYMS:
                decisions.append(d)
    print(f"\nloaded {len(decisions)} decisions")

    client = build_exchange_rest_client(exchange="bitget", allow_insecure_ssl=True, allow_missing_credentials=True)
    results: list[dict[str, Any]] = []

    for i, d in enumerate(decisions):
        sym = d["symbol"].upper()
        ts = _parse_timestamp(d["timestamp"])
        ts_ms = int(ts.timestamp() * 1000)
        ref = _safe_float(d.get("reference_price"))
        if ref <= 0.0:
            continue

        idx = bisect_left(cycle_ts_by_sym[sym], ts_ms) - 1
        if idx < LOOKBACK:
            continue

        # Compute the last LOOKBACK step labels (idx-LOOKBACK..idx)
        step_labels: list[str] = []
        oi_deltas_pct: list[float] = []
        price_deltas_bps: list[float] = []
        bad = False
        for s in range(LOOKBACK):
            cur = cycles_by_sym[sym][idx - s]
            prv = cycles_by_sym[sym][idx - s - 1]
            if cur["open_interest"] <= 0 or prv["open_interest"] <= 0 or cur["last_price"] <= 0 or prv["last_price"] <= 0:
                bad = True
                break
            oi_d = (cur["open_interest"] / prv["open_interest"] - 1.0) * 100.0
            p_d = (cur["last_price"] / prv["last_price"] - 1.0) * 10000.0
            step_labels.append(_label_step(p_d > 0, oi_d > 0))
            oi_deltas_pct.append(oi_d)
            price_deltas_bps.append(p_d)
        if bad:
            continue

        # most-recent step is step_labels[0]; oldest is step_labels[-1]
        latest = step_labels[0]
        consistent = all(s == latest for s in step_labels)

        # cumulative deltas across the lookback window
        cum_oi_pct = (cycles_by_sym[sym][idx]["open_interest"]
                      / cycles_by_sym[sym][idx - LOOKBACK]["open_interest"] - 1.0) * 100.0
        cum_price_bps = (cycles_by_sym[sym][idx]["last_price"]
                         / cycles_by_sym[sym][idx - LOOKBACK]["last_price"] - 1.0) * 10000.0

        # ALWAYS compute long-direction raw forward return (we'll bucket by quadrant pattern)
        f15 = _forward_ret_raw(client, symbol=sym, ref_ts=d["timestamp"], ref_price=ref, forward_minutes=15)
        f60 = _forward_ret_raw(client, symbol=sym, ref_ts=d["timestamp"], ref_price=ref, forward_minutes=60)

        results.append({
            "symbol": sym,
            "ts": d["timestamp"],
            "latest_label": latest,
            "consistent": consistent,
            "step_labels": step_labels,  # newest first
            "step_oi_pct": [round(x, 4) for x in oi_deltas_pct],
            "step_price_bps": [round(x, 2) for x in price_deltas_bps],
            "cum_oi_pct": round(cum_oi_pct, 4),
            "cum_price_bps": round(cum_price_bps, 2),
            "f15_raw": f15,
            "f60_raw": f60,
        })
        if (i + 1) % 500 == 0:
            print(f"  ... {i+1}/{len(decisions)}")

    print(f"\nresults: {len(results)} (joinable, lookback>={LOOKBACK})")

    out: dict[str, Any] = {"n_results": len(results), "lookback": LOOKBACK, "per_symbol": {}}

    for sym in SYMS:
        rs = [r for r in results if r["symbol"] == sym]
        if not rs:
            continue
        # 1) bucket by (latest_label, consistent flag)
        single_f15: dict[str, list[float]] = defaultdict(list)
        single_f60: dict[str, list[float]] = defaultdict(list)
        consistent_f15: dict[str, list[float]] = defaultdict(list)
        consistent_f60: dict[str, list[float]] = defaultdict(list)
        for r in rs:
            tag = r["latest_label"]
            f15, f60 = r["f15_raw"], r["f60_raw"]
            if r["consistent"]:
                if f15 is not None: consistent_f15[tag].append(f15)
                if f60 is not None: consistent_f60[tag].append(f60)
            else:
                if f15 is not None: single_f15[tag].append(f15)
                if f60 is not None: single_f60[tag].append(f60)

        out["per_symbol"][sym] = {
            "n_total": len(rs),
            "n_consistent": sum(1 for r in rs if r["consistent"]),
            f"{LOOKBACK}step_consistent_f15_raw": {k: _stats(v) for k, v in consistent_f15.items()},
            f"{LOOKBACK}step_consistent_f60_raw": {k: _stats(v) for k, v in consistent_f60.items()},
            "single_step_only_f15_raw": {k: _stats(v) for k, v in single_f15.items()},
            "single_step_only_f60_raw": {k: _stats(v) for k, v in single_f60.items()},
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
