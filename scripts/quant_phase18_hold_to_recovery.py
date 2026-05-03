#!/usr/bin/env python3
"""Phase 18: Test the "filter entries + hold to recovery" hypothesis.

User question (paraphrased): "If we filter long entries properly, AND if we hold
through losses to take profit when long signal returns, isn't loss impossible?"

Test 4 exit policies on the SAME momentum_obv entries (memes universe, 30x):

  Policy A: SL=-50% ROE / TP=+500% ROE (Phase17 winner)
  Policy B: NO SL, exit only when long signal terminates AND ROE > 0
            (the user's "버텨서 다시 롱전환되면 익절" hypothesis)
  Policy C: NO SL, exit on signal flip regardless of profit (less stubborn)
  Policy D: NO SL, exit only at TP=+500% or signal flip in profit
            (combination — most extreme "한탕 + 버티기")

CRITICAL: All policies include LIQUIDATION simulation:
  - Maintenance margin ~ 0.5% on Bitget memes
  - Effective liquidation: when intra-bar low reaches ROE ≤ -95% (with buffer)
  - At 30x: that's price drop of ~3.17% from entry
  - Liquidation = lose ENTIRE margin (not just SL amount)

Also tests at multiple leverages: 30x / 10x / 5x / 2x to show why "버티기" works
on low leverage but not 30x.
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
from quant_phase14_production_sim import compute_production_features
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv, entry_momentum_obv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quant_runtime" / "master_engine_runs" / "phase18_hold_to_recovery.json"

LIQ_BUFFER = 0.95  # Liquidate when ROE <= -95% (5% buffer for fee/maintenance)
MAX_HOLD_H = 168   # Max hold = 7 days. After that, force exit.


def simulate_with_policy(ind, entry_idx, side, lev, margin, policy, n):
    """Simulate single trade with given exit policy.

    Returns (realized_roe_pct, exit_idx, exit_reason).
    realized_roe = position-weighted ROE %.
    On liquidation, returns -100 (full margin loss).
    """
    entry_px = ind["close"][entry_idx]
    if entry_px <= 0:
        return 0.0, entry_idx + 1, "INVALID"
    end_idx = min(entry_idx + MAX_HOLD_H, n - 1)

    for k in range(entry_idx + 1, end_idx + 1):
        hi = ind["high"][k]; lo = ind["low"][k]; cl = ind["close"][k]
        if side == 1:
            roe_lo = (lo / entry_px - 1) * lev * 100
            roe_hi = (hi / entry_px - 1) * lev * 100
            roe_cl = (cl / entry_px - 1) * lev * 100
        else:
            roe_lo = -(hi / entry_px - 1) * lev * 100
            roe_hi = -(lo / entry_px - 1) * lev * 100
            roe_cl = -(cl / entry_px - 1) * lev * 100

        # === LIQUIDATION CHECK (always first, regardless of policy) ===
        if roe_lo <= -LIQ_BUFFER * 100:  # ROE <= -95%
            return -100.0, k, "LIQUIDATED"

        # === Policy A: SL=-50% / TP=+500% ===
        if policy == "A_SL50_TP500":
            if roe_lo <= -50:
                return -50.0, k, "SL"
            if roe_hi >= 500:
                return 500.0, k, "TP"

        # === Policy B: NO SL, exit on signal flip + profit ===
        elif policy == "B_hold_to_recovery":
            # Long signal flipped? Check at close
            sig = entry_momentum_obv(ind, k, long_only=True)
            if sig == 0 and roe_cl > 0:
                return roe_cl, k, "SIGNAL_OFF_INPROFIT"

        # === Policy C: NO SL, exit on signal flip regardless ===
        elif policy == "C_signal_flip":
            sig = entry_momentum_obv(ind, k, long_only=True)
            if sig == 0:
                return roe_cl, k, "SIGNAL_OFF"

        # === Policy D: NO SL, only TP+500 or signal flip in profit ===
        elif policy == "D_tp500_or_signal":
            if roe_hi >= 500:
                return 500.0, k, "TP"
            sig = entry_momentum_obv(ind, k, long_only=True)
            if sig == 0 and roe_cl > 0:
                return roe_cl, k, "SIGNAL_OFF_INPROFIT"

    # Hold timeout — close at last bar
    if side == 1:
        roe = (ind["close"][end_idx] / entry_px - 1) * lev * 100
    else:
        roe = -(ind["close"][end_idx] / entry_px - 1) * lev * 100
    # If massive drawdown at timeout, treat as liquidation if exceeded
    if roe <= -LIQ_BUFFER * 100:
        return -100.0, end_idx, "LIQ_AT_TIMEOUT"
    return roe, end_idx, "TIMEOUT"


def backtest_policy(priority, cache, lev, mp, policy, idx_start=200, cooldown_h=12, loss_cooldown_h=24):
    """Backtest a single policy across the universe."""
    valid = [s for s in priority if s in cache]
    if not valid:
        return []
    n = min(len(cache[s]["close"]) for s in valid)
    idx_end = n - MAX_HOLD_H - 2
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
            sd = entry_momentum_obv(ind, i, True)
            if sd != 0:
                chosen = s; side = sd; break
        if chosen is None:
            i += 1; continue
        ind = cache[chosen]
        margin = EQUITY * mp
        notional = margin * lev
        fee = notional * COST_RT
        realized_roe, exit_idx, exit_reason = simulate_with_policy(
            ind, i, side, lev, margin, policy, n
        )
        hold_h = max(1, exit_idx - i)
        funding = notional * FUNDING_8H * (hold_h // 8)
        # ROE -100 = liquidated → margin loss only (cap at -margin, fee+funding still apply but already lost)
        if realized_roe <= -100:
            pnl = -margin - fee  # full margin gone, plus entry fee (no exit fee on liq)
        else:
            pnl = margin * (realized_roe / 100.0) - fee - funding
        trades.append({
            "symbol": chosen, "side": side, "entry": i, "exit": exit_idx,
            "hold_h": hold_h, "pnl": pnl, "roe": realized_roe, "reason": exit_reason
        })
        if pnl < 0:
            last_loss_h = exit_idx
        last_exit_h = exit_idx
        i = exit_idx + 1
    return trades


def stats(trades, label, lev, mp):
    if not trades:
        return {"label": label, "n": 0}
    pnls = [t["pnl"] for t in trades]
    roes = [t["roe"] for t in trades]
    reasons = [t["reason"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    n_liq = sum(1 for r in reasons if "LIQ" in r)
    n_sl = sum(1 for r in reasons if r == "SL")
    n_tp = sum(1 for r in reasons if r == "TP")
    n_signal_off = sum(1 for r in reasons if "SIGNAL_OFF" in r)
    n_timeout = sum(1 for r in reasons if r == "TIMEOUT")
    avg_hold = np.mean([t["hold_h"] for t in trades])

    # Compute DD from cumulative PnL
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    max_dd = float(np.max(dd))

    # MC ruin: 10000 bootstrap runs of 76 trades each, ruin if cum drawdown ≥ EQUITY
    rng = np.random.default_rng(42)
    n_sims = 10000
    pnls_arr = np.array(pnls)
    ruin = 0
    for _ in range(n_sims):
        sample = rng.choice(pnls_arr, size=len(pnls), replace=True)
        cum_s = np.cumsum(sample)
        if cum_s.min() <= -EQUITY:
            ruin += 1
    ruin_pct = ruin / n_sims * 100

    return {
        "label": label, "lev": lev, "mp": mp,
        "n": len(trades),
        "wr": len(wins) / len(trades),
        "total_pnl": float(sum(pnls)),
        "avg_pnl": float(np.mean(pnls)),
        "avg_win": float(np.mean(wins)) if wins else 0.0,
        "avg_loss": float(np.mean(losses)) if losses else 0.0,
        "max_win": float(max(pnls)),
        "max_loss": float(min(pnls)),
        "max_dd": max_dd,
        "annual_pct": float(sum(pnls)) / EQUITY * 100 / 3.0,  # 3yr backtest
        "n_liquidated": n_liq,
        "n_sl": n_sl,
        "n_tp": n_tp,
        "n_signal_off": n_signal_off,
        "n_timeout": n_timeout,
        "avg_hold_h": float(avg_hold),
        "mc_ruin_pct": ruin_pct,
    }


def main():
    print("Loading 1h OHLCV (memes)...")
    universe = ["PEPEUSDT", "BONKUSDT", "WIFUSDT"]
    cache = {}
    for sym in universe:
        try:
            df = load_1h(sym)
            ind = compute_indicators(df)
            ind = add_extra_features(ind)
            ind = add_obv(ind)
            ind = compute_production_features(ind)
            cache[sym] = ind
            print(f"  {sym}: {len(ind['close'])} bars")
        except Exception as e:
            print(f"  {sym}: FAIL {e}")

    print(f"\n{'='*100}")
    print(f"PHASE 18: Hold-to-Recovery Hypothesis Test")
    print(f"Signal: momentum_obv (mom24>5% & ema20>ema50 & ADX>22 & vol_r>=1.3 & obv↑)")
    print(f"Universe: memes (PEPE/BONK/WIF)")
    print(f"Liquidation buffer: ROE <= -95% (price drop ~3.17% at 30x)")
    print(f"{'='*100}\n")

    results = []
    # Test at 30x mp=1.0 (한탕 full) — most aggressive
    LEV = 30
    MP = 1.0
    print(f"--- Leverage = {LEV}x, mp = {MP} ---")
    for policy in ["A_SL50_TP500", "B_hold_to_recovery", "C_signal_flip", "D_tp500_or_signal"]:
        trades = backtest_policy(universe, cache, LEV, MP, policy)
        s = stats(trades, policy, LEV, MP)
        results.append(s)
        if s["n"] > 0:
            print(f"  {policy:25s}: N={s['n']:3d} WR={s['wr']*100:5.1f}% "
                  f"PnL=${s['total_pnl']:+9.2f} ({s['annual_pct']:+7.1f}%/yr) "
                  f"DD=${s['max_dd']:6.2f} ruin={s['mc_ruin_pct']:5.1f}% "
                  f"liq={s['n_liquidated']:3d} sl={s['n_sl']:3d} tp={s['n_tp']:3d} "
                  f"sig_off={s['n_signal_off']:3d} hold_avg={s['avg_hold_h']:.1f}h")

    # Now show: at LOW leverage, "hold to recovery" actually works
    print(f"\n--- Same policy B (hold-to-recovery), but at multiple leverages ---")
    for LEV2 in [30, 10, 5, 3, 2]:
        # adjust mp so notional / liq distance changes meaningfully
        # keep margin same (mp=1.0) for purest comparison
        trades = backtest_policy(universe, cache, LEV2, 1.0, "B_hold_to_recovery")
        s = stats(trades, f"B@{LEV2}x", LEV2, 1.0)
        results.append(s)
        if s["n"] > 0:
            liq_price_pct = 95.0 / LEV2  # price drop that triggers liq
            print(f"  Lev={LEV2:2d}x (liq@-{liq_price_pct:.2f}% price): "
                  f"N={s['n']:3d} WR={s['wr']*100:5.1f}% PnL=${s['total_pnl']:+9.2f} "
                  f"liq={s['n_liquidated']:3d}/{s['n']} ({s['n_liquidated']/max(s['n'],1)*100:.1f}%) "
                  f"ruin={s['mc_ruin_pct']:5.1f}%")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({"results": results}, f, indent=2)
    print(f"\nSaved to {OUT}")


if __name__ == "__main__":
    main()
