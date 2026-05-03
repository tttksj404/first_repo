#!/usr/bin/env python3
"""Phase 20: 10x + 전재산 + 한탕 최적화.

User question: "10배해도 전재산 다 넣는 그림이면 한탕 가능?"

Test design:
  - Lev = 10x, mp = 1.0 (full $50)
  - Multiple entry signals (momentum_obv, breakout_volexp, squeeze_release, vol_expansion)
  - Multiple exit policies optimized for "JACKPOT" (large TP target):
    L1: SL=-90 / TP=+1000 (가격 +100%) — pure 한탕
    L2: SL=-90 / TP=+500 + signal_off_inprofit
    L3: SL=-70 / TP=+1000 + signal_off_inprofit (>50%)
    L4: NO SL + signal_off_inprofit + TP=+500
    L5: SL=-90 / TP=+300 (가격 +30%, 더 자주 잡힘)
    L6: SL=-50 / TP=+200 + signal_off (검증용 baseline)

  - Time frame: 1년 단위 split (사용자: 3년은 길다)
  - Jackpot metrics:
    * max_win_pnl, top3_pnl
    * p_win >= +$50 (자본 2배), >= +$150 (4배), >= +$300 (7배)
    * trades_per_year, time_to_first_jackpot

Universes: memes (high-vol), majors (low-vol)
"""
from __future__ import annotations

import json, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import (  # type: ignore
    load_1h, compute_indicators, EQUITY, COST_RT, FUNDING_8H,
)
from quant_phase14_production_sim import compute_production_features
from quant_phase15_signal_library import (
    add_extra_features, entry_breakout_volexp, entry_squeeze_release,
)
from quant_phase16_robustness import add_obv, entry_momentum_obv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quant_runtime" / "master_engine_runs" / "phase20_10x_jackpot.json"
LIQ_BUFFER = 0.95
MAX_HOLD_H = 168


# Custom signal: vol expansion (BB width rank explodes + price up)
def entry_vol_expansion(ind, i, long_only=True):
    if i < 30: return 0
    if not (ind["bb_width_rank"][i] >= 0.7 and ind["mom24"][i] > 0.03
            and ind["close"][i] > ind["bb_upper"][i]
            and ind["vol_r"][i] >= 1.5):
        return 0
    return 1


SIGNALS = {
    "momentum_obv": entry_momentum_obv,
    "breakout_volexp": entry_breakout_volexp,
    "squeeze_release": entry_squeeze_release,
    "vol_expansion": entry_vol_expansion,
}


def simulate_v3(ind, entry_idx, side, lev, policy, n, sig_fn):
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

        if roe_lo <= -LIQ_BUFFER * 100:
            return -100.0, k, "LIQUIDATED"

        if policy == "L1_SL90_TP1000":
            if roe_lo <= -90: return -90.0, k, "SL"
            if roe_hi >= 1000: return 1000.0, k, "TP"
        elif policy == "L2_SL90_TP500_signal":
            if roe_lo <= -90: return -90.0, k, "SL"
            if roe_hi >= 500: return 500.0, k, "TP"
            if sig_fn(ind, k, True) == 0 and roe_cl > 50:
                return roe_cl, k, "SIGNAL_OFF_INPROFIT"
        elif policy == "L3_SL70_TP1000_signal":
            if roe_lo <= -70: return -70.0, k, "SL"
            if roe_hi >= 1000: return 1000.0, k, "TP"
            if sig_fn(ind, k, True) == 0 and roe_cl > 50:
                return roe_cl, k, "SIGNAL_OFF_INPROFIT"
        elif policy == "L4_NoSL_TP500_signal":
            if roe_hi >= 500: return 500.0, k, "TP"
            if sig_fn(ind, k, True) == 0 and roe_cl > 0:
                return roe_cl, k, "SIGNAL_OFF_INPROFIT"
        elif policy == "L5_SL90_TP300":
            if roe_lo <= -90: return -90.0, k, "SL"
            if roe_hi >= 300: return 300.0, k, "TP"
        elif policy == "L6_SL50_TP200_signal":
            if roe_lo <= -50: return -50.0, k, "SL"
            if roe_hi >= 200: return 200.0, k, "TP"
            if sig_fn(ind, k, True) == 0 and roe_cl > 30:
                return roe_cl, k, "SIGNAL_OFF_INPROFIT"

    if side == 1:
        roe = (ind["close"][end_idx] / entry_px - 1) * lev * 100
    else:
        roe = -(ind["close"][end_idx] / entry_px - 1) * lev * 100
    if roe <= -LIQ_BUFFER * 100:
        return -100.0, end_idx, "LIQ_AT_TIMEOUT"
    return roe, end_idx, "TIMEOUT"


