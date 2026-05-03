#!/usr/bin/env python3
"""Phase 22: 부분 재투자 (60% reinvest / 40% safe pocket) 최적화.

User logic: "10x 도박에서 벌면 40%만 safe pocket으로 빼두고 60%는 재투자"
        = Kelly-style bankroll management.

Test variants:
  V0: No reinvest (fixed margin = $50) — Phase 20 baseline
  V1: Simple reinvest_pct of profits added to working, rest to safe
       - 0.30, 0.40, 0.50, 0.60, 0.70 — including user's 0.60 base case
  V2: Jackpot cashout — when working >= 2*initial, take 50% to safe, reset working to 1.5*initial
  V3: Floor + all-to-safe (working capped at initial, all profits to safe)
  V4: Drawdown-aware — reinvest_pct scales: DD<30%→0.6, DD<50%→0.3, else 0
  V5: Bankroll refill — if working = 0, take $50 from safe (if available) to retry
       (user's "잃으면 safe에서 다시 시작" intent)

Base strategies (from Phase 20 winners):
  S1: 10x squeeze_release L1 (SL-90/TP+1000) — high jackpot
  S2: 10x vol_expansion L3 (SL-70/TP+1000/sig) — balanced
  S3: 10x vol_expansion L4 (NoSL/TP+500/sig) — NO-SL safe-ish
  S4: 10x momentum_obv P4 (SL-70/TP+200/sig>30%) — Phase 19 winner

For each base strategy, run 1 backtest to get ROE-per-trade sequence,
then apply each variant offline (deterministic, no randomness in reinvest math).

Metrics:
  - final_total = working + safe
  - final_safe = absolute "untouchable" wealth
  - max_total reached
  - n_trades_skipped (working=0)
  - n_safe_refills (V5 only)
  - MC ruin: bootstrap of trade SEQUENCE, redo reinvest math
    - "true ruin" = total wealth at end < initial $50
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
from quant_phase20_10x_jackpot import entry_vol_expansion, simulate_v3, SIGNALS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quant_runtime" / "master_engine_runs" / "phase22_partial_reinvest.json"

LIQ_BUFFER = 0.95
MAX_HOLD_H = 168
INITIAL = 50.0  # $50 starting capital


def collect_trade_roes(priority, cache, lev, policy, sig_name):
    """Run base backtest and return list of (roe%, hold_h) per trade."""
    valid = [s for s in priority if s in cache]
    if not valid: return []
    n = min(len(cache[s]["close"]) for s in valid)
    idx_end = n - MAX_HOLD_H - 2
    sig_fn = SIGNALS[sig_name]
    trades = []
    last_loss_h = -1e9; last_exit_h = -1e9
    i = max(200, 200)
    while i < idx_end:
        if i - last_loss_h < 24: i += 1; continue
        if i - last_exit_h < 12: i += 1; continue
        chosen = None; side = 0
        for s in valid:
            sd = sig_fn(cache[s], i, True)
            if sd != 0: chosen = s; side = sd; break
        if chosen is None: i += 1; continue
        ind = cache[chosen]
        roe, exit_idx, reason = simulate_v3(ind, i, side, lev, policy, n, sig_fn)
        hold_h = max(1, exit_idx - i)
        trades.append({"roe": roe, "hold_h": hold_h, "reason": reason})
        if roe < 0: last_loss_h = exit_idx
        last_exit_h = exit_idx
        i = exit_idx + 1
    return trades


def apply_reinvest(trade_roes, variant_name, lev=10, initial=INITIAL,
                   reinvest_pct=0.6, allow_refill=False):
    """Apply reinvestment policy to trade ROE sequence.

    Returns dict with:
      - history: per-trade (working, safe, pnl)
      - final_total, final_working, final_safe
      - max_total, max_working, min_working
      - n_executed, n_skipped, n_refills
    """
    working = initial
    safe = 0.0
    history = []
    n_skip = 0
    n_refill = 0
    peak_working = initial

    for t in trade_roes:
        roe = t["roe"]
        hold_h = t["hold_h"]

        # If working <= 0 and refill not allowed → skip
        if working < 1.0:  # 1$ minimum
            if allow_refill and safe >= initial:
                safe -= initial
                working = initial
                n_refill += 1
            else:
                n_skip += 1
                history.append({"working": working, "safe": safe, "pnl": 0.0, "skipped": True})
                continue

        margin = working
        notional = margin * lev
        fee = notional * COST_RT
        funding = notional * FUNDING_8H * (hold_h // 8)

        if roe <= -100:
            # liquidation
            pnl = -margin - fee
        else:
            pnl = margin * (roe / 100.0) - fee - funding

        # Variant-specific reinvest logic
        if variant_name == "V0_no_reinvest":
            # Fixed margin behavior — but here we use working as margin.
            # To match Phase20 fixed-margin, we'd need margin=$50 always.
            # Here V0 = all profit/loss to safe, working stays at initial.
            if pnl > 0:
                safe += pnl
            else:
                safe += pnl  # losses also from safe; working untouched
                # if safe < 0, treat as loss but working still $50
            # working stays at initial (constant)
            working = initial

        elif variant_name.startswith("V1_reinvest"):
            # Simple partial reinvest
            if pnl > 0:
                safe += pnl * (1 - reinvest_pct)
                working += pnl * reinvest_pct
            else:
                working += pnl  # losses fully from working
                if working < 0: working = 0

        elif variant_name == "V2_jackpot_cashout":
            # Reinvest 100% normally; when working >= 2*initial, cashout 50%
            if pnl > 0:
                working += pnl
                if working >= 2 * initial:
                    excess = working - 1.5 * initial
                    cashout = excess * 0.5
                    safe += cashout
                    working -= cashout
            else:
                working += pnl
                if working < 0: working = 0

        elif variant_name == "V3_floor_all_to_safe":
            # All profit to safe; working capped at initial
            # Losses come from working (and refill from safe if needed)
            if pnl > 0:
                safe += pnl
                working = min(working, initial)  # cap
            else:
                working += pnl
                if working < 0:
                    deficit = -working
                    if safe >= deficit:
                        safe -= deficit
                        working = 0
                    else:
                        working = 0
                # Try to refill working back to initial from safe
                if working < initial and safe >= (initial - working):
                    refill_amt = initial - working
                    safe -= refill_amt
                    working = initial

        elif variant_name == "V4_drawdown_aware":
            # Reinvest_pct varies with drawdown
            dd_pct = 1.0 - (working / max(peak_working, 1e-9))
            if dd_pct < 0.3:
                rp = 0.6
            elif dd_pct < 0.5:
                rp = 0.3
            else:
                rp = 0.0
            if pnl > 0:
                safe += pnl * (1 - rp)
                working += pnl * rp
            else:
                working += pnl
                if working < 0: working = 0

        elif variant_name == "V5_bankroll_refill":
            # Same as V1 reinvest 60%, but allow safe→working refill
            if pnl > 0:
                safe += pnl * (1 - reinvest_pct)
                working += pnl * reinvest_pct
            else:
                working += pnl
                if working < 0: working = 0

        peak_working = max(peak_working, working)

        history.append({"working": working, "safe": safe, "pnl": pnl})

    totals = [h["working"] + h["safe"] for h in history if not h.get("skipped")]
    return {
        "variant": variant_name,
        "reinvest_pct": reinvest_pct if "reinvest" in variant_name or "bankroll" in variant_name else None,
        "final_working": working,
        "final_safe": safe,
        "final_total": working + safe,
        "max_total": max(totals) if totals else initial,
        "min_working": min(h["working"] for h in history) if history else initial,
        "n_executed": len([h for h in history if not h.get("skipped")]),
        "n_skipped": n_skip,
        "n_refills": n_refill,
        "history_summary": {
            "first10_total": [h["working"] + h["safe"] for h in history[:10]],
            "first10_safe": [h["safe"] for h in history[:10]],
        },
    }


def mc_ruin_with_variant(trade_roes, variant_name, n_sims=2000, **kwargs):
    """Bootstrap the trade SEQUENCE, apply variant, count if final_total < initial."""
    rng = np.random.default_rng(42)
    n = len(trade_roes)
    if n == 0:
        return {"ruin_pct": 100.0, "median_total": INITIAL}
    ruin = 0
    medians = []
    for _ in range(n_sims):
        # Sample with replacement to preserve distribution
        idxs = rng.choice(n, size=n, replace=True)
        sampled = [trade_roes[i] for i in idxs]
        result = apply_reinvest(sampled, variant_name, **kwargs)
        if result["final_total"] < INITIAL:
            ruin += 1
        medians.append(result["final_total"])
    return {
        "ruin_pct": ruin / n_sims * 100,
        "median_total": float(np.median(medians)),
        "p25_total": float(np.percentile(medians, 25)),
        "p75_total": float(np.percentile(medians, 75)),
        "p90_total": float(np.percentile(medians, 90)),
        "p99_total": float(np.percentile(medians, 99)),
    }


def main():
    print("Loading data...")
    universe = ["PEPEUSDT", "WIFUSDT", "DOGEUSDT"]
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

    LEV = 10
    base_strategies = {
        "S1_squeeze_L1":     ("squeeze_release", "L1_SL90_TP1000"),
        "S2_volexp_L3":      ("vol_expansion",   "L3_SL70_TP1000_signal"),
        "S3_volexp_L4_NoSL": ("vol_expansion",   "L4_NoSL_TP500_signal"),
        "S4_momentum_obv_P4": None,  # Special case from Phase 19
    }

    all_results = []

    for s_name, sigpol in base_strategies.items():
        if sigpol is None:
            continue
        sig_name, policy = sigpol
        print(f"\n--- Base strategy: {s_name} ({sig_name} | {policy}) ---")
        trades = collect_trade_roes(universe, cache, LEV, policy, sig_name)
        if not trades:
            print(f"  No trades. Skip.")
            continue
        roes = [t["roe"] for t in trades]
        n_liq = sum(1 for t in trades if t["roe"] <= -100)
        print(f"  N={len(trades)}, liq={n_liq} ({n_liq/len(trades)*100:.1f}%), "
              f"mean_roe={np.mean(roes):.1f}%, max_roe={max(roes):.0f}%")

        # Variants
        variants_to_test = [
            ("V0_no_reinvest", {}),
            ("V1_reinvest_30", {"reinvest_pct": 0.30}),
            ("V1_reinvest_40", {"reinvest_pct": 0.40}),
            ("V1_reinvest_50", {"reinvest_pct": 0.50}),
            ("V1_reinvest_60", {"reinvest_pct": 0.60}),  # USER's request
            ("V1_reinvest_70", {"reinvest_pct": 0.70}),
            ("V2_jackpot_cashout", {}),
            ("V3_floor_all_to_safe", {}),
            ("V4_drawdown_aware", {}),
            ("V5_bankroll_refill", {"reinvest_pct": 0.60, "allow_refill": True}),
        ]

        for v_name, kwargs in variants_to_test:
            # Deterministic application on actual sequence
            result = apply_reinvest(trades, v_name, lev=LEV, initial=INITIAL, **kwargs)
            # MC bootstrap
            mc = mc_ruin_with_variant(trades, v_name, n_sims=2000, lev=LEV, initial=INITIAL, **kwargs)
            row = {"strategy": s_name, "variant": v_name,
                   "reinvest_pct": kwargs.get("reinvest_pct"),
                   "n_trades": len(trades), "n_liq": n_liq,
                   "final_total": result["final_total"],
                   "final_safe": result["final_safe"],
                   "final_working": result["final_working"],
                   "max_total": result["max_total"],
                   "n_executed": result["n_executed"],
                   "n_skipped": result["n_skipped"],
                   "n_refills": result["n_refills"],
                   "ruin_pct": mc["ruin_pct"],
                   "median_total": mc["median_total"],
                   "p25_total": mc["p25_total"],
                   "p75_total": mc["p75_total"],
                   "p90_total": mc["p90_total"],
                   "p99_total": mc["p99_total"],
                   }
            all_results.append(row)

        # Print results for this strategy
        print(f"\n  {'Variant':28s} {'final_total':>12s} {'safe':>10s} {'work':>8s} "
              f"{'max':>10s} {'p25':>8s} {'p75':>8s} {'p99':>8s} {'ruin%':>7s}")
        for r in all_results[-len(variants_to_test):]:
            label = r["variant"]
            if r["reinvest_pct"] is not None:
                label = f"{r['variant']}({r['reinvest_pct']:.2f})"
            print(f"  {label:28s} ${r['final_total']:11.2f} ${r['final_safe']:9.2f} ${r['final_working']:7.2f} "
                  f"${r['max_total']:9.2f} ${r['p25_total']:7.2f} ${r['p75_total']:7.2f} ${r['p99_total']:7.2f} "
                  f"{r['ruin_pct']:6.1f}%")

    print(f"\n{'='*150}")
    print("TOP 10 by Pareto: median_total - 0.5*ruin_pct (안 잃기 + 기대값)")
    print(f"{'='*150}")
    for r in sorted(all_results, key=lambda r: r["median_total"] - 0.5*r["ruin_pct"], reverse=True)[:10]:
        rp = f" rp={r['reinvest_pct']:.2f}" if r["reinvest_pct"] is not None else ""
        print(f"  {r['strategy']:20s} {r['variant']:25s}{rp}: "
              f"final=${r['final_total']:8.2f} safe=${r['final_safe']:8.2f} "
              f"med=${r['median_total']:7.2f} p99=${r['p99_total']:8.2f} ruin={r['ruin_pct']:5.1f}%")

    print(f"\n{'='*150}")
    print("TOP 10 by p99_total (잭팟 가능성)")
    print(f"{'='*150}")
    for r in sorted(all_results, key=lambda r: r["p99_total"], reverse=True)[:10]:
        rp = f" rp={r['reinvest_pct']:.2f}" if r["reinvest_pct"] is not None else ""
        print(f"  {r['strategy']:20s} {r['variant']:25s}{rp}: "
              f"p99=${r['p99_total']:8.2f} med=${r['median_total']:7.2f} ruin={r['ruin_pct']:5.1f}%")

    print(f"\n{'='*150}")
    print("LOWEST RUIN%")
    print(f"{'='*150}")
    for r in sorted(all_results, key=lambda r: (r["ruin_pct"], -r["median_total"]))[:10]:
        rp = f" rp={r['reinvest_pct']:.2f}" if r["reinvest_pct"] is not None else ""
        print(f"  {r['strategy']:20s} {r['variant']:25s}{rp}: "
              f"ruin={r['ruin_pct']:5.1f}% med=${r['median_total']:7.2f} safe=${r['final_safe']:8.2f}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({"results": all_results}, f, indent=2, default=str)
    print(f"\nSaved to {OUT}")


if __name__ == "__main__":
    main()
