#!/usr/bin/env python3
"""Phase 15: Diverse entry signal library + multi-archetype sweep.

Phase 14 showed that the production-faithful gates with our `long_signal`
(oversold bounce) lose 90%+ at 30x because -10% ROE = -0.33% price (noise).

This phase tests multiple ENTRY ARCHETYPES with the production exit/gate framework:

  1. breakout_volexp     — 20-bar high broken with ATR expansion
  2. squeeze_release     — BB squeeze (low volatility) then breakout
  3. momentum_continuation — 24h+ uptrend with volume confirmation
  4. liq_cascade_bounce  — Sharp drop + reclaim
  5. vwap_reclaim        — Below 24h-VWAP then reclaim
  6. macd_zero_up        — MACD crosses 0 from below + ADX rising
  7. higher_tf_pullback  — 4h trend up + 1h pullback bounce
  8. trap_reversal       — Failed breakdown reversal
  9. simple_breakout     — Pure 20-bar high break (no filter)

Each ENTRY × multiple TP/SL combos × 30x lev × $50.
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
    compute_production_features, GateConfig, ExitConfig, simulate_trade_exit,
    aggregate_with_dist, _max_dd
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quant_runtime" / "master_engine_runs" / "phase15_signal_library.json"


# ====================================================================
# Extra features needed for new archetypes
# ====================================================================

def add_extra_features(ind: dict) -> dict:
    """Add BB width, VWAP, 4h-equiv trend, mom_24h."""
    n = len(ind["close"])
    close = ind["close"]
    high = ind["high"]
    low = ind["low"]

    # BB(20, 2)
    bb_mid = np.zeros(n); bb_std = np.zeros(n)
    for i in range(n):
        s = max(0, i - 19)
        bb_mid[i] = np.mean(close[s:i+1])
        bb_std[i] = np.std(close[s:i+1]) if i > 0 else 0
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    bb_width = np.where(bb_mid > 0, (bb_upper - bb_lower) / bb_mid, 0.0)
    # BB width percentile (low = squeeze)
    bb_width_rank = np.zeros(n)
    for i in range(20, n):
        s = max(0, i - 100)
        window = bb_width[s:i+1]
        bb_width_rank[i] = (window <= bb_width[i]).mean()

    # 24h VWAP (rolling 24h on hourly bars)
    typical = (high + low + close) / 3.0
    # Approximate using close × volume (no vol available from this signature, use typical)
    # Use 24-bar simple VWAP-like (price-mean over 24h)
    vwap24 = np.zeros(n)
    for i in range(n):
        s = max(0, i - 23)
        vwap24[i] = np.mean(typical[s:i+1])

    # 24h momentum
    mom24 = np.zeros(n)
    for i in range(24, n):
        mom24[i] = (close[i] - close[i-24]) / close[i-24]

    # 4h-equivalent trend: ema20 vs ema50 over 4h-resampled (use 4h offsets)
    # Approx: positive if close > close[i-4*5]=close[i-20] AND ema20 > ema50
    htf_uptrend = np.zeros(n, dtype=bool)
    for i in range(20, n):
        htf_uptrend[i] = (close[i] > close[i-20]) and (ind["ema20"][i] > ind["ema50"][i])

    # 1h drop (worst 1h drop in last 6h)
    drop6 = np.zeros(n)
    for i in range(6, n):
        # Find max single-bar drop in last 6 bars
        drops = [(close[k-1] - low[k]) / max(close[k-1], 1e-9) for k in range(i-5, i+1)]
        drop6[i] = max(drops)

    ind["bb_width"] = bb_width
    ind["bb_width_rank"] = bb_width_rank
    ind["bb_upper"] = bb_upper
    ind["bb_lower"] = bb_lower
    ind["vwap24"] = vwap24
    ind["mom24"] = mom24
    ind["htf_uptrend"] = htf_uptrend
    ind["drop6"] = drop6
    return ind


# ====================================================================
# Entry archetypes — each returns (side: int, score_for_log: float)
#   side: 1=long, -1=short, 0=none
# ====================================================================

def entry_breakout_volexp(ind, i, long_only=True):
    if i < 21: return 0
    atr = ind["atr"][i]
    atr_ma = np.mean(ind["atr"][max(0,i-19):i+1])
    if atr <= 0 or atr_ma <= 0: return 0
    # Long: broke above 20-bar high + ATR expansion
    if (ind["close"][i] > ind["high20"][i-1]
        and atr > atr_ma * 1.3
        and ind["adx"][i] > 18
        and ind["vol_r"][i] > 1.2):
        return 1
    if (not long_only and
        ind["close"][i] < ind["low20"][i-1]
        and atr > atr_ma * 1.3
        and ind["adx"][i] > 18
        and ind["vol_r"][i] > 1.2):
        return -1
    return 0


def entry_squeeze_release(ind, i, long_only=True):
    if i < 22: return 0
    # Squeeze: BB width was in bottom 30% over last 100 bars over the past 5 bars
    recent_squeeze = all(ind["bb_width_rank"][k] < 0.30 for k in range(i-5, i)) if i >= 5 else False
    if not recent_squeeze: return 0
    # Now break: close > BB upper (long)
    if ind["close"][i] > ind["bb_upper"][i-1] and ind["vol_r"][i] > 1.3:
        return 1
    if (not long_only) and ind["close"][i] < ind["bb_lower"][i-1] and ind["vol_r"][i] > 1.3:
        return -1
    return 0


def entry_momentum_continuation(ind, i, long_only=True):
    if i < 25: return 0
    if (ind["mom24"][i] > 0.05
        and ind["ema20"][i] > ind["ema50"][i]
        and ind["adx"][i] > 22
        and ind["vol_r"][i] >= 1.3):
        return 1
    if ((not long_only)
        and ind["mom24"][i] < -0.05
        and ind["ema20"][i] < ind["ema50"][i]
        and ind["adx"][i] > 22
        and ind["vol_r"][i] >= 1.3):
        return -1
    return 0


def entry_liq_cascade_bounce(ind, i, long_only=True):
    """Sharp drop then reclaim: drop6 ≥ 4% AND current close > prev close AND vol >= 1.5x."""
    if i < 8: return 0
    if (ind["drop6"][i-1] >= 0.04
        and ind["close"][i] > ind["close"][i-1]
        and ind["close"][i] > ind["high"][i-1]  # reclaim prev hi
        and ind["vol_r"][i] >= 1.5):
        return 1
    return 0  # short variant skipped (long-only bounce)


def entry_vwap_reclaim(ind, i, long_only=True):
    """Was below VWAP for >=4 bars, now reclaims with vol."""
    if i < 5: return 0
    below = all(ind["close"][k] < ind["vwap24"][k] for k in range(i-4, i))
    if (below and ind["close"][i] > ind["vwap24"][i] and ind["vol_r"][i] > 1.2
        and ind["macd"][i] > ind["macd_sig"][i]):
        return 1
    return 0


def entry_macd_zero_up(ind, i, long_only=True):
    """MACD crosses zero from below + ADX rising."""
    if i < 5: return 0
    if (ind["macd"][i-1] <= 0 and ind["macd"][i] > 0
        and ind["adx"][i] > ind["adx"][i-3]
        and ind["adx"][i] > 18
        and ind["vol_r"][i] >= 1.1):
        return 1
    if ((not long_only)
        and ind["macd"][i-1] >= 0 and ind["macd"][i] < 0
        and ind["adx"][i] > ind["adx"][i-3]
        and ind["adx"][i] > 18
        and ind["vol_r"][i] >= 1.1):
        return -1
    return 0


def entry_htf_pullback(ind, i, long_only=True):
    """HTF up + pulled back to ema20 + bounce + macd cross up."""
    if i < 25: return 0
    if not ind["htf_uptrend"][i]: return 0
    # Pulled back: low of last 3 bars touched/below ema20
    pullback = any(ind["low"][k] <= ind["ema20"][k] for k in range(i-3, i+1))
    if not pullback: return 0
    if (ind["close"][i] > ind["ema20"][i]
        and ind["macd"][i] > ind["macd_sig"][i]
        and ind["close"][i] > ind["close"][i-1]):
        return 1
    return 0


def entry_trap_reversal(ind, i, long_only=True):
    """Failed breakdown: low broke 20-bar low but close back above it."""
    if i < 21: return 0
    if (ind["low"][i] < ind["low20"][i-1]
        and ind["close"][i] > ind["low20"][i-1]
        and ind["close"][i] > ind["close"][i-1]
        and ind["vol_r"][i] >= 1.4
        and ind["macd"][i] > ind["macd_sig"][i]):
        return 1
    return 0


def entry_simple_breakout(ind, i, long_only=True):
    if i < 21: return 0
    if ind["close"][i] > ind["high20"][i-1] and ind["vol_r"][i] > 1.0:
        return 1
    if (not long_only) and ind["close"][i] < ind["low20"][i-1] and ind["vol_r"][i] > 1.0:
        return -1
    return 0


def entry_oversold_bounce(ind, i, long_only=True):
    """Phase 14 baseline."""
    if i < 1: return 0
    if (ind["rsi"][i] <= 30 and ind["macd"][i] > ind["macd_sig"][i]
        and ind["close"][i] > ind["close"][i-1]):
        return 1
    return 0


ENTRIES = {
    "breakout_volexp": entry_breakout_volexp,
    "squeeze_release": entry_squeeze_release,
    "momentum_cont": entry_momentum_continuation,
    "liq_cascade": entry_liq_cascade_bounce,
    "vwap_reclaim": entry_vwap_reclaim,
    "macd_zero_up": entry_macd_zero_up,
    "htf_pullback": entry_htf_pullback,
    "trap_reversal": entry_trap_reversal,
    "simple_breakout": entry_simple_breakout,
    "oversold_bounce": entry_oversold_bounce,  # baseline
}


# ====================================================================
# Backtest with arbitrary entry function
# ====================================================================

def backtest_signal(priority, cache, entry_fn, ec: ExitConfig, lev=30.0, mp=1.0,
                    long_only=True, idx_start=200, idx_end=None,
                    cooldown_h=12, loss_cooldown_h=24):
    valid = [s for s in priority if s in cache]
    if not valid: return [], {}
    n = min(len(cache[s]["close"]) for s in valid)
    idx_end = min(idx_end or n, n - ec.max_hold_h - 2)
    trades = []
    last_loss_h = -1e9; last_exit_h = -1e9
    fire_count = 0
    i = max(idx_start, 200)
    while i < idx_end:
        if i - last_loss_h < loss_cooldown_h:
            i += 1; continue
        if i - last_exit_h < cooldown_h:
            i += 1; continue
        chosen = None; side = 0
        for s in valid:
            ind = cache[s]
            sd = entry_fn(ind, i, long_only)
            if sd != 0:
                chosen = s; side = sd; break
        if chosen is None:
            i += 1; continue
        fire_count += 1
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
    return trades, {"fire_count": fire_count}


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
        cache[s] = ind
    n_bars = min(len(v["close"]) for v in cache.values())
    print(f"[load] {len(cache)} syms × {n_bars} bars  ({time.time()-t0:.1f}s)")

    universes = {
        "PEPE_only": ["PEPEUSDT"],
        "memes": ["PEPEUSDT", "WIFUSDT", "DOGEUSDT"],
        "memes_first": ["PEPEUSDT", "WIFUSDT", "DOGEUSDT", "SOLUSDT"],
        "rotation_orig": ["PEPEUSDT", "DOGEUSDT", "ETHUSDT", "SOLUSDT"],
    }

    # Exit variants — at 30x, SL=-10% = -0.33% price (too tight for memes!)
    # SL=-30% = -1% px, SL=-50% = -1.67% px
    base_ladder = ExitConfig(tp_ladder_roe=(5,18,35,60), tp_ladder_fraction=0.75,
                              profit_protect_arm_roe=18, profit_protect_retrace_roe=5,
                              sl_roe=-10, max_hold_h=48)
    exits = {
        "PROD_ladder_sl10":   base_ladder,
        "ladder_sl30":        replace(base_ladder, sl_roe=-30),
        "ladder_sl50":        replace(base_ladder, sl_roe=-50),
        "tp200_sl30":         ExitConfig(tp_ladder_roe=(200,200,200,200), tp_ladder_fraction=1.0,
                                          profit_protect_arm_roe=999, sl_roe=-30, max_hold_h=72),
        "tp500_sl30":         ExitConfig(tp_ladder_roe=(500,500,500,500), tp_ladder_fraction=1.0,
                                          profit_protect_arm_roe=999, sl_roe=-30, max_hold_h=96),
        "tp200_sl50":         ExitConfig(tp_ladder_roe=(200,200,200,200), tp_ladder_fraction=1.0,
                                          profit_protect_arm_roe=999, sl_roe=-50, max_hold_h=72),
        "tp500_sl50":         ExitConfig(tp_ladder_roe=(500,500,500,500), tp_ladder_fraction=1.0,
                                          profit_protect_arm_roe=999, sl_roe=-50, max_hold_h=96),
        "split_100_50":       ExitConfig(tp_ladder_roe=(50,100,200,400), tp_ladder_fraction=0.5,
                                          profit_protect_arm_roe=50, profit_protect_retrace_roe=20,
                                          sl_roe=-30, max_hold_h=72),
    }

    rows = []
    print(f"\n{'entry':<18s} {'exit':<18s} {'univ':<14s} {'N':>3s} {'WR%':>5s} {'avgW%':>6s} {'avgL%':>6s} {'EV$':>7s} {'PnL$':>8s} {'maxR%':>7s} {'p100':>5s} {'p200':>5s} {'p500':>5s} {'B3$':>7s}")
    for univ_name, priority in universes.items():
        if not all(s in cache for s in priority): continue
        for entry_name, entry_fn in ENTRIES.items():
            for exit_name, ec in exits.items():
                trades, diag = backtest_signal(priority, cache, entry_fn, ec, lev=30.0, mp=1.0)
                agg = aggregate_with_dist(trades)
                if agg["n"] == 0:
                    rows.append({"entry":entry_name,"exit":exit_name,"univ":univ_name,"n":0})
                    continue
                row = {"entry":entry_name,"exit":exit_name,"univ":univ_name,**agg}
                rows.append(row)
                if agg["n"] >= 3:
                    print(f"{entry_name:<18s} {exit_name:<18s} {univ_name:<14s} "
                          f"{agg['n']:>3d} {agg['wr']*100:>4.1f} "
                          f"{agg['avg_win_roe']:>5.0f} {agg['avg_loss_roe']:>5.0f} "
                          f"${agg['ev_pnl']:>+5.2f} ${agg['total_pnl']:>+6.2f} "
                          f"{agg['max_win_roe']:>6.0f} "
                          f"{agg['p_win_100']*100:>4.1f}% {agg['p_win_200']*100:>4.1f}% "
                          f"{agg['p_win_500']*100:>4.1f}% ${agg['best3_pnl']:>+5.2f}")

    OUT.write_text(json.dumps(rows, indent=2, default=str))
    print(f"\n[done] {len(rows)} configs, {time.time()-t0:.1f}s, saved: {OUT}")

    fired = [r for r in rows if r.get("n", 0) >= 5]
    print(f"\nN={len(fired)} configs with ≥5 trades")

    if fired:
        print(f"\n=== TOP-15 by total_pnl ===")
        fired.sort(key=lambda r: -r["total_pnl"])
        for i, r in enumerate(fired[:15], 1):
            print(f"  {i:>2d} {r['entry']:<18s} {r['exit']:<18s} {r['univ']:<14s} "
                  f"N={r['n']:>3d} WR={r['wr']*100:>4.1f}% EV=${r['ev_pnl']:>+5.2f} "
                  f"PnL=${r['total_pnl']:>+7.2f} max={r['max_win_roe']:>5.0f}% "
                  f"p200={r['p_win_200']*100:>4.1f}% B3=${r['best3_pnl']:>+6.2f}")

        print(f"\n=== TOP-15 by best_3_pnl (한탕 잠재력) ===")
        fired.sort(key=lambda r: -r.get("best3_pnl", 0))
        for i, r in enumerate(fired[:15], 1):
            print(f"  {i:>2d} {r['entry']:<18s} {r['exit']:<18s} {r['univ']:<14s} "
                  f"N={r['n']:>3d} WR={r['wr']*100:>4.1f}% maxR={r['max_win_roe']:>5.0f}% "
                  f"p100={r['p_win_100']*100:>4.1f}% p200={r['p_win_200']*100:>4.1f}% "
                  f"p500={r['p_win_500']*100:>4.1f}% B3=${r['best3_pnl']:>+6.2f} "
                  f"PnL=${r['total_pnl']:>+7.2f}")

        print(f"\n=== TOP-15 by p_win_200 (3배+ ROE hit 확률) ===")
        fired.sort(key=lambda r: -r["p_win_200"])
        for i, r in enumerate(fired[:15], 1):
            print(f"  {i:>2d} {r['entry']:<18s} {r['exit']:<18s} {r['univ']:<14s} "
                  f"N={r['n']:>3d} p100={r['p_win_100']*100:>4.1f}% "
                  f"p200={r['p_win_200']*100:>4.1f}% p500={r['p_win_500']*100:>4.1f}% "
                  f"maxR={r['max_win_roe']:>5.0f}% PnL=${r['total_pnl']:>+7.2f}")


if __name__ == "__main__":
    main()
