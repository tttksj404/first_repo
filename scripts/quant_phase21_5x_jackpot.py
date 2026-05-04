#!/usr/bin/env python3
"""Phase 21: 5x leverage + mp=1.0 (전재산) 한탕 최적화.

User progression:
  - 30x mp=1.0 → ruin 87.7%, +2552%/y, max win $248
  - 10x mp=1.0 squeeze L1 → ruin 79%, +352%/y, max win $498
  - 5x mp=1.0 → ?

5x context:
  - Liquidation: price -19% (vs 10x's -9.5%, 30x's -3.17%)
  - ROE per +20% price = +100%
  - ROE per +50% price = +250%
  - ROE per +100% price = +500% (large jackpot)
  - ROE per +200% price = +1000% (mega jackpot — rare)

So we need TPs set in PRICE terms, not ROE:
  Q1: SL=-90 (price -18%) / TP=+500 (price +100%) — pure jackpot, still aggressive
  Q2: SL=-90 / TP=+250 (price +50%) + signal off
  Q3: SL=-50 (price -10%) / TP=+200 (price +40%) + signal off in profit
  Q4: NO SL / TP=+250 + signal off in profit (사용자 가설 NO-SL)
  Q5: SL=-70 (price -14%) / TP=+500 + signal off (>50%)
  Q6: SL=-90 / TP=+1000 (price +200%) - mega jackpot
  Q7: SL=-50 / TP=+100 (price +20%) + signal off — high-freq small wins
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
from quant_phase20_10x_jackpot import entry_vol_expansion

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quant_runtime" / "master_engine_runs" / "phase21_5x_jackpot.json"
LIQ_BUFFER = 0.95
MAX_HOLD_H = 168 * 2  # 14 days at 5x — slower moves


SIGNALS = {
    "momentum_obv": entry_momentum_obv,
    "breakout_volexp": entry_breakout_volexp,
    "squeeze_release": entry_squeeze_release,
    "vol_expansion": entry_vol_expansion,
}


def simulate_v4(ind, entry_idx, side, lev, policy, n, sig_fn):
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

        if policy == "Q1_SL90_TP500":
            if roe_lo <= -90: return -90.0, k, "SL"
            if roe_hi >= 500: return 500.0, k, "TP"
        elif policy == "Q2_SL90_TP250_signal":
            if roe_lo <= -90: return -90.0, k, "SL"
            if roe_hi >= 250: return 250.0, k, "TP"
            if sig_fn(ind, k, True) == 0 and roe_cl > 30:
                return roe_cl, k, "SIGNAL_OFF_INPROFIT"
        elif policy == "Q3_SL50_TP200_signal":
            if roe_lo <= -50: return -50.0, k, "SL"
            if roe_hi >= 200: return 200.0, k, "TP"
            if sig_fn(ind, k, True) == 0 and roe_cl > 20:
                return roe_cl, k, "SIGNAL_OFF_INPROFIT"
        elif policy == "Q4_NoSL_TP250_signal":
            # 사용자 직관 NO-SL
            if roe_hi >= 250: return 250.0, k, "TP"
            if sig_fn(ind, k, True) == 0 and roe_cl > 0:
                return roe_cl, k, "SIGNAL_OFF_INPROFIT"
        elif policy == "Q5_SL70_TP500_signal":
            if roe_lo <= -70: return -70.0, k, "SL"
            if roe_hi >= 500: return 500.0, k, "TP"
            if sig_fn(ind, k, True) == 0 and roe_cl > 50:
                return roe_cl, k, "SIGNAL_OFF_INPROFIT"
        elif policy == "Q6_SL90_TP1000":
            # mega jackpot - price +200%
            if roe_lo <= -90: return -90.0, k, "SL"
            if roe_hi >= 1000: return 1000.0, k, "TP"
        elif policy == "Q7_SL50_TP100_signal":
            # 잦은 작은 한 방
            if roe_lo <= -50: return -50.0, k, "SL"
            if roe_hi >= 100: return 100.0, k, "TP"
            if sig_fn(ind, k, True) == 0 and roe_cl > 0:
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
        roe, exit_idx, reason = simulate_v4(ind, i, side, lev, policy, n, sig_fn)
        hold_h = max(1, exit_idx - i)
        funding = notional * FUNDING_8H * (hold_h // 8)
        if roe <= -100:
            pnl = -margin - fee
        else:
            pnl = margin * (roe / 100.0) - fee - funding
        trades.append({"sym": chosen, "pnl": pnl, "roe": roe, "reason": reason, "hold_h": hold_h})
        if pnl < 0: last_loss_h = exit_idx
        last_exit_h = exit_idx
        i = exit_idx + 1
    return trades


def jackpot_stats(trades, label, n_years):
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
    return {
        "label": label, "n": len(trades),
        "n_per_year": len(trades) / n_years,
        "wr": float(len(wins) / len(trades)),
        "total_pnl": float(pnls.sum()),
        "annual_pct": float(pnls.sum()) / EQUITY * 100 / n_years,
        "max_win": float(pnls.max()),
        "top3_total": float(pnls_sorted[:3].sum()) if len(pnls) >= 3 else float(pnls_sorted.sum()),
        "n_jackpot_50": int(np.sum(pnls >= 50)),
        "n_jackpot_100": int(np.sum(pnls >= 100)),
        "n_jackpot_150": int(np.sum(pnls >= 150)),
        "n_jackpot_300": int(np.sum(pnls >= 300)),
        "max_dd": float(np.max(dd)),
        "max_loss": float(pnls.min()),
        "n_liq": n_liq,
        "liq_pct": n_liq / len(trades) * 100,
        "ruin_pct": ruin / 5000 * 100,
        "avg_hold_h": float(np.mean([t["hold_h"] for t in trades])),
    }


def main():
    print("Loading...")
    universes = {
        "memes": ["PEPEUSDT", "BONKUSDT", "WIFUSDT", "DOGEUSDT", "SHIBUSDT"],
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

    LEV = 5
    MP = 1.0
    n_years = 3.0
    signals = list(SIGNALS.keys())
    policies = ["Q1_SL90_TP500", "Q2_SL90_TP250_signal", "Q3_SL50_TP200_signal",
                "Q4_NoSL_TP250_signal", "Q5_SL70_TP500_signal", "Q6_SL90_TP1000",
                "Q7_SL50_TP100_signal"]

    results = []
    print(f"\n{'='*135}")
    print(f"PHASE 21: 5x leverage + mp=1.0 (전재산 $50) 한탕 최적화")
    print(f"  Liquidation: price -19%   |   ROE +500% = price +100%   |   ROE +1000% = price +200%")
    print(f"{'='*135}\n")

    for u_name, u_syms in universes.items():
        print(f"--- Universe: {u_name} ---")
        for sig_name in signals:
            for policy in policies:
                trades = backtest(u_syms, cache, LEV, MP, policy, sig_name)
                s = jackpot_stats(trades, f"{sig_name}|{policy}", n_years)
                s.update({"signal": sig_name, "policy": policy})
                results.append(s)
                if s["n"] > 0:
                    print(f"  {sig_name:18s} | {policy:25s}: "
                          f"N={s['n']:3d} WR={s['wr']*100:5.1f}% "
                          f"$={s['total_pnl']:+8.1f} ({s['annual_pct']:+6.0f}%/y) "
                          f"max=${s['max_win']:6.1f} top3=${s['top3_total']:6.1f} "
                          f"jp50={s['n_jackpot_50']:2d} jp150={s['n_jackpot_150']:2d} "
                          f"liq={s['liq_pct']:4.1f}% ruin={s['ruin_pct']:5.1f}%")
        print()

    print(f"\n{'='*135}")
    print(f"TOP 10 by total_pnl (한탕 누적 수익 최대)")
    print(f"{'='*135}")
    valid = [r for r in results if r["n"] > 0]
    for r in sorted(valid, key=lambda r: r["total_pnl"], reverse=True)[:10]:
        print(f"  {r['label']:50s}: PnL=${r['total_pnl']:+8.1f} max=${r['max_win']:6.1f} "
              f"jp150={r['n_jackpot_150']:2d} liq={r['liq_pct']:4.1f}% ruin={r['ruin_pct']:5.1f}%")

    print(f"\n{'='*135}")
    print(f"TOP 10 by max_win (한 방 최대)")
    print(f"{'='*135}")
    for r in sorted(valid, key=lambda r: r["max_win"], reverse=True)[:10]:
        print(f"  {r['label']:50s}: max=${r['max_win']:6.1f} jp150={r['n_jackpot_150']:2d} "
              f"PnL=${r['total_pnl']:+8.1f} ruin={r['ruin_pct']:5.1f}%")

    print(f"\n{'='*135}")
    print(f"TOP 10 by Pareto (annual_pct - ruin_pct) — 살아남기 + 수익 균형")
    print(f"{'='*135}")
    for r in sorted(valid, key=lambda r: r["annual_pct"] - r["ruin_pct"], reverse=True)[:10]:
        print(f"  {r['label']:50s}: ({r['annual_pct']:+6.0f}%/y, ruin={r['ruin_pct']:5.1f}%) "
              f"max=${r['max_win']:6.1f} jp150={r['n_jackpot_150']:2d}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({"results": results}, f, indent=2)
    print(f"\nSaved to {OUT}")


if __name__ == "__main__":
    main()
