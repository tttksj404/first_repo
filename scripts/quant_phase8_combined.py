#!/usr/bin/env python3
"""Phase 8: Best refined params + BTC regime + time-of-day + capital scaling.

Apex strategy: Phase 6 best (lev4/mp0.75/tp100/sl-15/h48) + BTC RSI<70 filter.

Tests:
  A) Apex variants — combine best refined params with BTC RSI gates
  B) Time-of-day — hour-of-day buckets (0-3, 4-7, 8-11, 12-15, 16-19, 20-23 UTC)
  C) Capital scaling — does same strategy work at $100, $200, $500?
  D) High-funding stress — 0.0002/8h vs 0.0001/8h
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
OUT = ROOT / "quant_runtime" / "master_engine_runs" / "phase8_combined.json"


def rot_gated(priority, cache, p, idx_start, idx_end, gate_fn=lambda i: True,
              equity_override=None, funding_8h=0.0001):
    sig_fn = SIGNALS[p.signal]
    eq = equity_override if equity_override is not None else EQUITY
    margin = eq * p.margin_pct
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
        funding = notional * funding_8h * (hold_hours // 8)
        pnl = margin * (roe / 100.0) - fee - funding
        trades.append(Trade(chosen, side, i, exit_k, hold_hours, pnl, roe))
        i = exit_k + p.cooldown_bars
    return trades


def main():
    t0 = time.time()
    priority = PRIORITY_UNIVERSES["PEPE_DOGE"]
    cache = {s: compute_indicators(load_1h(s)) for s in priority if load_1h(s) is not None}
    btc = compute_indicators(load_1h("BTCUSDT"))
    n_bars = min(len(cache[s]["close"]) for s in cache)
    n_bars = min(n_bars, len(btc["close"]))
    print(f"[load] {n_bars} bars")

    btc_rsi = btc["rsi"][-n_bars:]
    btc_close = btc["close"][-n_bars:]
    btc_atr = btc["atr"][-n_bars:]

    results = {}

    # ==== A) Apex variants ====
    apex_configs = [
        ("phase6_best", dict(signal="x1", long_only=False, lev=4, margin_pct=0.75, tp_roe=100, sl_roe=-15, abort_roe=-20, hold_h=48)),
        ("phase4b_best", dict(signal="x1", long_only=False, lev=5, margin_pct=0.5, tp_roe=100, sl_roe=-15, abort_roe=-20, hold_h=48)),
        ("phase6_safest", dict(signal="x1", long_only=False, lev=8, margin_pct=0.4, tp_roe=120, sl_roe=-12, abort_roe=-17, hold_h=72)),
    ]
    btc_gates = {
        "no_filter": lambda i: True,
        "btc_rsi_neutral": lambda i: 30 < btc_rsi[i] < 70,
        "btc_not_overbought": lambda i: btc_rsi[i] < 70,
        "btc_not_extreme": lambda i: 25 < btc_rsi[i] < 75,
    }
    print("\n=== A) APEX VARIANTS (params × BTC filter) ===")
    print(f"{'config':<20s} {'gate':<22s} {'N':>3s} {'WR%':>5s} {'PF':>5s} {'PnL$':>8s} {'%/yr':>7s} {'DD':>6s} {'ruin%':>6s}")
    for cfg_name, cfg in apex_configs:
        for g_name, gate in btc_gates.items():
            p = RotationParams(**cfg)
            tr = rot_gated(priority, cache, p, 200, n_bars, gate)
            agg = aggregate(tr)
            mc = mc_ruin(tr, n_runs=5000) if agg["n"] >= 5 else {"ruin_pct": 0}
            key = f"A:{cfg_name}:{g_name}"
            results[key] = {**agg, "ruin_pct": mc["ruin_pct"], "config": cfg, "gate": g_name}
            pf = agg.get("pf"); pf_s = f"{pf:.2f}" if isinstance(pf, (int, float)) else "-"
            print(f"{cfg_name:<20s} {g_name:<22s} {agg['n']:>3d} {agg['wr']*100:>4.1f} {pf_s:>5s} ${agg['total_pnl']:>+6.2f} {agg['annual_pct']:>+6.1f} ${agg['max_dd']:>4.1f} {mc['ruin_pct']:>5.2f}")

    # ==== B) Time-of-day filter on phase6_best ====
    print("\n=== B) TIME-OF-DAY (hour-of-day filter) ===")
    # For each bar, compute hour-of-day from open_time (assume hourly aligned)
    # Use first symbol's time
    arr0 = load_1h(priority[0])
    times = arr0[-n_bars:, 0]  # ms
    hours = ((times // 3600000) % 24).astype(int)

    p = RotationParams(signal="x1", long_only=False, lev=4, margin_pct=0.75, tp_roe=100, sl_roe=-15, abort_roe=-20, hold_h=48)
    print(f"{'hour_filter':<28s} {'N':>3s} {'WR%':>5s} {'PnL$':>8s} {'%/yr':>7s} {'ruin%':>6s}")
    tod_gates = {
        "all_hours": lambda i: True,
        "asia_session_0_8": lambda i: 0 <= hours[i] < 8,
        "us_session_12_20": lambda i: 12 <= hours[i] < 20,
        "eu_session_8_16": lambda i: 8 <= hours[i] < 16,
        "off_hours_20_4": lambda i: hours[i] >= 20 or hours[i] < 4,
        "us_open_13_17": lambda i: 13 <= hours[i] < 17,  # NY open
        "asia_late_22_2": lambda i: hours[i] >= 22 or hours[i] < 2,
    }
    for g_name, gate in tod_gates.items():
        tr = rot_gated(priority, cache, p, 200, n_bars, gate)
        agg = aggregate(tr)
        mc = mc_ruin(tr, n_runs=3000) if agg["n"] >= 5 else {"ruin_pct": 0}
        results[f"B:tod:{g_name}"] = {**agg, "ruin_pct": mc["ruin_pct"]}
        print(f"{g_name:<28s} {agg['n']:>3d} {agg['wr']*100:>4.1f} ${agg['total_pnl']:>+6.2f} {agg['annual_pct']:>+6.1f} {mc['ruin_pct']:>5.2f}")

    # ==== C) Capital scaling ====
    print("\n=== C) CAPITAL SCALING (does it work at higher equity?) ===")
    print(f"{'equity':<10s} {'margin':<8s} {'notional':<10s} {'N':>3s} {'PnL$':>8s} {'PnL%':>6s} {'ruin%':>6s}")
    for eq in [50, 100, 200, 500, 1000]:
        p = RotationParams(signal="x1", long_only=False, lev=4, margin_pct=0.75, tp_roe=100, sl_roe=-15, abort_roe=-20, hold_h=48)
        tr = rot_gated(priority, cache, p, 200, n_bars, lambda i: btc_rsi[i] < 70, equity_override=eq)
        agg = aggregate(tr)
        mc = mc_ruin(tr, n_runs=3000) if agg["n"] >= 5 else {"ruin_pct": 0}
        results[f"C:eq{eq}"] = {**agg, "ruin_pct": mc["ruin_pct"], "equity": eq}
        margin = eq * 0.75; notional = margin * 4
        print(f"${eq:<8d} ${margin:<7.0f} ${notional:<8.0f} {agg['n']:>3d} ${agg['total_pnl']:>+7.2f} {agg['total_pnl']/eq*100:>+5.1f}% {mc['ruin_pct']:>5.2f}")

    # ==== D) High-funding stress ====
    print("\n=== D) FUNDING STRESS (8h funding rate amplification) ===")
    print(f"{'fund_8h':<10s} {'N':>3s} {'PnL$':>8s} {'%/yr':>7s} {'ruin%':>6s}")
    for fund in [0.0001, 0.00015, 0.0002, 0.0003, 0.0005]:
        p = RotationParams(signal="x1", long_only=False, lev=4, margin_pct=0.75, tp_roe=100, sl_roe=-15, abort_roe=-20, hold_h=48)
        tr = rot_gated(priority, cache, p, 200, n_bars, lambda i: btc_rsi[i] < 70, funding_8h=fund)
        agg = aggregate(tr)
        mc = mc_ruin(tr, n_runs=3000) if agg["n"] >= 5 else {"ruin_pct": 0}
        results[f"D:fund{fund}"] = {**agg, "ruin_pct": mc["ruin_pct"], "funding_8h": fund}
        print(f"{fund:<10.5f} {agg['n']:>3d} ${agg['total_pnl']:>+6.2f} {agg['annual_pct']:>+6.1f} {mc['ruin_pct']:>5.2f}")

    OUT.write_text(json.dumps(results, indent=2, default=str))
    print(f"\n[done] {time.time()-t0:.0f}s, saved: {OUT}")


if __name__ == "__main__":
    main()
