#!/usr/bin/env python3
"""Phase 7: BTC regime overlay on the SAFE winner.

Tests whether adding BTC-state gates improves robustness:
  - "btc_above_ema50": only trade when BTC close > BTC EMA50
  - "btc_above_ema20": tighter trend
  - "btc_uptrend": EMA20 > EMA50
  - "btc_low_vol": ATR/close < 0.025
  - "btc_not_extreme": ADX < 35 (avoid panic moves)
  - "btc_rsi_neutral": 30 < RSI < 70

Winner config: x1 / PEPE_DOGE / lv5 / mp0.5 / tp100 / sl-15 / h48 / lo=False
"""
from __future__ import annotations

import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import (  # type: ignore
    RotationParams, aggregate, mc_ruin, load_1h, compute_indicators,
    PRIORITY_UNIVERSES, EQUITY, SIGNALS, COST_RT, Trade,
)
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quant_runtime" / "master_engine_runs" / "phase7_btc_regime.json"


def rotation_backtest_gated(priority, data_cache, p, idx_start, idx_end, gate_fn):
    """Same as rotation_backtest but only enters when gate_fn(i) returns True."""
    sig_fn = SIGNALS[p.signal]
    margin = EQUITY * p.margin_pct
    notional = margin * p.lev
    fee = notional * (COST_RT + 2 * p.extra_bps / 10000.0)
    valid = [s for s in priority if s in data_cache]
    if not valid: return []
    n = min(len(data_cache[s]["close"]) for s in valid)
    idx_end = min(idx_end or n, n - p.hold_h - 2)

    trades = []
    i = max(idx_start, 200)
    while i < idx_end:
        if not gate_fn(i):
            i += 1; continue
        chosen = None; side = 0
        for s in valid:
            ind = data_cache[s]
            sd = sig_fn(ind, i, p.long_only)
            if sd != 0:
                chosen = s; side = sd; break
        if chosen is None:
            i += 1; continue

        ind = data_cache[chosen]
        e = i + 1
        if e >= n: break
        entry_px = ind["close"][i]
        if entry_px <= 0:
            i += 1; continue

        tp_pct = p.tp_roe / 100.0 / p.lev
        sl_pct = p.sl_roe / 100.0 / p.lev
        abort_pct = p.abort_roe / 100.0 / p.lev
        tp_px = entry_px * (1 + side * tp_pct)
        sl_px = entry_px * (1 + side * sl_pct)
        abort_px = entry_px * (1 + side * abort_pct)

        exit_px = None; exit_k = None
        for k in range(e, min(e + p.hold_h, n)):
            hi = ind["high"][k]; lo = ind["low"][k]
            if side == 1:
                if lo <= sl_px: exit_px, exit_k = sl_px, k; break
                if hi >= tp_px: exit_px, exit_k = tp_px, k; break
            else:
                if hi >= sl_px: exit_px, exit_k = sl_px, k; break
                if lo <= tp_px: exit_px, exit_k = tp_px, k; break
        if exit_px is None:
            exit_k = min(e + p.hold_h - 1, n - 1)
            exit_px = ind["close"][exit_k]
        roe = side * (exit_px / entry_px - 1) * p.lev * 100
        hold_hours = max(1, exit_k - i)
        funding = notional * 0.0001 * (hold_hours // 8)
        pnl = margin * (roe / 100.0) - fee - funding
        trades.append(Trade(chosen, side, i, exit_k, hold_hours, pnl, roe))
        i = exit_k + p.cooldown_bars
    return trades


def main():
    t0 = time.time()
    # Load BTC and PEPE_DOGE data
    priority = PRIORITY_UNIVERSES["PEPE_DOGE"]
    cache = {}
    for s in priority:
        a = load_1h(s)
        if a is None: continue
        cache[s] = compute_indicators(a)
    btc_arr = load_1h("BTCUSDT")
    btc = compute_indicators(btc_arr)
    n_bars = min(len(cache[s]["close"]) for s in cache)
    n_bars = min(n_bars, len(btc["close"]))
    print(f"[load] {len(cache)} alts + BTC, {n_bars} bars")

    # Winner config
    p = RotationParams(signal="x1", long_only=False, lev=5, margin_pct=0.5,
                       tp_roe=100, sl_roe=-15, abort_roe=-20, hold_h=48)

    # Pre-compute BTC features over the bar window
    btc_close = btc["close"][-n_bars:]
    btc_ema20 = btc["ema20"][-n_bars:]
    btc_ema50 = btc["ema50"][-n_bars:]
    btc_atr = btc["atr"][-n_bars:]
    btc_rsi = btc["rsi"][-n_bars:]
    btc_adx = btc["adx"][-n_bars:]

    # Align: assume BTC and alts are sampled at same time; if not, this could be wrong
    # but for our purposes we'll use index-aligned (close enough for trend filter)

    gates = {
        "baseline_no_filter": lambda i: True,
        "btc_above_ema50": lambda i: btc_close[i] > btc_ema50[i],
        "btc_above_ema20": lambda i: btc_close[i] > btc_ema20[i],
        "btc_uptrend": lambda i: btc_ema20[i] > btc_ema50[i],
        "btc_low_vol": lambda i: btc_atr[i] / max(btc_close[i], 1) < 0.025,
        "btc_high_vol": lambda i: btc_atr[i] / max(btc_close[i], 1) > 0.018,  # high-vol regime preferred
        "btc_not_extreme_adx": lambda i: btc_adx[i] < 35,
        "btc_rsi_neutral": lambda i: 30 < btc_rsi[i] < 70,
        "btc_not_overbought": lambda i: btc_rsi[i] < 70,
        "btc_oversold_or_normal": lambda i: btc_rsi[i] < 65,
        "btc_uptrend_AND_low_vol": lambda i: btc_ema20[i] > btc_ema50[i] and btc_atr[i] / max(btc_close[i], 1) < 0.025,
        "btc_uptrend_AND_rsi_neutral": lambda i: btc_ema20[i] > btc_ema50[i] and 30 < btc_rsi[i] < 70,
    }

    results = {}
    for name, gate in gates.items():
        trades = rotation_backtest_gated(priority, cache, p, 200, n_bars, gate)
        agg = aggregate(trades)
        mc = mc_ruin(trades, n_runs=5000) if agg["n"] >= 5 else {"ruin_pct": 0, "median_final": 0}
        results[name] = {**agg, "ruin_pct": mc["ruin_pct"], "median_final": mc.get("median_final", 0)}
        print(f"{name:<32s} N={agg['n']:>3d} WR={agg['wr']*100:>4.1f}% PF={agg.get('pf'):.2f} pnl=${agg['total_pnl']:>+6.2f} ({agg['annual_pct']:>+5.1f}%/yr) DD=${agg['max_dd']:>5.2f} ruin={mc['ruin_pct']:.2f}%" if isinstance(agg.get('pf'),(int,float)) else f"{name:<32s} N={agg['n']:>3d} pnl=${agg['total_pnl']:>+6.2f}")

    # Save
    OUT.write_text(json.dumps(results, indent=2, default=str))
    print(f"\n[done] {time.time()-t0:.0f}s, saved: {OUT}")

    # Identify winners
    print(f"\n{'='*100}\nBTC REGIME RANKING (by score: pnl × (1-ruin/100))\n{'='*100}")
    ranked = sorted(results.items(),
                    key=lambda kv: -kv[1]["total_pnl"] * (1 - kv[1]["ruin_pct"] / 100))
    for name, r in ranked:
        print(f"  {name:<32s} score={r['total_pnl']*(1-r['ruin_pct']/100):>+7.2f}  pnl=${r['total_pnl']:>+6.2f} ruin={r['ruin_pct']:>4.1f}% N={r['n']}")


if __name__ == "__main__":
    main()
