#!/usr/bin/env python3
"""Phase 17: Validate momentum_obv (best new candidate +$1275/yr) + find sweet-spot mp + regime filter.

Phase 16 found:
  - All top candidates fail WF 2/4 with MC ruin 76-91% at mp=1.0 (full margin)
  - Only E (breakout_tp200_PEPE) passes WF 4/4 but ruin still 76%
  - momentum_obv + tp500_sl50 + memes: NEW best, +$1275/yr — needs full robustness check
  - mp=0.10~0.15 brings ruin to 36-50% with +212~318%/yr (한탕 with controlled ruin)

This phase:
  1. Full robustness on momentum_obv (the new best)
  2. mp grid 0.05~1.0 with full ruin curve
  3. BTC RSI / volatility regime filter to fix WF f2/f3 failure
  4. Final TOP-3 production-ready picks
"""
from __future__ import annotations

import json, sys, time
from dataclasses import dataclass, field, replace
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import (  # type: ignore
    load_1h, compute_indicators, EQUITY, COST_RT, FUNDING_8H, Trade,
)
from quant_phase14_production_sim import (
    compute_production_features, ExitConfig, simulate_trade_exit, aggregate_with_dist
)
from quant_phase15_signal_library import (
    add_extra_features, backtest_signal, entry_momentum_continuation,
    entry_breakout_volexp, entry_squeeze_release
)
from quant_phase16_robustness import (
    add_obv, entry_momentum_obv, entry_obv_breakout, wf_4fold,
    backtest_with_slip, mc_ruin_simulation
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quant_runtime" / "master_engine_runs" / "phase17_final.json"


def backtest_with_regime_gate(priority, cache, entry_fn, ec, lev, mp, btc_rsi, btc_vol_regime,
                                gate_fn, idx_start=200, cooldown_h=12, loss_cooldown_h=24):
    """Backtest with arbitrary regime gate (function of bar index)."""
    valid = [s for s in priority if s in cache]
    if not valid: return []
    n = min(len(cache[s]["close"]) for s in valid)
    n = min(n, len(btc_rsi))
    idx_end = n - ec.max_hold_h - 2
    trades = []
    last_loss_h = -1e9; last_exit_h = -1e9
    i = max(idx_start, 200)
    while i < idx_end:
        if i - last_loss_h < loss_cooldown_h:
            i += 1; continue
        if i - last_exit_h < cooldown_h:
            i += 1; continue
        if not gate_fn(i):
            i += 1; continue
        chosen = None; side = 0
        for s in valid:
            ind = cache[s]
            sd = entry_fn(ind, i, True)
            if sd != 0:
                chosen = s; side = sd; break
        if chosen is None:
            i += 1; continue
        ind = cache[chosen]
        margin = EQUITY * mp
        notional = margin * lev
        fee = notional * COST_RT
        realized_roe, exit_idx, exit_reason = simulate_trade_exit(
            ind, i, side=side, lev=lev, margin=margin, ec=ec, n=n
        )
        hold_h = max(1, exit_idx - i)
        funding = notional * FUNDING_8H * (hold_h // 8)
        pnl = margin * (realized_roe / 100.0) - fee - funding
        trades.append(Trade(chosen, side, i, exit_idx, hold_h, pnl, realized_roe))
        if pnl < 0:
            last_loss_h = exit_idx
        last_exit_h = exit_idx
        i = exit_idx + ec.cooldown_bars
    return trades


def main():
    t0 = time.time()
    syms = ["PEPEUSDT", "DOGEUSDT", "WIFUSDT", "ETHUSDT", "SOLUSDT", "BTCUSDT"]
    cache = {}
    for s in syms:
        arr = load_1h(s)
        if arr is None: continue
        ind = compute_indicators(arr)
        ind = compute_production_features(ind)
        ind = add_extra_features(ind)
        ind = add_obv(ind)
        cache[s] = ind
    n_bars = min(len(v["close"]) for v in cache.values())
    btc_ind = cache["BTCUSDT"]
    btc_rsi = btc_ind["rsi"][-n_bars:]
    btc_atr = btc_ind["atr"][-n_bars:]
    btc_close = btc_ind["close"][-n_bars:]
    # BTC volatility percentile (rolling 100-bar)
    btc_atr_pct = np.zeros(n_bars)
    for i in range(20, n_bars):
        s = max(0, i-100)
        btc_atr_pct[i] = (btc_atr[s:i+1] <= btc_atr[i]).mean()
    print(f"[load] {len(cache)} syms × {n_bars} bars  ({time.time()-t0:.1f}s)")

    universes = {
        "memes":       ["PEPEUSDT", "WIFUSDT", "DOGEUSDT"],
        "memes_first": ["PEPEUSDT", "WIFUSDT", "DOGEUSDT", "SOLUSDT"],
        "PEPE_only":   ["PEPEUSDT"],
    }
    tp500_sl50 = ExitConfig(tp_ladder_roe=(500,500,500,500), tp_ladder_fraction=1.0,
                             profit_protect_arm_roe=999, sl_roe=-50, max_hold_h=96)
    tp200_sl50 = ExitConfig(tp_ladder_roe=(200,200,200,200), tp_ladder_fraction=1.0,
                             profit_protect_arm_roe=999, sl_roe=-50, max_hold_h=72)

    # ===== 1) Full robustness on momentum_obv (NEW best from Phase 16) =====
    print(f"\n{'='*120}\n=== momentum_obv robustness (NEW BEST: +$1275/yr) ===\n{'='*120}")
    for univ_name in ["memes", "memes_first", "PEPE_only"]:
        priority = universes[univ_name]
        if not all(s in cache for s in priority): continue
        for ec_name, ec in [("tp500_sl50", tp500_sl50), ("tp200_sl50", tp200_sl50)]:
            trades, _ = backtest_signal(priority, cache, entry_momentum_obv, ec, lev=30.0, mp=1.0)
            agg = aggregate_with_dist(trades) if trades else {"n":0}
            if agg["n"] < 5: continue
            # WF
            wf = wf_4fold(priority, cache, entry_momentum_obv, ec, lev=30.0, mp=1.0)
            wf_p = sum(1 for f in wf if f and f.get("total_pnl",0)>0)
            # MC
            mc = mc_ruin_simulation(trades, equity=EQUITY, ruin_thresh=0.5, n_runs=10000)
            print(f"\n  univ={univ_name:<12s} exit={ec_name}: N={agg['n']:3d} WR={agg['wr']*100:.1f}% "
                  f"PnL=${agg['total_pnl']:.0f} p500={agg['p_win_500']*100:.1f}%")
            print(f"    WF: ", end="")
            for k,f in enumerate(wf):
                m = "✓" if f and f.get("total_pnl",0)>0 else "✗"
                print(f"f{k}={m}${f.get('total_pnl',0):>+5.0f}(N{f.get('n',0)}) ", end="")
            print(f"  {wf_p}/4")
            print(f"    MC ruin: {mc['ruin_pct']:.1f}%   max_dd: ${agg['max_dd']:.0f}")

    # ===== 2) mp grid + ruin curve for momentum_obv on memes =====
    print(f"\n{'='*120}\n=== mp grid (Kelly-style sizing curve): momentum_obv + tp500_sl50 + memes ===\n{'='*120}")
    print(f"{'mp':<6s} {'margin':<8s} {'notional':<10s} {'N':>3s} {'WR%':>5s} "
          f"{'PnL$':>8s} {'%/yr':>6s} {'maxDD$':>8s} {'ruin%':>6s} {'EV$':>7s}")
    mp_results = []
    for mp in [0.05, 0.075, 0.10, 0.125, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75, 1.00]:
        trades, _ = backtest_signal(universes["memes"], cache, entry_momentum_obv,
                                     tp500_sl50, lev=30.0, mp=mp)
        agg = aggregate_with_dist(trades) if trades else {"n":0,"total_pnl":0,"max_dd":0,"wr":0,"ev_pnl":0}
        mc = mc_ruin_simulation(trades, equity=EQUITY, ruin_thresh=0.5, n_runs=10000) if trades else {"ruin_pct":0}
        margin = EQUITY*mp; notional = margin*30
        annual_pct = agg["total_pnl"]/EQUITY*100
        mp_results.append({"mp":mp,"margin":margin,"notional":notional,"n":agg["n"],
                           "wr":agg["wr"],"pnl":agg["total_pnl"],"max_dd":agg["max_dd"],
                           "ruin":mc["ruin_pct"],"annual_pct":annual_pct,"ev":agg["ev_pnl"]})
        print(f"{mp:<6.3f} ${margin:<7.2f} ${notional:<8.0f} {agg['n']:>3d} {agg['wr']*100:>4.1f} "
              f"${agg['total_pnl']:>+6.2f} {annual_pct:>+5.0f}% ${agg['max_dd']:>6.1f} "
              f"{mc['ruin_pct']:>5.1f}% ${agg['ev_pnl']:>+5.2f}")

    # ===== 3) BTC regime filter — fix WF f2/f3 fail =====
    print(f"\n{'='*120}\n=== BTC regime filter for momentum_obv (fix late-period failure) ===\n{'='*120}")
    print(f"{'gate':<28s} {'N':>3s} {'PnL$':>8s} {'ruin%':>6s} {'WF':>4s} {'B3$':>8s}")
    gates = {
        "no_filter":            lambda i: True,
        "btc_rsi<70":           lambda i: btc_rsi[i] < 70,
        "btc_rsi<60":           lambda i: btc_rsi[i] < 60,
        "btc_rsi 30-70":        lambda i: 30 < btc_rsi[i] < 70,
        "btc_rsi>40":           lambda i: btc_rsi[i] > 40,
        "btc_low_vol":          lambda i: btc_atr_pct[i] < 0.7,
        "btc_high_vol":         lambda i: btc_atr_pct[i] > 0.3,
        "btc_rsi>40+low_vol":   lambda i: btc_rsi[i] > 40 and btc_atr_pct[i] < 0.7,
        "btc_neutral_filter":   lambda i: 35 < btc_rsi[i] < 70 and btc_atr_pct[i] > 0.2,
    }
    for g_name, gate in gates.items():
        # Use memes universe + momentum_obv + tp500_sl50 + mp=0.15 (sweet spot from above)
        trades = backtest_with_regime_gate(universes["memes"], cache, entry_momentum_obv,
                                            tp500_sl50, 30.0, 0.15, btc_rsi, btc_atr_pct, gate)
        agg = aggregate_with_dist(trades) if trades else {"n":0,"total_pnl":0,"best3_pnl":0}
        mc = mc_ruin_simulation(trades, equity=EQUITY, ruin_thresh=0.5, n_runs=10000) if trades else {"ruin_pct":0}
        # WF
        n = min(len(cache[s]["close"]) for s in universes["memes"])
        n = min(n, len(btc_rsi))
        fold_size = n // 4; wf_p = 0
        for k in range(4):
            s_idx = k*fold_size + 200; e_idx = (k+1)*fold_size if k<3 else n
            tr_f = backtest_with_regime_gate(universes["memes"], cache, entry_momentum_obv,
                                              tp500_sl50, 30.0, 0.15, btc_rsi, btc_atr_pct, gate, idx_start=s_idx)
            tr_f = [t for t in tr_f if t.entry_idx < e_idx]
            ag_f = aggregate_with_dist(tr_f) if tr_f else {"total_pnl":0}
            if ag_f.get("total_pnl",0) > 0: wf_p += 1
        print(f"{g_name:<28s} {agg['n']:>3d} ${agg['total_pnl']:>+6.2f} {mc['ruin_pct']:>5.1f}% {wf_p}/4 ${agg.get('best3_pnl',0):>+6.2f}")

    # ===== 4) Final picks: report S+/S/A tiers =====
    print(f"\n{'='*120}\n=== FINAL TIER RECOMMENDATIONS ===\n{'='*120}")
    final_picks = []
    candidates_final = [
        ("S+_ultraSafe", "memes", entry_momentum_obv, tp500_sl50, 0.10, "btc_rsi>40+low_vol"),
        ("S_balanced",   "memes", entry_momentum_obv, tp500_sl50, 0.15, "btc_rsi<70"),
        ("A_aggressive", "memes", entry_momentum_obv, tp500_sl50, 0.25, "no_filter"),
        ("한탕_lottery_full", "memes", entry_momentum_obv, tp500_sl50, 1.00, "no_filter"),
    ]
    print(f"{'tier':<22s} {'mp':<6s} {'gate':<22s} {'N':>3s} {'WR%':>5s} {'PnL$':>8s} "
          f"{'%/yr':>6s} {'maxR%':>6s} {'p500':>5s} {'ruin%':>6s} {'B3$':>8s}")
    for name, univ, ent_fn, ec, mp, gate_name in candidates_final:
        gate = gates[gate_name]
        trades = backtest_with_regime_gate(universes[univ], cache, ent_fn, ec, 30.0, mp,
                                            btc_rsi, btc_atr_pct, gate)
        agg = aggregate_with_dist(trades) if trades else {"n":0,"total_pnl":0,"wr":0,"max_win_roe":0,"p_win_500":0,"best3_pnl":0}
        mc = mc_ruin_simulation(trades, equity=EQUITY, ruin_thresh=0.5, n_runs=10000) if trades else {"ruin_pct":0}
        annual = agg.get("total_pnl",0)/EQUITY*100
        final_picks.append({**agg, "tier": name, "mp": mp, "gate": gate_name, "ruin": mc["ruin_pct"], "annual_pct": annual})
        print(f"{name:<22s} {mp:<6.2f} {gate_name:<22s} {agg['n']:>3d} {agg['wr']*100:>4.1f} "
              f"${agg['total_pnl']:>+6.2f} {annual:>+5.0f}% {agg['max_win_roe']:>5.0f} "
              f"{agg['p_win_500']*100:>4.1f}% {mc['ruin_pct']:>5.1f}% ${agg['best3_pnl']:>+6.2f}")

    Path(OUT).write_text(json.dumps({"mp_grid": mp_results, "final_picks": final_picks}, indent=2, default=str))
    print(f"\n[done] {time.time()-t0:.1f}s, saved: {OUT}")


if __name__ == "__main__":
    main()
