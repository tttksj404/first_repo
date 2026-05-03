#!/usr/bin/env python3
"""Phase SS: Bitget orderbook depth probe — validate 8bps slippage assumption.

For each universe symbol, fetch L2 orderbook and simulate market buy/sell
of $500 notional (= MARGIN $50 × 10x leverage). Measure VWAP slippage vs mid.

If model 8bps > observed worst case → conservative (no fix).
If observed > 8bps → bump SLIPPAGE_BPS to p95 + 5bps margin.

Captures snapshots at 3 timestamps (10s apart) to smooth microstructure.
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
NOTIONAL_USD = 500.0
SNAPSHOTS = 3


def vwap_slippage(orderbook: dict, side: str, notional: float) -> float | None:
    """Walk one side of book for `notional` USD. Return VWAP slippage in bps vs mid."""
    bids = orderbook.get("bids", []); asks = orderbook.get("asks", [])
    if not bids or not asks: return None
    mid = (bids[0][0] + asks[0][0]) / 2.0
    levels = asks if side == "buy" else bids
    filled_qty = 0.0; filled_usd = 0.0
    for px, sz in levels:
        if px is None or sz is None: continue
        level_usd = px * sz
        need_usd = notional - filled_usd
        if need_usd <= 0: break
        if level_usd >= need_usd:
            qty = need_usd / px
            filled_qty += qty; filled_usd += need_usd
            break
        else:
            filled_qty += sz; filled_usd += level_usd
    if filled_usd < notional * 0.99:
        return None  # not enough depth
    vwap = filled_usd / filled_qty
    bps = abs(vwap - mid) / mid * 1e4
    return bps


def run():
    print(f"Phase SS: orderbook depth probe — {len(SYMBOLS)} syms × {SNAPSHOTS} snapshots, ${NOTIONAL_USD:.0f}")
    ex = ccxt.bitget({"options": {"defaultType": "swap"}, "enableRateLimit": True})
    rows = []
    for sym in SYMBOLS:
        buy_bps = []; sell_bps = []
        for k in range(SNAPSHOTS):
            try:
                ob = ex.fetch_order_book(sym, limit=50)
                b = vwap_slippage(ob, "buy", NOTIONAL_USD)
                s = vwap_slippage(ob, "sell", NOTIONAL_USD)
                if b is not None: buy_bps.append(b)
                if s is not None: sell_bps.append(s)
                if k < SNAPSHOTS-1: time.sleep(10)
            except Exception as e:
                print(f"  {sym} ERR: {e}")
                break
        if not buy_bps or not sell_bps:
            print(f"  {sym}: insufficient data")
            continue
        avg_b = sum(buy_bps)/len(buy_bps); avg_s = sum(sell_bps)/len(sell_bps)
        worst = max(max(buy_bps), max(sell_bps))
        rows.append({"sym": sym, "avg_buy_bps": avg_b, "avg_sell_bps": avg_s,
                     "worst_bps": worst, "n_snap": min(len(buy_bps), len(sell_bps))})
        print(f"  {sym:<22} buy~{avg_b:.2f}bps sell~{avg_s:.2f}bps  worst={worst:.2f}bps")

    if not rows:
        print("\n  [empty] no rows captured")
        return
    all_bps = [r["worst_bps"] for r in rows]
    all_avg = [(r["avg_buy_bps"]+r["avg_sell_bps"])/2 for r in rows]
    p50 = sorted(all_avg)[len(all_avg)//2]
    p95 = sorted(all_bps)[int(len(all_bps)*0.95)] if len(all_bps) >= 5 else max(all_bps)
    worst = max(all_bps)
    print(f"\n=== Aggregate slippage ({NOTIONAL_USD:.0f} USD) ===")
    print(f"  median (avg buy+sell)/2: {p50:.2f}bps")
    print(f"  p95 worst:               {p95:.2f}bps")
    print(f"  worst:                   {worst:.2f}bps")
    print(f"  model SLIPPAGE_BPS = 8")

    if worst <= 8:
        verdict = f"CONSERVATIVE — observed worst {worst:.2f}bps ≤ model 8bps. No change needed."
    elif p95 <= 8:
        verdict = f"OK — p95 {p95:.2f}bps ≤ 8bps but tail extends to {worst:.2f}bps. Watch."
    elif worst <= 15:
        verdict = f"BUMP TO 12bps — observed {worst:.2f}bps; recommend SLIPPAGE_BPS = 12."
    else:
        verdict = f"BUMP TO {int(p95)+5}bps — observed worst {worst:.2f}bps far exceeds 8bps."
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseSS_orderbook_depth.json")
    with open(out_path, "w") as f:
        json.dump({"per_symbol": rows, "p50_avg_bps": p50, "p95_worst_bps": p95,
                   "worst_bps": worst, "verdict": verdict,
                   "notional_usd": NOTIONAL_USD}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
