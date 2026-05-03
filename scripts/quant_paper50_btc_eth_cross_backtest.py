#!/usr/bin/env python3
"""BTC own quadrant × ETH context cross-coin backtest.

Mirror of crosscoin script but with BTC as own and ETH as the leader
(BTC is large-cap; ETH is also large-cap, can serve as confirming leader).
Also includes BTC own-only as fallback.
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

ROOT = Path("/Users/tttksj/first_repo")
sys.path.insert(0, str(ROOT))

from scripts.quant_paper50_counterfactual import (  # type: ignore
    fetch_klines_cached, _parse_timestamp, _safe_float,
)
from quant_binance.execution.client_factory import build_exchange_rest_client  # type: ignore


SHADOW_ROOT = ROOT / "quant_runtime_paper50" / "bitget_external_alpha_shadow"
DECISIONS = ROOT / "quant_runtime_paper50" / "forensics" / "decisions.jsonl"
KLINE_CACHE = ROOT / "quant_runtime_paper50" / "cache" / "klines"
OUT = ROOT / "quant_runtime_paper50" / "artifacts" / "paper50_btc_eth_cross_backtest_latest.json"

OWN = "BTCUSDT"
LEADER = "ETHUSDT"


def _stats(arr):
    if not arr: return {"n": 0}
    return {"n": len(arr), "mean_bps": round(statistics.mean(arr), 3),
            "median_bps": round(statistics.median(arr), 3),
            "winrate": round(sum(1 for x in arr if x > 0) / len(arr), 3)}


def _forward_ret(client, *, symbol, ref_ts, ref_price, forward_minutes):
    if ref_price <= 0: return None
    ts = _parse_timestamp(ref_ts)
    start_ms = int(ts.timestamp() * 1000)
    end_ms = int((ts + timedelta(minutes=forward_minutes + 1)).timestamp() * 1000)
    try:
        bars = sorted(fetch_klines_cached(client.get_klines, symbol=symbol,
                      start_ms=start_ms, end_ms=end_ms,
                      forward_minutes=forward_minutes, cache_dir=KLINE_CACHE),
                      key=lambda x: int(x.get("open_time") or 0))
    except Exception:
        return None
    if not bars: return None
    target_ms = start_ms + forward_minutes * 60_000
    after = [b for b in bars if int(b.get("open_time") or 0) >= target_ms] or [bars[-1]]
    close = _safe_float(after[0].get("close_price"), 0.0)
    if close <= 0: return None
    return (close / ref_price - 1.0) * 10000.0


def _quad(p_up, oi_up):
    if p_up and oi_up: return "newLongs"
    if p_up and not oi_up: return "shortCover"
    if not p_up and oi_up: return "newShorts"
    return "longUnwind"


def main():
    cycles = defaultdict(list)
    cdirs = sorted(SHADOW_ROOT.glob("cycle_*"))
    print(f"loading {len(cdirs)} cycle dirs ...")
    for cdir in cdirs:
        m = cdir / "metrics.json"
        if not m.exists(): continue
        try: payload = json.loads(m.read_text())
        except json.JSONDecodeError: continue
        for row in payload.get("rows", []):
            sym = (row.get("symbol") or "").upper()
            if sym not in (OWN, LEADER): continue
            ts = row.get("timestamp")
            if not ts: continue
            try: ts_ms = int(_parse_timestamp(ts).timestamp() * 1000)
            except Exception: continue
            cycles[sym].append({"ts_ms": ts_ms,
                                "open_interest": _safe_float(row.get("open_interest")),
                                "last_price": _safe_float(row.get("last_price"))})

    for s in (OWN, LEADER):
        cycles[s].sort(key=lambda r: r["ts_ms"])
        print(f"  {s}: {len(cycles[s])}")

    cycle_ts = {s: [r["ts_ms"] for r in cycles[s]] for s in (OWN, LEADER)}

    decisions = []
    with DECISIONS.open() as f:
        for line in f:
            try: d = json.loads(line)
            except json.JSONDecodeError: continue
            if (d.get("symbol") or "").upper() == OWN:
                decisions.append(d)
    print(f"\nloaded {len(decisions)} {OWN} decisions")

    client = build_exchange_rest_client(exchange="bitget", allow_insecure_ssl=True, allow_missing_credentials=True)
    results = []

    for i, d in enumerate(decisions):
        ts_ms = int(_parse_timestamp(d["timestamp"]).timestamp() * 1000)
        ref = _safe_float(d.get("reference_price"))
        if ref <= 0: continue

        idx_self = bisect_left(cycle_ts[OWN], ts_ms) - 1
        if idx_self < 1: continue
        cur, prv = cycles[OWN][idx_self], cycles[OWN][idx_self - 1]
        if min(cur["open_interest"], prv["open_interest"], cur["last_price"], prv["last_price"]) <= 0: continue
        own_quad = _quad((cur["last_price"] / prv["last_price"] - 1) > 0,
                         (cur["open_interest"] / prv["open_interest"] - 1) > 0)

        idx_lead = bisect_left(cycle_ts[LEADER], ts_ms) - 1
        if idx_lead < 1: continue
        lcur, lprv = cycles[LEADER][idx_lead], cycles[LEADER][idx_lead - 1]
        if min(lcur["open_interest"], lprv["open_interest"], lcur["last_price"], lprv["last_price"]) <= 0: continue
        lead_p_d = (lcur["last_price"] / lprv["last_price"] - 1) * 10000.0
        lead_quad = _quad(lead_p_d > 0, (lcur["open_interest"] / lprv["open_interest"] - 1) > 0)
        lead_dir = "up" if lead_p_d > 0 else "down"

        f15 = _forward_ret(client, symbol=OWN, ref_ts=d["timestamp"], ref_price=ref, forward_minutes=15)
        f60 = _forward_ret(client, symbol=OWN, ref_ts=d["timestamp"], ref_price=ref, forward_minutes=60)

        results.append({"own_quad": own_quad, "lead_quad": lead_quad, "lead_dir": lead_dir,
                        "f15": f15, "f60": f60})

    print(f"results: {len(results)}")

    own_only_15, own_only_60 = defaultdict(list), defaultdict(list)
    own_x_dir_15, own_x_dir_60 = defaultdict(list), defaultdict(list)
    own_x_quad_60 = defaultdict(list)
    for r in results:
        if r["f15"] is not None: own_only_15[r["own_quad"]].append(r["f15"])
        if r["f60"] is not None: own_only_60[r["own_quad"]].append(r["f60"])
        k = f"{r['own_quad']}|eth_{r['lead_dir']}"
        if r["f15"] is not None: own_x_dir_15[k].append(r["f15"])
        if r["f60"] is not None: own_x_dir_60[k].append(r["f60"])
        k2 = f"{r['own_quad']}|eth_{r['lead_quad']}"
        if r["f60"] is not None: own_x_quad_60[k2].append(r["f60"])

    out = {
        "n_results": len(results),
        "own": OWN, "leader": LEADER,
        "own_only_f15": {k: _stats(v) for k, v in own_only_15.items()},
        "own_only_f60": {k: _stats(v) for k, v in own_only_60.items()},
        "own_x_eth_dir_f15": {k: _stats(v) for k, v in own_x_dir_15.items()},
        "own_x_eth_dir_f60": {k: _stats(v) for k, v in own_x_dir_60.items()},
        "own_x_eth_quad_f60": {k: _stats(v) for k, v in own_x_quad_60.items()},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
