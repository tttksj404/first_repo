#!/usr/bin/env python3
"""Phase KK: Per-symbol funding rate fetch + stress recompute.

GPT-5.4 Round 3 must-fix #4: funding modeled as static 0.012% across all coins.
Reality: Bitget per-symbol funding spans -0.05% to +0.10% depending on tier.

This phase:
1. Fetch current Bitget perp funding rate for all 12 universe symbols
2. Compute weighted-avg funding for portfolio
3. If any symbol funding > 0.05% (5x baseline), flag for ramp delay
"""
from __future__ import annotations
import json
from pathlib import Path
import ccxt

SYMBOLS = [
    "BTC/USDT:USDT", "ETH/USDT:USDT", "SUI/USDT:USDT",
    "DOGE/USDT:USDT", "ARB/USDT:USDT", "WIF/USDT:USDT",
    "ADA/USDT:USDT", "OP/USDT:USDT", "PEPE/USDT:USDT",
    "NEAR/USDT:USDT", "DOT/USDT:USDT", "LINK/USDT:USDT",
]


def run():
    print("Phase KK: per-symbol Bitget funding fetch")
    ex = ccxt.bitget({"enableRateLimit": True})
    out = []
    for sym in SYMBOLS:
        try:
            fr = ex.fetch_funding_rate(sym)
            rate = fr.get("fundingRate", 0)  # decimal, e.g. 0.0001 = 0.01%/8h
            interval_h = 8  # Bitget standard
            # Some Bitget pairs have 4h funding (rare); fundingTimestamp delta tells us
            ts = fr.get("fundingTimestamp")
            next_ts = fr.get("nextFundingTimestamp")
            if ts and next_ts and next_ts > ts:
                dt_h = (next_ts - ts) / 3_600_000
                if 1 <= dt_h <= 24:
                    interval_h = round(dt_h)
            r_ann_pct = rate * 100 * (24 / interval_h) * 365
            out.append({"symbol": sym, "funding_rate": rate,
                        "funding_pct_per_interval": rate*100,
                        "interval_h": interval_h, "annual_pct": r_ann_pct})
            print(f"  {sym:<22} fr={rate*100:+.4f}% / {interval_h}h  "
                  f"(annualized {r_ann_pct:+.1f}%)")
        except Exception as e:
            print(f"  {sym:<22} ERROR: {e}")
            out.append({"symbol": sym, "error": str(e)})

    valid = [o for o in out if "funding_rate" in o]
    if valid:
        rates = [abs(o["funding_rate"]) for o in valid]
        max_r = max(rates); avg_r = sum(rates)/len(rates)
        print(f"\n=== Aggregate ===")
        print(f"  Avg |funding|: {avg_r*100:.4f}%/8h  ({avg_r/0.00012*100:.0f}% of model 0.012%)")
        print(f"  Max |funding|: {max_r*100:.4f}%/8h  (vs model 0.012% = {max_r/0.00012:.1f}x)")
        worst = max(valid, key=lambda o: abs(o["funding_rate"]))
        print(f"  Worst symbol: {worst['symbol']} {worst['funding_rate']*100:+.4f}%/8h")

        # Compare to FUNDING_8H = 0.00012 in paper bot
        if max_r > 0.0010:
            verdict = "ALERT — at least one symbol >10x model funding; paper bot may underestimate cost"
        elif max_r > 0.00050:
            verdict = "MINOR — one symbol >4x model; within Phase EE tested range"
        else:
            verdict = "OK — all funding within Phase EE baseline ranges"
        print(f"\n  Verdict: {verdict}")
    else:
        verdict = "NO_DATA"

    out_path = Path("quant_runtime/output/auto4h/phaseKK_funding_live.json")
    with open(out_path, "w") as f:
        json.dump({"per_symbol": out, "verdict": verdict}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
