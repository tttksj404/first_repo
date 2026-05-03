#!/usr/bin/env python3
"""Backtest Signal C (OI-Δ × Price-Δ quadrant) + Signal D (taker_buy_ratio extreme).

Loads cycle snapshots from quant_runtime_paper50/bitget_external_alpha_shadow/cycle_*,
joins each decision to nearest preceding 2 cycles to compute deltas, then buckets
forward 15m / 60m signed return by quadrant.
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
OUT = ROOT / "quant_runtime_paper50" / "artifacts" / "paper50_oi_quadrant_backtest_latest.json"

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "PEPEUSDT"]


def _stats(arr: list[float]) -> dict[str, Any]:
    if not arr:
        return {"n": 0}
    return {
        "n": len(arr),
        "mean_bps": round(statistics.mean(arr), 3),
        "median_bps": round(statistics.median(arr), 3),
        "winrate": round(sum(1 for x in arr if x > 0) / len(arr), 3),
    }


def _forward_ret_signed(client, *, symbol, ref_ts, ref_price, intent_side, forward_minutes):
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
    raw = (close / ref_price - 1.0) * 10000.0
    return -raw if intent_side == "short" else raw


def main() -> None:
    # Load all cycle metrics
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
                "taker_buy_ratio": _safe_float(row.get("taker_buy_ratio")),
                "long_ratio": _safe_float(row.get("long_ratio")),
                "long_short_ratio": _safe_float(row.get("long_short_ratio")),
            })

    for sym in SYMS:
        cycles_by_sym[sym].sort(key=lambda r: r["ts_ms"])
        print(f"  {sym}: {len(cycles_by_sym[sym])} cycle snapshots")

    cycle_ts_by_sym = {sym: [r["ts_ms"] for r in cycles_by_sym[sym]] for sym in SYMS}

    # Load decisions
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

        td = d.get("trend_direction", 0)
        intent_side = "long" if td > 0 else ("short" if td < 0 else "long")

        # Find the 2 most recent cycle snapshots before ts
        idx = bisect_left(cycle_ts_by_sym[sym], ts_ms) - 1
        if idx < 1:
            continue
        cur = cycles_by_sym[sym][idx]
        prev = cycles_by_sym[sym][idx - 1]
        if cur["open_interest"] <= 0 or prev["open_interest"] <= 0 or cur["last_price"] <= 0 or prev["last_price"] <= 0:
            continue

        oi_delta_pct = (cur["open_interest"] / prev["open_interest"] - 1.0) * 100.0
        price_delta_bps = (cur["last_price"] / prev["last_price"] - 1.0) * 10000.0
        taker_buy_ratio = cur["taker_buy_ratio"]
        long_ratio = cur["long_ratio"]

        f15 = _forward_ret_signed(client, symbol=sym, ref_ts=d["timestamp"], ref_price=ref, intent_side=intent_side, forward_minutes=15)
        f60 = _forward_ret_signed(client, symbol=sym, ref_ts=d["timestamp"], ref_price=ref, intent_side=intent_side, forward_minutes=60)

        results.append({
            "symbol": sym,
            "ts": d["timestamp"],
            "intent_side": intent_side,
            "oi_delta_pct": round(oi_delta_pct, 4),
            "price_delta_bps": round(price_delta_bps, 4),
            "taker_buy_ratio": round(taker_buy_ratio, 4) if taker_buy_ratio else None,
            "long_ratio": round(long_ratio, 4) if long_ratio else None,
            "f15": f15,
            "f60": f60,
        })
        if (i + 1) % 500 == 0:
            print(f"  ... {i+1}/{len(decisions)}")

    print(f"\nresults: {len(results)} (joinable to cycle snapshots)")

    # ============ Analysis ============
    # 1) OI×Price quadrant (raw, intent-agnostic forward return is just price move; we use SIGNED by intent)
    def quadrant(oi_d, pd):
        oi_up = oi_d > 0
        p_up = pd > 0
        if p_up and oi_up: return "newLongs(P↑+OI↑)"
        if p_up and not oi_up: return "shortCover(P↑+OI↓)"
        if not p_up and oi_up: return "newShorts(P↓+OI↑)"
        return "longUnwind(P↓+OI↓)"

    # Use unsigned RAW price forward return for quadrant analysis (since quadrant predicts direction)
    # We need raw forward return. Re-compute from intent-side flipped:
    # If intent="short", f15 was -raw. So raw = -f15 if intent=short else f15
    out: dict[str, Any] = {"n_results": len(results), "per_symbol": {}}

    for sym in SYMS:
        rs = [r for r in results if r["symbol"] == sym]
        if not rs:
            continue
        per_q15: dict[str, list[float]] = defaultdict(list)
        per_q60: dict[str, list[float]] = defaultdict(list)
        for r in rs:
            q = quadrant(r["oi_delta_pct"], r["price_delta_bps"])
            # raw price forward return (long-direction)
            f15_raw = r["f15"] if r["intent_side"] == "long" else -r["f15"] if r["f15"] is not None else None
            f60_raw = r["f60"] if r["intent_side"] == "long" else -r["f60"] if r["f60"] is not None else None
            if f15_raw is not None:
                per_q15[q].append(f15_raw)
            if f60_raw is not None:
                per_q60[q].append(f60_raw)
        out["per_symbol"][sym] = {
            "n": len(rs),
            "quadrant_f15_raw": {k: _stats(v) for k, v in per_q15.items()},
            "quadrant_f60_raw": {k: _stats(v) for k, v in per_q60.items()},
        }

    # 2) Taker buy ratio extreme buckets (signed-by-intent)
    def taker_bucket(r):
        x = r["taker_buy_ratio"]
        if x is None: return "no_data"
        if x >= 0.65: return "extreme_buy"
        if x >= 0.55: return "buy_lean"
        if x >= 0.45: return "balanced"
        if x >= 0.35: return "sell_lean"
        return "extreme_sell"

    bucket_f15: dict[str, list[float]] = defaultdict(list)
    bucket_f60: dict[str, list[float]] = defaultdict(list)
    for r in results:
        bk = taker_bucket(r)
        if r["f15"] is not None:
            bucket_f15[bk].append(r["f15"])
        if r["f60"] is not None:
            bucket_f60[bk].append(r["f60"])
    out["taker_buy_ratio_signed_by_intent"] = {
        "f15": {k: _stats(v) for k, v in bucket_f15.items()},
        "f60": {k: _stats(v) for k, v in bucket_f60.items()},
    }

    # 3) Long ratio (crowd long%) extreme buckets, signed-by-intent
    def long_bucket(r):
        x = r["long_ratio"]
        if x is None: return "no_data"
        if x >= 0.65: return "crowd_long_extreme"
        if x >= 0.55: return "crowd_long"
        if x >= 0.45: return "balanced"
        if x >= 0.35: return "crowd_short"
        return "crowd_short_extreme"

    lf15: dict[str, list[float]] = defaultdict(list)
    lf60: dict[str, list[float]] = defaultdict(list)
    for r in results:
        bk = long_bucket(r)
        if r["f15"] is not None:
            lf15[bk].append(r["f15"])
        if r["f60"] is not None:
            lf60[bk].append(r["f60"])
    out["long_ratio_signed_by_intent"] = {
        "f15": {k: _stats(v) for k, v in lf15.items()},
        "f60": {k: _stats(v) for k, v in lf60.items()},
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
