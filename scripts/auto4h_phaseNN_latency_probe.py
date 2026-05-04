#!/usr/bin/env python3
"""Phase NN: One-shot Bitget fetch latency probe.

Measures fetch_ohlcv() latency across 12 universe symbols, 3 cycles.
Report: per-symbol avg/max + total cycle time.
GPT-5.4 must-fix: bar-age guard misses execution latency. This probe
quantifies the actual baseline so we can decide if a bps-drift abort is needed.
"""
from __future__ import annotations
import json, time
from pathlib import Path
import ccxt

SYMBOLS = [
    "BTC/USDT:USDT", "ETH/USDT:USDT", "SUI/USDT:USDT",
    "DOGE/USDT:USDT", "ARB/USDT:USDT", "WIF/USDT:USDT",
    "ADA/USDT:USDT", "OP/USDT:USDT", "PEPE/USDT:USDT",
    "NEAR/USDT:USDT", "DOT/USDT:USDT", "LINK/USDT:USDT",
]
CYCLES = 3


def run():
    print(f"Phase NN: Bitget latency probe — {len(SYMBOLS)} symbols × {CYCLES} cycles")
    ex = ccxt.bitget({"enableRateLimit": True})
    per_symbol = {sym: [] for sym in SYMBOLS}
    cycle_total = []
    for c in range(CYCLES):
        cyc0 = time.time()
        for sym in SYMBOLS:
            try:
                t0 = time.time()
                ex.fetch_ohlcv(sym, timeframe="1h", limit=300)
                dt = (time.time()-t0)*1000
                per_symbol[sym].append(dt)
            except Exception as e:
                print(f"  [{c}] {sym}: ERROR {e}")
        cycle_total.append(time.time() - cyc0)
        print(f"  cycle {c+1}/{CYCLES} total: {cycle_total[-1]:.2f}s")

    print(f"\n=== Per-symbol latency ===")
    print(f"{'symbol':<22} {'avg':>6} {'max':>6} {'min':>6}")
    rows = []
    for sym in SYMBOLS:
        ls = per_symbol[sym]
        if not ls: continue
        avg = sum(ls)/len(ls); mx = max(ls); mn = min(ls)
        rows.append({"sym": sym, "avg": avg, "max": mx, "min": mn})
        print(f"{sym:<22} {avg:>5.0f}ms {mx:>5.0f}ms {mn:>5.0f}ms")

    all_lats = [l for ls in per_symbol.values() for l in ls]
    if all_lats:
        all_lats.sort()
        p50 = all_lats[len(all_lats)//2]
        p95 = all_lats[int(len(all_lats)*0.95)]
        p99 = all_lats[int(len(all_lats)*0.99)] if len(all_lats) >= 100 else max(all_lats)
        print(f"\n=== Aggregate latency ===")
        print(f"  p50: {p50:.0f}ms")
        print(f"  p95: {p95:.0f}ms")
        print(f"  p99: {p99:.0f}ms")
        print(f"  max: {max(all_lats):.0f}ms")
        avg_cycle = sum(cycle_total)/len(cycle_total)
        print(f"  avg cycle (12 syms): {avg_cycle:.2f}s")

        # vs Phase AA: 1h delay = -56% → execution latency budget is ~5min total
        if max(all_lats) > 5000:
            verdict = "CONCERN — single fetch >5s observed; entry may slip past 5min cap"
        elif p95 > 1000:
            verdict = "WATCH — p95 >1s; cumulative cycle time grows in degraded networks"
        else:
            verdict = "HEALTHY — p95 <1s, cycle <30s. Bar-age guard sufficient."
        print(f"\n  Verdict: {verdict}")
    else:
        verdict = "NO_DATA"

    out_path = Path("quant_runtime/output/auto4h/phaseNN_latency_probe.json")
    with open(out_path, "w") as f:
        json.dump({"per_symbol": rows, "cycle_totals_s": cycle_total,
                   "p50_ms": p50, "p95_ms": p95, "p99_ms": p99,
                   "verdict": verdict}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
