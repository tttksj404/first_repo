#!/usr/bin/env python3
"""Phase 10: Direct apples-to-apples — Original 30x rotation vs APEX.

Original = strategy_override.rotation_30x_candidate.json mapped to engine:
  signal: turnaround (long-only, since long_only_turnaround_mode=true)
  universe: rotation_30x_orig (PEPE→DOGE→ETH→SOL)
  lev: 30
  margin_pct: 0.35
  tp_roe: 30, sl_roe: -10, abort_roe: -16
  hold: 48h
  long_only: true

APEX = x1 / PEPE_DOGE / lv4 / mp0.75 / tp100 / sl-15 / h48 / lo=False + BTC RSI<70

Compare side-by-side. Also test "modified original" variants with the engine's signals.
"""
from __future__ import annotations

import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import (  # type: ignore
    RotationParams, aggregate, mc_ruin, load_1h, compute_indicators,
    rotation_backtest, PRIORITY_UNIVERSES, EQUITY, SIGNALS, COST_RT, Trade,
)
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quant_runtime" / "master_engine_runs" / "phase10_compare.json"


def rot_gated(priority, cache, p, idx_start, idx_end, gate_fn=lambda i: True):
    sig_fn = SIGNALS[p.signal]
    margin = EQUITY * p.margin_pct
    notional = margin * p.lev
    fee = notional * (COST_RT + 2 * p.extra_bps / 10000.0)
    valid = [s for s in priority if s in cache]
    if not valid: return []
    n = min(len(cache[s]["close"]) for s in valid)
    idx_end = min(idx_end or n, n - p.hold_h - 2)
    trades = []
    i = max(idx_start, 200)
    while i < idx_end:
        if not gate_fn(i):
            i += 1; continue
        chosen = None; side = 0
        for s in valid:
            sd = sig_fn(cache[s], i, p.long_only)
            if sd != 0:
                chosen = s; side = sd; break
        if chosen is None:
            i += 1; continue
        ind = cache[chosen]
        e = i + 1
        if e >= n: break
        entry_px = ind["close"][i]
        if entry_px <= 0:
            i += 1; continue
        tp_pct = p.tp_roe / 100.0 / p.lev
        sl_pct = p.sl_roe / 100.0 / p.lev
        tp_px = entry_px * (1 + side * tp_pct)
        sl_px = entry_px * (1 + side * sl_pct)
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
    # Load all needed (PEPE, DOGE, ETH, SOL, BTC)
    syms = list(set(PRIORITY_UNIVERSES["rotation_30x_orig"] + PRIORITY_UNIVERSES["PEPE_DOGE"]))
    cache = {s: compute_indicators(load_1h(s)) for s in syms if load_1h(s) is not None}
    btc = compute_indicators(load_1h("BTCUSDT"))
    n_bars = min(len(cache[s]["close"]) for s in cache)
    n_bars = min(n_bars, len(btc["close"]))
    btc_rsi = btc["rsi"][-n_bars:]
    print(f"[load] {len(cache)} syms × {n_bars} bars")

    configs = [
        ("ORIGINAL_lev30_turnaround", "rotation_30x_orig", dict(signal="turnaround", long_only=True, lev=30, margin_pct=0.35, tp_roe=30, sl_roe=-10, abort_roe=-16, hold_h=48), False),
        ("ORIGINAL_lev30_x1", "rotation_30x_orig", dict(signal="x1", long_only=True, lev=30, margin_pct=0.35, tp_roe=30, sl_roe=-10, abort_roe=-16, hold_h=48), False),
        ("ORIGINAL_lev30_combined", "rotation_30x_orig", dict(signal="combined", long_only=True, lev=30, margin_pct=0.35, tp_roe=30, sl_roe=-10, abort_roe=-16, hold_h=48), False),
        ("MODIFIED_lev10_x1", "rotation_30x_orig", dict(signal="x1", long_only=False, lev=10, margin_pct=0.35, tp_roe=100, sl_roe=-15, abort_roe=-20, hold_h=48), False),
        ("APEX_lev4_x1_no_filter", "PEPE_DOGE", dict(signal="x1", long_only=False, lev=4, margin_pct=0.75, tp_roe=100, sl_roe=-15, abort_roe=-20, hold_h=48), False),
        ("APEX_lev4_x1_btc_filter", "PEPE_DOGE", dict(signal="x1", long_only=False, lev=4, margin_pct=0.75, tp_roe=100, sl_roe=-15, abort_roe=-20, hold_h=48), True),
    ]

    print(f"\n{'name':<32s} {'univ':<20s} {'sig':<11s} {'lev':>3s} {'mp':>5s} {'N':>3s} {'WR%':>5s} {'PF':>5s} {'PnL$':>9s} {'%/yr':>7s} {'DD$':>6s} {'ruin%':>6s} {'WF':>4s}")
    out = {}
    for name, univ, cfg, use_btc in configs:
        priority = PRIORITY_UNIVERSES[univ]
        p = RotationParams(**cfg)
        gate = (lambda i: btc_rsi[i] < 70) if use_btc else (lambda i: True)
        # Full year
        tr = rot_gated(priority, cache, p, 200, n_bars, gate)
        agg = aggregate(tr)
        mc = mc_ruin(tr, n_runs=10000) if agg["n"] >= 5 else {"ruin_pct": 0}
        # WF
        wf = 0
        fs = n_bars // 4
        for k in range(4):
            s = k * fs; e = (k + 1) * fs if k < 3 else n_bars
            atr = aggregate(rot_gated(priority, cache, p, s, e, gate))
            if atr["total_pnl"] > 0: wf += 1
        out[name] = {**agg, "ruin_pct": mc["ruin_pct"], "wf_pass": wf, "config": cfg, "univ": univ}
        pf = agg.get("pf"); pf_s = f"{pf:.2f}" if isinstance(pf, (int, float)) else "-"
        print(f"{name:<32s} {univ:<20s} {cfg['signal']:<11s} {cfg['lev']:>3d} {cfg['margin_pct']:>5.2f} {agg['n']:>3d} {agg['wr']*100:>4.1f} {pf_s:>5s} ${agg['total_pnl']:>+7.2f} {agg['annual_pct']:>+6.1f} ${agg['max_dd']:>4.1f} {mc['ruin_pct']:>5.2f} {wf}/4")

    Path(OUT).write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[done] {time.time()-t0:.0f}s, saved: {OUT}")


if __name__ == "__main__":
    main()
