#!/usr/bin/env python3
"""Phase 16: Robustness check on top phase-15 candidates.

Top phase 15 winners:
  A. momentum_cont + tp500_sl50 + memes        : N=84, +$1059, p500=13.1%
  B. momentum_cont + tp500_sl50 + memes_first  : N=86, +$866
  C. breakout_volexp + tp200_sl50 + memes      : N=65, +$834, WR=32.3%
  D. squeeze_release + tp200_sl50 + memes_first: N=101, +$772
  E. breakout_volexp + tp200_sl50 + PEPE_only  : N=40, +$548, WR=32.5%

Apply MANDATORY checks (per CLAUDE.md):
  1. Walk-forward 4-fold (n≥3/4 positive)
  2. MC ruin (n_runs=10000, ruin≤5% safe / ≤10% aggressive)
  3. Slippage stress 0/5/10/15/20bps
  4. Parameter sensitivity (TP/SL ±20%)
  5. Fee/SL ratio < 20%
  6. Fixed-equity (no compound) — already enforced

Also test:
  7. Add OBV divergence signal (per GPT research)
  8. Fractional Kelly sizing (mp=0.5 vs 1.0 vs 0.25)
  9. With-Trump filter: simulate funding/OI proxy via volume regime
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
    add_extra_features, ENTRIES, backtest_signal, entry_momentum_continuation,
    entry_breakout_volexp, entry_squeeze_release
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quant_runtime" / "master_engine_runs" / "phase16_robustness.json"


# ====================================================================
# Walk-forward
# ====================================================================

def wf_4fold(priority, cache, entry_fn, ec, lev=30.0, mp=1.0):
    valid = [s for s in priority if s in cache]
    if not valid: return [None]*4
    n = min(len(cache[s]["close"]) for s in valid)
    fold_size = n // 4
    folds = []
    for k in range(4):
        s_idx = k * fold_size + 200
        e_idx = (k + 1) * fold_size if k < 3 else n
        trades, _ = backtest_signal(priority, cache, entry_fn, ec, lev=lev, mp=mp,
                                     idx_start=s_idx, idx_end=e_idx)
        agg = aggregate_with_dist(trades) if trades else {"n":0, "total_pnl":0, "wr":0}
        folds.append(agg)
    return folds


# ====================================================================
# Slippage stress
# ====================================================================

def backtest_with_slip(priority, cache, entry_fn, ec, lev, mp, slip_bps,
                       cooldown_h=12, loss_cooldown_h=24, idx_start=200):
    """Apply extra slippage on entry+exit."""
    valid = [s for s in priority if s in cache]
    if not valid: return []
    n = min(len(cache[s]["close"]) for s in valid)
    idx_end = min(n - ec.max_hold_h - 2, n)
    trades = []
    last_loss_h = -1e9; last_exit_h = -1e9
    i = max(idx_start, 200)
    while i < idx_end:
        if i - last_loss_h < loss_cooldown_h:
            i += 1; continue
        if i - last_exit_h < cooldown_h:
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
        # Extra slippage = 2*slip_bps round trip
        fee = notional * (COST_RT + 2 * slip_bps / 10000.0)
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


# ====================================================================
# MC ruin
# ====================================================================

def mc_ruin_simulation(trades, equity=50, ruin_thresh=0.5, n_runs=10000):
    """Bootstrap-resample trades; count runs where running equity <= ruin_thresh*equity."""
    if not trades:
        return {"ruin_pct": 0.0, "n": 0}
    pnls = np.array([t.pnl_usd for t in trades])
    n = len(pnls)
    rng = np.random.default_rng(42)
    ruined = 0
    for _ in range(n_runs):
        idx = rng.integers(0, n, n)
        path_pnls = pnls[idx]
        cum = np.cumsum(path_pnls)
        if (cum.min() + equity) <= ruin_thresh * equity:
            ruined += 1
    return {"ruin_pct": 100.0 * ruined / n_runs, "n": n}


# ====================================================================
# Add OBV-based divergence signal (per GPT research)
# ====================================================================

def add_obv(ind):
    n = len(ind["close"])
    close = ind["close"]
    delta = np.zeros(n)
    obv = np.zeros(n)
    # No volume — assume volume is in `vol_r` already normalized
    # Use vol_r as proxy weight: if close>prev, +vol_r; if <prev, -vol_r
    vol_r = ind["vol_r"]
    for i in range(1, n):
        d = 0
        if close[i] > close[i-1]: d = vol_r[i]
        elif close[i] < close[i-1]: d = -vol_r[i]
        obv[i] = obv[i-1] + d
    ind["obv"] = obv
    # OBV slope (last 6 bars)
    obv_slope = np.zeros(n)
    for i in range(6, n):
        obv_slope[i] = obv[i] - obv[i-6]
    ind["obv_slope"] = obv_slope
    return ind


def entry_obv_breakout(ind, i, long_only=True):
    """20-bar high break + OBV making new 6h high (no divergence)."""
    if i < 21: return 0
    if (ind["close"][i] > ind["high20"][i-1]
        and ind["obv"][i] > ind["obv"][i-6]
        and ind["obv_slope"][i] > 0
        and ind["vol_r"][i] >= 1.2):
        return 1
    return 0


def entry_obv_div_long(ind, i, long_only=True):
    """Bullish OBV divergence: price makes new 20-bar low BUT obv doesn't."""
    if i < 21: return 0
    if (ind["low"][i] <= ind["low20"][i-1]
        and ind["obv"][i] > ind["obv"][i-15]
        and ind["close"][i] > ind["close"][i-1]
        and ind["macd"][i] > ind["macd_sig"][i]):
        return 1
    return 0


