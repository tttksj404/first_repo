#!/usr/bin/env python3
"""Signal C++ : Cross-coin context (BTC/ETH state when entering altcoin).

For each non-BTC decision, look up BTC's price/OI quadrant at the same cycle.
Bucket forward returns by (own_quadrant × BTC_quadrant) and by BTC price direction.

Hypothesis: PEPE shortCover -32bps may be much worse when BTC is also dumping,
much milder when BTC is pumping. If true, the gate becomes conditional.
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
OUT = ROOT / "quant_runtime_paper50" / "artifacts" / "paper50_oi_crosscoin_backtest_latest.json"

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "PEPEUSDT"]
LEADER = "BTCUSDT"  # cross-coin context source


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


def _quadrant(p_up: bool, oi_up: bool) -> str:
    if p_up and oi_up: return "newLongs"
    if p_up and not oi_up: return "shortCover"
    if not p_up and oi_up: return "newShorts"
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
        if sym == LEADER:
            continue  # skip leader-on-self
        ts = _parse_timestamp(d["timestamp"])
        ts_ms = int(ts.timestamp() * 1000)
        ref = _safe_float(d.get("reference_price"))
        if ref <= 0.0:
            continue

        # own quadrant from latest cycle pair
        idx_self = bisect_left(cycle_ts_by_sym[sym], ts_ms) - 1
        if idx_self < 1:
            continue
        cur = cycles_by_sym[sym][idx_self]
        prv = cycles_by_sym[sym][idx_self - 1]
        if cur["open_interest"] <= 0 or prv["open_interest"] <= 0 or cur["last_price"] <= 0 or prv["last_price"] <= 0:
            continue
        own_oi_d = (cur["open_interest"] / prv["open_interest"] - 1.0) * 100.0
        own_p_d = (cur["last_price"] / prv["last_price"] - 1.0) * 10000.0
        own_quad = _quadrant(own_p_d > 0, own_oi_d > 0)

        # leader (BTC) quadrant at same cycle (find BTC cycle nearest to ts_ms)
        idx_lead = bisect_left(cycle_ts_by_sym[LEADER], ts_ms) - 1
        if idx_lead < 1:
            continue
        bcur = cycles_by_sym[LEADER][idx_lead]
        bprv = cycles_by_sym[LEADER][idx_lead - 1]
        if bcur["open_interest"] <= 0 or bprv["open_interest"] <= 0 or bcur["last_price"] <= 0 or bprv["last_price"] <= 0:
            continue
        btc_oi_d = (bcur["open_interest"] / bprv["open_interest"] - 1.0) * 100.0
        btc_p_d = (bcur["last_price"] / bprv["last_price"] - 1.0) * 10000.0
        btc_quad = _quadrant(btc_p_d > 0, btc_oi_d > 0)
        btc_dir = "up" if btc_p_d > 0 else "down"  # simpler bucket too

        f15 = _forward_ret_raw(client, symbol=sym, ref_ts=d["timestamp"], ref_price=ref, forward_minutes=15)
        f60 = _forward_ret_raw(client, symbol=sym, ref_ts=d["timestamp"], ref_price=ref, forward_minutes=60)

        results.append({
            "symbol": sym,
            "ts": d["timestamp"],
            "own_quad": own_quad,
            "btc_quad": btc_quad,
            "btc_dir": btc_dir,
            "btc_p_d_bps": round(btc_p_d, 2),
            "f15": f15,
            "f60": f60,
        })
        if (i + 1) % 500 == 0:
            print(f"  ... {i+1}/{len(decisions)}")

    print(f"\nresults: {len(results)} (joinable, alts only)")

    # Analysis
    out: dict[str, Any] = {"n_results": len(results), "leader": LEADER, "per_symbol": {}}

    for sym in [s for s in SYMS if s != LEADER]:
        rs = [r for r in results if r["symbol"] == sym]
        if not rs:
            continue

        # 1) own_quad × btc_dir matrix
        own_btc_dir_15: dict[str, list[float]] = defaultdict(list)
        own_btc_dir_60: dict[str, list[float]] = defaultdict(list)
        for r in rs:
            key = f"{r['own_quad']}|btc_{r['btc_dir']}"
            if r["f15"] is not None: own_btc_dir_15[key].append(r["f15"])
            if r["f60"] is not None: own_btc_dir_60[key].append(r["f60"])

        # 2) own_quad × btc_quad fine matrix
        own_btc_quad_15: dict[str, list[float]] = defaultdict(list)
        own_btc_quad_60: dict[str, list[float]] = defaultdict(list)
        for r in rs:
            key = f"{r['own_quad']}|btc_{r['btc_quad']}"
            if r["f15"] is not None: own_btc_quad_15[key].append(r["f15"])
            if r["f60"] is not None: own_btc_quad_60[key].append(r["f60"])

        # 3) just own_quad alone (baseline for comparison)
        own_only_15: dict[str, list[float]] = defaultdict(list)
        own_only_60: dict[str, list[float]] = defaultdict(list)
        for r in rs:
            if r["f15"] is not None: own_only_15[r["own_quad"]].append(r["f15"])
            if r["f60"] is not None: own_only_60[r["own_quad"]].append(r["f60"])

        out["per_symbol"][sym] = {
            "n_total": len(rs),
            "own_only_f15": {k: _stats(v) for k, v in own_only_15.items()},
            "own_only_f60": {k: _stats(v) for k, v in own_only_60.items()},
            "own_x_btc_dir_f15": {k: _stats(v) for k, v in own_btc_dir_15.items()},
            "own_x_btc_dir_f60": {k: _stats(v) for k, v in own_btc_dir_60.items()},
            "own_x_btc_quad_f60": {k: _stats(v) for k, v in own_btc_quad_60.items()},
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