def backtest(priority, cache, lev, mp, policy, sig_name, idx_start=200, cooldown_h=12, loss_cooldown_h=24):
    valid = [s for s in priority if s in cache]
    if not valid: return []
    n = min(len(cache[s]["close"]) for s in valid)
    idx_end = n - MAX_HOLD_H - 2
    sig_fn = SIGNALS[sig_name]
    trades = []
    last_loss_h = -1e9; last_exit_h = -1e9
    i = max(idx_start, 200)
    while i < idx_end:
        if i - last_loss_h < loss_cooldown_h: i += 1; continue
        if i - last_exit_h < cooldown_h: i += 1; continue
        chosen = None; side = 0
        for s in valid:
            sd = sig_fn(cache[s], i, True)
            if sd != 0: chosen = s; side = sd; break
        if chosen is None: i += 1; continue
        ind = cache[chosen]
        margin = EQUITY * mp
        notional = margin * lev
        fee = notional * COST_RT
        roe, exit_idx, reason = simulate_v3(ind, i, side, lev, policy, n, sig_fn)
        hold_h = max(1, exit_idx - i)
        funding = notional * FUNDING_8H * (hold_h // 8)
        if roe <= -100:
            pnl = -margin - fee
        else:
            pnl = margin * (roe / 100.0) - fee - funding
        trades.append({"sym": chosen, "pnl": pnl, "roe": roe, "reason": reason, "hold_h": hold_h, "entry_h": i})
        if pnl < 0: last_loss_h = exit_idx
        last_exit_h = exit_idx
        i = exit_idx + 1
    return trades


def jackpot_stats(trades, label, n_years):
    """Jackpot-focused metrics."""
    if not trades:
        return {"label": label, "n": 0}
    pnls = np.array([t["pnl"] for t in trades])
    pnls_sorted = np.sort(pnls)[::-1]
    reasons = [t["reason"] for t in trades]
    wins = pnls[pnls > 0]; losses = pnls[pnls <= 0]
    n_liq = sum(1 for r in reasons if "LIQ" in r)
    cum = np.cumsum(pnls); peak = np.maximum.accumulate(cum); dd = peak - cum

    rng = np.random.default_rng(42)
    ruin = 0
    for _ in range(5000):
        sample = rng.choice(pnls, size=len(pnls), replace=True)
        if np.cumsum(sample).min() <= -EQUITY: ruin += 1

    # Time to first jackpot (>=+$50 = 자본 2배)
    cum_pnl = 0
    cum_pnl_at_first_50 = None; idx_first_50 = None
    for idx, t in enumerate(trades):
        cum_pnl += t["pnl"]
        if cum_pnl_at_first_50 is None and t["pnl"] >= 50:
            cum_pnl_at_first_50 = cum_pnl
            idx_first_50 = idx

    return {
        "label": label, "n": len(trades),
        "n_per_year": len(trades) / n_years,
        "wr": float(len(wins) / len(trades)),
        "total_pnl": float(pnls.sum()),
        "annual_pct": float(pnls.sum()) / EQUITY * 100 / n_years,
        "max_win": float(pnls.max()),
        "top3_total": float(pnls_sorted[:3].sum()) if len(pnls) >= 3 else float(pnls_sorted.sum()),
        "n_jackpot_50": int(np.sum(pnls >= 50)),    # 2x
        "n_jackpot_100": int(np.sum(pnls >= 100)),  # 3x
        "n_jackpot_150": int(np.sum(pnls >= 150)),  # 4x
        "n_jackpot_300": int(np.sum(pnls >= 300)),  # 7x
        "p_jackpot_50": float(np.mean(pnls >= 50)),
        "p_jackpot_150": float(np.mean(pnls >= 150)),
        "max_dd": float(np.max(dd)),
        "max_loss": float(pnls.min()),
        "n_liq": n_liq,
        "liq_pct": n_liq / len(trades) * 100,
        "ruin_pct": ruin / 5000 * 100,
        "trades_to_first_jackpot": idx_first_50 + 1 if idx_first_50 is not None else None,
    }


def main():
    print("Loading...")
    universes = {
        "memes": ["PEPEUSDT", "BONKUSDT", "WIFUSDT"],
        "memes_full": ["PEPEUSDT", "BONKUSDT", "WIFUSDT", "DOGEUSDT", "SHIBUSDT"],
    }
    all_syms = sorted(set([s for u in universes.values() for s in u]))
    cache = {}
    for sym in all_syms:
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

    LEV = 10
    MP = 1.0  # 전재산 다 넣음
    n_years = 3.0
    signals = list(SIGNALS.keys())
    policies = ["L1_SL90_TP1000", "L2_SL90_TP500_signal", "L3_SL70_TP1000_signal",
                "L4_NoSL_TP500_signal", "L5_SL90_TP300", "L6_SL50_TP200_signal"]

    results = []
    print(f"\n{'='*130}")
    print(f"PHASE 20: 10x leverage + mp=1.0 (전재산 $50) + 한탕 최적화")
    print(f"{'='*130}\n")

    for u_name, u_syms in universes.items():
        print(f"--- Universe: {u_name} ---")
        for sig_name in signals:
            for policy in policies:
                trades = backtest(u_syms, cache, LEV, MP, policy, sig_name)
                s = jackpot_stats(trades, f"{u_name}|{sig_name}|{policy}", n_years)
                s.update({"universe": u_name, "signal": sig_name, "policy": policy})
                results.append(s)
                if s["n"] > 0:
                    print(f"  {sig_name:18s} | {policy:25s}: "
                          f"N={s['n']:3d} WR={s['wr']*100:5.1f}% "
                          f"$={s['total_pnl']:+8.1f} ({s['annual_pct']:+6.0f}%/y) "
                          f"max=${s['max_win']:6.1f} top3=${s['top3_total']:6.1f} "
                          f"jp50={s['n_jackpot_50']:2d} jp150={s['n_jackpot_150']:2d} "
                          f"liq={s['liq_pct']:4.1f}% ruin={s['ruin_pct']:4.1f}%")
        print()

    print(f"\n{'='*130}")
    print(f"TOP 10 by total_pnl (한탕 누적 수익 최대)")
    print(f"{'='*130}")
    valid = [r for r in results if r["n"] > 0]
    for r in sorted(valid, key=lambda r: r["total_pnl"], reverse=True)[:10]:
        print(f"  {r['label']:60s}: PnL=${r['total_pnl']:+8.1f} max=${r['max_win']:6.1f} "
              f"jp150={r['n_jackpot_150']:2d} liq={r['liq_pct']:4.1f}% ruin={r['ruin_pct']:4.1f}%")

    print(f"\n{'='*130}")
    print(f"TOP 10 by jackpot count (>= +$150 = 4배 한탕 빈도)")
    print(f"{'='*130}")
    for r in sorted(valid, key=lambda r: (r["n_jackpot_150"], r["total_pnl"]), reverse=True)[:10]:
        print(f"  {r['label']:60s}: jp150={r['n_jackpot_150']:2d} max=${r['max_win']:6.1f} "
              f"PnL=${r['total_pnl']:+8.1f} liq={r['liq_pct']:4.1f}% ruin={r['ruin_pct']:4.1f}%")

    print(f"\n{'='*130}")
    print(f"TOP 10 by Pareto (annual_pct - ruin_pct)")
    print(f"{'='*130}")
    for r in sorted(valid, key=lambda r: r["annual_pct"] - r["ruin_pct"], reverse=True)[:10]:
        print(f"  {r['label']:60s}: ({r['annual_pct']:+6.0f}%/y, ruin={r['ruin_pct']:4.1f}%) "
              f"max=${r['max_win']:6.1f} jp150={r['n_jackpot_150']:2d}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({"results": results}, f, indent=2)
    print(f"\nSaved to {OUT}")


if __name__ == "__main__":
    main()
