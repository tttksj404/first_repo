#!/usr/bin/env python3
"""Phase 19: 10x leverage + 버티기 메커니즘 정밀 분석.

User question: "그럼 10배 수준으로 레버리지를 낮춰서 버티는건?"

Phase 18 quick result on memes: 10x mp=1.0 hold-to-recovery
  → WR=80.2%, PnL=+$44, liq=14.8%, ruin=72.9%

Now systematically explore 10x:
  - margin %: 0.25, 0.5, 1.0
  - 5 exit policies (SL/TP fix vs 버티기 vs 하이브리드)
  - 3 universes (memes, majors, all)

Goal: Find if there's a sweet spot where "10x + 버티기" = low ruin + good return.

Liquidation at 10x: ROE <= -95% = price drop ~9.5%
That's much rarer than 30x's -3.17%, but still happens in volatile alts.
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
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv, entry_momentum_obv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quant_runtime" / "master_engine_runs" / "phase19_10x_hold.json"
LIQ_BUFFER = 0.95
MAX_HOLD_H = 168  # 7 days


def simulate_v2(ind, entry_idx, side, lev, policy, n):
    """Extended exit policies."""
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

        # Liquidation always
        if roe_lo <= -LIQ_BUFFER * 100:
            return -100.0, k, "LIQUIDATED"

        if policy == "P1_SL50_TP200":
            # 10x용 - 가격 ±5%/+20%
            if roe_lo <= -50: return -50.0, k, "SL"
            if roe_hi >= 200: return 200.0, k, "TP"
        elif policy == "P2_HOLD_signal_off_inprofit":
            # 사용자 가설: 버티고 신호 종료시 익절
            sig = entry_momentum_obv(ind, k, long_only=True)
            if sig == 0 and roe_cl > 0:
                return roe_cl, k, "SIGNAL_OFF_INPROFIT"
        elif policy == "P3_SL90_signal_off_inprofit":
            # 청산 직전(-90%)에만 SL, 나머지는 신호 종료시 익절
            if roe_lo <= -90: return -90.0, k, "SL90"
            sig = entry_momentum_obv(ind, k, long_only=True)
            if sig == 0 and roe_cl > 0:
                return roe_cl, k, "SIGNAL_OFF_INPROFIT"
        elif policy == "P4_SL70_TP200_signal_off":
            # SL=-70%로 적당히 보호 + TP=+200% + 신호 종료 익절
            if roe_lo <= -70: return -70.0, k, "SL70"
            if roe_hi >= 200: return 200.0, k, "TP"
            sig = entry_momentum_obv(ind, k, long_only=True)
            if sig == 0 and roe_cl > 30:  # 30% 이상이면 신호 종료시 익절
                return roe_cl, k, "SIGNAL_OFF_INPROFIT"
        elif policy == "P5_SL50_TP500_signal":
            # Phase17 winner format scaled to 10x: SL=-50, TP=+500 (가격 +50%)
            if roe_lo <= -50: return -50.0, k, "SL"
            if roe_hi >= 500: return 500.0, k, "TP"
            # 신호 종료 시 50% 이상이면 익절
            sig = entry_momentum_obv(ind, k, long_only=True)
            if sig == 0 and roe_cl > 50:
                return roe_cl, k, "SIGNAL_OFF_INPROFIT"

    if side == 1:
        roe = (ind["close"][end_idx] / entry_px - 1) * lev * 100
    else:
        roe = -(ind["close"][end_idx] / entry_px - 1) * lev * 100
    if roe <= -LIQ_BUFFER * 100:
        return -100.0, end_idx, "LIQ_AT_TIMEOUT"
    return roe, end_idx, "TIMEOUT"


def backtest(priority, cache, lev, mp, policy, idx_start=200, cooldown_h=12, loss_cooldown_h=24):
    valid = [s for s in priority if s in cache]
    if not valid: return []
    n = min(len(cache[s]["close"]) for s in valid)
    idx_end = n - MAX_HOLD_H - 2
    trades = []
    last_loss_h = -1e9; last_exit_h = -1e9
    i = max(idx_start, 200)
    while i < idx_end:
        if i - last_loss_h < loss_cooldown_h: i += 1; continue
        if i - last_exit_h < cooldown_h: i += 1; continue
        chosen = None; side = 0
        for s in valid:
            sd = entry_momentum_obv(cache[s], i, True)
            if sd != 0: chosen = s; side = sd; break
        if chosen is None: i += 1; continue
        ind = cache[chosen]
        margin = EQUITY * mp
        notional = margin * lev
        fee = notional * COST_RT
        roe, exit_idx, reason = simulate_v2(ind, i, side, lev, policy, n)
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


def stats(trades, label):
    if not trades:
        return {"label": label, "n": 0}
    pnls = np.array([t["pnl"] for t in trades])
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
        "wr": float(len(wins) / len(trades)) if len(trades) else 0,
        "pnl": float(pnls.sum()),
        "annual_pct": float(pnls.sum()) / EQUITY * 100 / 3.0,
        "max_dd": float(np.max(dd)),
        "max_loss_pnl": float(pnls.min()),
        "max_win_pnl": float(pnls.max()),
        "n_liq": n_liq,
        "liq_pct": n_liq / len(trades) * 100,
        "ruin_pct": ruin / 5000 * 100,
        "avg_hold_h": float(np.mean([t["hold_h"] for t in trades])),
    }


def main():
    print("Loading 1h OHLCV...")
    universes = {
        "memes": ["PEPEUSDT", "BONKUSDT", "WIFUSDT"],
        "majors": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        "mixed": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "PEPEUSDT", "WIFUSDT"],
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
    policies = ["P1_SL50_TP200", "P2_HOLD_signal_off_inprofit", "P3_SL90_signal_off_inprofit",
                "P4_SL70_TP200_signal_off", "P5_SL50_TP500_signal"]
    mps = [0.25, 0.5, 1.0]

    results = []
    print(f"\n{'='*120}")
    print(f"PHASE 19: 10x leverage + 버티기 정밀 분석")
    print(f"{'='*120}\n")

    for u_name, u_syms in universes.items():
        print(f"--- Universe: {u_name} ({','.join(u_syms)}) ---")
        for mp in mps:
            for policy in policies:
                trades = backtest(u_syms, cache, LEV, mp, policy)
                s = stats(trades, f"{u_name}|mp={mp}|{policy}")
                s.update({"universe": u_name, "mp": mp, "policy": policy, "lev": LEV})
                results.append(s)
                if s["n"] > 0:
                    print(f"  mp={mp:.2f} {policy:35s}: N={s['n']:3d} WR={s['wr']*100:5.1f}% "
                          f"PnL=${s['pnl']:+8.2f} ({s['annual_pct']:+7.1f}%/yr) "
                          f"DD=${s['max_dd']:6.2f} liq={s['liq_pct']:5.1f}% "
                          f"ruin={s['ruin_pct']:5.1f}% avg_hold={s['avg_hold_h']:.1f}h")
        print()

    # Find Pareto-optimal: low ruin + good return
    print(f"\n{'='*120}")
    print(f"TOP 10 by (annual_pct - ruin_pct) — Pareto-optimal")
    print(f"{'='*120}")
    valid = [r for r in results if r["n"] > 0]
    valid.sort(key=lambda r: r["annual_pct"] - r["ruin_pct"], reverse=True)
    for r in valid[:10]:
        print(f"  {r['label']:55s}: N={r['n']:3d} WR={r['wr']*100:5.1f}% "
              f"PnL=${r['pnl']:+8.2f} ({r['annual_pct']:+7.1f}%/yr) "
              f"liq={r['liq_pct']:5.1f}% ruin={r['ruin_pct']:5.1f}%")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({"results": results}, f, indent=2)
    print(f"\nSaved to {OUT}")


if __name__ == "__main__":
    main()