# Combined momentum + OBV confirmation
def entry_momentum_obv(ind, i, long_only=True):
    """Momentum (24h) + OBV up + ADX rising."""
    if i < 25: return 0
    if (ind["mom24"][i] > 0.05
        and ind["ema20"][i] > ind["ema50"][i]
        and ind["adx"][i] > 22
        and ind["vol_r"][i] >= 1.3
        and ind["obv_slope"][i] > 0):
        return 1
    return 0


EXTRA_ENTRIES = {
    "obv_breakout": entry_obv_breakout,
    "obv_div_long": entry_obv_div_long,
    "momentum_obv": entry_momentum_obv,
}


# ====================================================================
# Main
# ====================================================================

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
    print(f"[load] {len(cache)} syms × {n_bars} bars  ({time.time()-t0:.1f}s)")

    # ===== Top candidates =====
    universes = {
        "memes": ["PEPEUSDT", "WIFUSDT", "DOGEUSDT"],
        "memes_first": ["PEPEUSDT", "WIFUSDT", "DOGEUSDT", "SOLUSDT"],
        "PEPE_only": ["PEPEUSDT"],
        "rotation_orig": ["PEPEUSDT", "DOGEUSDT", "ETHUSDT", "SOLUSDT"],
    }
    tp500_sl50 = ExitConfig(tp_ladder_roe=(500,500,500,500), tp_ladder_fraction=1.0,
                             profit_protect_arm_roe=999, sl_roe=-50, max_hold_h=96)
    tp200_sl50 = ExitConfig(tp_ladder_roe=(200,200,200,200), tp_ladder_fraction=1.0,
                             profit_protect_arm_roe=999, sl_roe=-50, max_hold_h=72)
    candidates = [
        ("A_mom_tp500_memes",    entry_momentum_continuation, "memes",       tp500_sl50, 1.0),
        ("B_mom_tp500_memes_first", entry_momentum_continuation, "memes_first", tp500_sl50, 1.0),
        ("C_breakout_tp200_memes", entry_breakout_volexp, "memes",       tp200_sl50, 1.0),
        ("D_squeeze_tp200_memesfirst", entry_squeeze_release, "memes_first", tp200_sl50, 1.0),
        ("E_breakout_tp200_PEPE",  entry_breakout_volexp, "PEPE_only",   tp200_sl50, 1.0),
    ]

    print(f"\n{'='*120}\n=== ROBUSTNESS REPORT (top 5 candidates) ===\n{'='*120}")
    results = {}
    for name, ent_fn, univ, ec, mp in candidates:
        priority = universes[univ]
        if not all(s in cache for s in priority):
            print(f"\n[{name}] SKIP — missing symbols"); continue
        # Full backtest
        trades, _ = backtest_signal(priority, cache, ent_fn, ec, lev=30.0, mp=mp)
        agg = aggregate_with_dist(trades)
        # WF
        wf_folds = wf_4fold(priority, cache, ent_fn, ec, lev=30.0, mp=mp)
        wf_passes = sum(1 for f in wf_folds if f and f.get("total_pnl", 0) > 0)
        # MC ruin
        mc = mc_ruin_simulation(trades, equity=EQUITY, ruin_thresh=0.5, n_runs=10000)
        # Slippage stress
        slips = {}
        for slip_bps in [0, 5, 10, 15, 20]:
            tr_slip = backtest_with_slip(priority, cache, ent_fn, ec, 30.0, mp, slip_bps)
            ag = aggregate_with_dist(tr_slip) if tr_slip else {"n":0, "total_pnl":0, "ev_pnl":0}
            slips[f"slip_{slip_bps}bps"] = {"n": ag.get("n",0), "total_pnl": ag.get("total_pnl",0), "ev": ag.get("ev_pnl",0)}
        # Param sensitivity: TP±20%, SL±20%
        sens_results = []
        for tp_mul in [0.8, 1.0, 1.2]:
            for sl_mul in [0.8, 1.0, 1.2]:
                ec_v = replace(ec,
                               tp_ladder_roe=tuple(t*tp_mul for t in ec.tp_ladder_roe),
                               sl_roe=ec.sl_roe*sl_mul)
                tr_v, _ = backtest_signal(priority, cache, ent_fn, ec_v, lev=30.0, mp=mp)
                ag_v = aggregate_with_dist(tr_v) if tr_v else {"total_pnl":0, "n":0}
                sens_results.append({"tp_mul":tp_mul, "sl_mul":sl_mul,
                                     "n":ag_v.get("n",0), "pnl":ag_v.get("total_pnl",0)})
        sens_pos = sum(1 for s in sens_results if s["pnl"] > 0)
        # Fee/SL ratio
        notional = EQUITY * mp * 30
        fee_dollar = notional * COST_RT
        sl_dollar = abs(EQUITY * mp * (ec.sl_roe / 100.0))
        fee_sl_ratio = fee_dollar / sl_dollar if sl_dollar > 0 else 999

        results[name] = {
            "agg": agg, "wf_folds": wf_folds, "wf_passes": wf_passes,
            "mc_ruin": mc, "slips": slips, "sensitivity": sens_results,
            "sens_positive": sens_pos, "fee_sl_ratio": fee_sl_ratio,
            "univ": univ
        }
        print(f"\n=== {name} ({univ}) ===")
        print(f"  Trades       : N={agg['n']:>3d}, WR={agg['wr']*100:.1f}%, EV=${agg['ev_pnl']:.2f}, "
              f"PnL=${agg['total_pnl']:.2f}, B3=${agg['best3_pnl']:.2f}, "
              f"p100={agg['p_win_100']*100:.1f}% p500={agg['p_win_500']*100:.1f}%")
        print(f"  WF 4-fold    : ", end="")
        for k, f in enumerate(wf_folds):
            mark = "✓" if f and f.get("total_pnl",0) > 0 else "✗"
            print(f"f{k}={mark}${f.get('total_pnl',0):>+5.0f}(N{f.get('n',0)}) ", end="")
        print(f" → {wf_passes}/4 {'✓PASS' if wf_passes>=3 else '✗FAIL'}")
        print(f"  MC ruin (10k): {mc['ruin_pct']:.1f}% {'✓SAFE' if mc['ruin_pct']<=5 else ('✓AGG' if mc['ruin_pct']<=10 else '✗RUIN')}")
        print(f"  Slip stress  : ", end="")
        for slip_bps in [0,5,10,15,20]:
            v = slips[f"slip_{slip_bps}bps"]
            mark = "✓" if v["total_pnl"] > 0 else "✗"
            print(f"{slip_bps}bps={mark}${v['total_pnl']:>+5.0f} ", end="")
        print()
        print(f"  Param sens   : {sens_pos}/9 positive {'✓' if sens_pos>=7 else '✗'} "
              f"(TP±20%×SL±20%)")
        print(f"  Fee/SL ratio : {fee_sl_ratio*100:.1f}% {'✓' if fee_sl_ratio<0.20 else '✗'} (<20%)")
        # Pass/fail matrix
        passes = {
            "n>=25": agg['n'] >= 25,
            "wf>=3/4": wf_passes >= 3,
            "ruin<=10%": mc['ruin_pct'] <= 10,
            "slip5bps_pos": slips["slip_5bps"]["total_pnl"] > 0,
            "sens>=7/9": sens_pos >= 7,
            "fee/sl<20%": fee_sl_ratio < 0.20,
        }
        n_pass = sum(passes.values())
        print(f"  Overall      : {n_pass}/6 {'✓✓ STRONG' if n_pass==6 else ('✓ OK' if n_pass>=4 else '✗ WEAK')}")
        results[name]["passes"] = passes
        results[name]["n_pass"] = n_pass

    # ===== Test additional OBV signals on memes =====
    print(f"\n{'='*120}\n=== OBV-based new signals (per GPT research) ===\n{'='*120}")
    print(f"{'entry':<18s} {'exit':<18s} {'univ':<14s} {'N':>3s} {'WR%':>5s} {'EV$':>7s} {'PnL$':>8s} {'p100':>5s} {'p500':>5s} {'B3$':>7s}")
    for univ_name in ["memes", "memes_first", "PEPE_only"]:
        priority = universes[univ_name]
        if not all(s in cache for s in priority): continue
        for ent_name, ent_fn in EXTRA_ENTRIES.items():
            for exit_name, ec in [("tp200_sl50", tp200_sl50), ("tp500_sl50", tp500_sl50)]:
                trades, _ = backtest_signal(priority, cache, ent_fn, ec, lev=30.0, mp=1.0)
                agg = aggregate_with_dist(trades) if trades else {"n":0}
                if agg["n"] < 5: continue
                print(f"{ent_name:<18s} {exit_name:<18s} {univ_name:<14s} "
                      f"{agg['n']:>3d} {agg['wr']*100:>4.1f} ${agg['ev_pnl']:>+5.2f} "
                      f"${agg['total_pnl']:>+6.2f} {agg['p_win_100']*100:>4.1f}% "
                      f"{agg['p_win_500']*100:>4.1f}% ${agg['best3_pnl']:>+5.2f}")

    # ===== Fractional Kelly sizing on best candidate =====
    print(f"\n{'='*120}\n=== FRACTIONAL KELLY SIZING (best candidate: A) ===\n{'='*120}")
    print(f"{'mp':<6s} {'margin$':<8s} {'notional$':<10s} {'N':>3s} {'WR%':>5s} {'PnL$':>8s} {'ruin%':>6s} {'maxDD$':>7s} {'%/yr':>7s}")
    ec_a = tp500_sl50
    for mp in [1.0, 0.75, 0.50, 0.25, 0.15, 0.10]:
        trades, _ = backtest_signal(universes["memes"], cache, entry_momentum_continuation,
                                     ec_a, lev=30.0, mp=mp)
        agg = aggregate_with_dist(trades) if trades else {"n":0,"total_pnl":0,"wr":0,"max_dd":0}
        mc = mc_ruin_simulation(trades, equity=EQUITY, ruin_thresh=0.5, n_runs=10000) if trades else {"ruin_pct":0}
        margin = EQUITY * mp; notional = margin * 30
        annual_pct = agg["total_pnl"]/EQUITY*100 if EQUITY>0 else 0
        print(f"{mp:<6.2f} ${margin:<7.2f} ${notional:<8.0f} {agg['n']:>3d} {agg['wr']*100:>4.1f} "
              f"${agg['total_pnl']:>+6.2f} {mc['ruin_pct']:>5.1f}% ${agg['max_dd']:>5.1f} "
              f"{annual_pct:>+5.0f}%")

    Path(OUT).write_text(json.dumps(results, indent=2, default=str))
    print(f"\n[done] {time.time()-t0:.1f}s, saved: {OUT}")


if __name__ == "__main__":
    main()
