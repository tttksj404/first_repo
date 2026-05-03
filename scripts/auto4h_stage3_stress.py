#!/usr/bin/env python3
"""auto4h Stage 3: Slippage/Fee stress + adjacent sensitivity for top winners.

Stage 2 결과에서 robust verdict 받은 모든 후보(top 20)에 대해:
  1) Slippage stress: {0, 5, 10, 15, 20} bps
  2) Cost stress: {1.0x, 1.5x, 2.0x} of baseline (0.12% RT)
  3) Funding stress: {1x, 2x, 3x} of baseline
  4) Adjacent param sens: best TP/SL ± 1 step (8 cells)

PASS criteria:
  - net > 0 at slip=10bps, cost=1.5x, funding=2x
  - >=6/8 adjacent cells profitable
"""
from __future__ import annotations
import sys, json, time
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv
from auto4h_signal_library import SIGNALS
from auto4h_stage1_matrix import precompute_btc_regime

LEVERAGE = 10
MARGIN = 50.0
LIQ_ROE = -95.0
SIGNAL_OFF_MIN_ROE = 0.0
COOLDOWN_AFTER_EXIT_H = 12
COOLDOWN_AFTER_LOSS_H = 24


def simulate_stress(ind, btc_regime, sig_fn, start_idx, end_idx,
                    tp_roe, sl_roe, mom_min,
                    slip_bps=8, cost_rt=0.0012, funding_8h=0.0001):
    trades = []
    in_pos = False; entry_px = 0.0; entry_idx = 0
    last_exit_i = -1; last_loss_i = -1
    slip = slip_bps / 10000.0

    for i in range(max(start_idx, 50), end_idx):
        if not in_pos:
            if last_exit_i >= 0 and (i - last_exit_i) < COOLDOWN_AFTER_EXIT_H: continue
            if last_loss_i >= 0 and (i - last_loss_i) < COOLDOWN_AFTER_LOSS_H: continue
            btc_r = bool(btc_regime[i]) if i < len(btc_regime) else False
            if not btc_r: continue
            if ind["mom24"][i] < mom_min: continue
            if not sig_fn(ind, i): continue
            entry_px = ind["close"][i] * (1 + slip)
            entry_idx = i; in_pos = True
        else:
            hi = ind["high"][i]; lo = ind["low"][i]; cl = ind["close"][i]
            roe_lo = (lo / entry_px - 1) * LEVERAGE * 100
            roe_hi = (hi / entry_px - 1) * LEVERAGE * 100
            roe_cl = (cl / entry_px - 1) * LEVERAGE * 100
            exit_roe = None; reason = None
            if roe_lo <= LIQ_ROE:
                exit_roe = -100.0; reason = "LIQ"
            elif roe_lo <= sl_roe:
                sl_px = entry_px * (1 + sl_roe/100/LEVERAGE)
                fill = sl_px * (1 - slip)
                exit_roe = (fill / entry_px - 1) * LEVERAGE * 100
                reason = "SL"
            elif roe_hi >= tp_roe:
                tp_px = entry_px * (1 + tp_roe/100/LEVERAGE)
                fill = tp_px * (1 - slip)
                exit_roe = (fill / entry_px - 1) * LEVERAGE * 100
                reason = "TP"
            else:
                if (not sig_fn(ind, i)) and roe_cl > SIGNAL_OFF_MIN_ROE:
                    fill = cl * (1 - slip)
                    exit_roe = (fill / entry_px - 1) * LEVERAGE * 100
                    reason = "SIG_OFF"
            if exit_roe is not None:
                hold_h = i - entry_idx
                notional = MARGIN * LEVERAGE
                fee = notional * cost_rt
                funding = notional * funding_8h * (hold_h / 8)
                if exit_roe <= -100:
                    pnl = -MARGIN - fee
                else:
                    pnl = MARGIN * (exit_roe / 100) - fee - funding
                trades.append({"pnl": pnl, "roe": exit_roe, "reason": reason, "hold_h": hold_h})
                in_pos = False; last_exit_i = i
                if pnl < 0: last_loss_i = i
    return trades


def aggregate_pnl(ind, btc_regime, sig_fn, folds, tp, sl, mom, slip, cost, fund):
    all_pnls = []
    for s_i, e_i in folds:
        ts = simulate_stress(ind, btc_regime, sig_fn, s_i, e_i, tp, sl, mom,
                             slip, cost, fund)
        all_pnls.extend([t["pnl"] for t in ts])
    if not all_pnls: return 0, 0, 0
    a = np.array(all_pnls)
    wins = a[a>0]; losses = a[a<0]
    pf = wins.sum()/abs(losses.sum()) if losses.sum()<0 else 99
    return float(a.sum()), float(pf), len(a)


def run():
    s2 = json.load(open("quant_runtime/output/auto4h/stage2_grid.json"))
    cands = s2["candidates"]
    robust = [c for c in cands if c["verdict"] == "✅ ROBUST"][:20]
    print(f"Stage 3: stress-testing {len(robust)} robust candidates")

    universe = sorted(set(c["symbol"] for c in robust) | {"BTCUSDT"})
    cache = {}
    for sym in universe:
        df = load_1h(sym)
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_regime = precompute_btc_regime(cache["BTCUSDT"])
    n_min = min(len(cache[s]["close"]) for s in universe)
    fold_size = n_min // 4
    folds = [(k*fold_size, (k+1)*fold_size if k<3 else n_min) for k in range(4)]

    results = []
    t0 = time.time()
    print(f"\n{'rank':>3} {'sig':<16} {'sym':<10} {'TP/SL':>9} "
          f"{'slip0':>8} {'slip5':>8} {'slip10':>8} {'slip20':>8} "
          f"{'cost1.5x':>9} {'fund3x':>8} {'adj/8':>6} verdict")
    for c in robust:
        sym = c["symbol"]; sig_fn = SIGNALS[c["signal"]]
        b = c["best"]; tp, sl, mom = b["tp"], b["sl"], c["mom_min"]
        ind = cache[sym]

        # slippage sweep
        slip_results = {}
        for sb in [0, 5, 10, 15, 20]:
            net, pf, n = aggregate_pnl(ind, btc_regime, sig_fn, folds, tp, sl, mom,
                                        sb, 0.0012, 0.0001)
            slip_results[sb] = {"net": net, "pf": pf, "n": n}

        # cost stress
        cost15 = aggregate_pnl(ind, btc_regime, sig_fn, folds, tp, sl, mom,
                                8, 0.0012*1.5, 0.0001)
        cost20 = aggregate_pnl(ind, btc_regime, sig_fn, folds, tp, sl, mom,
                                8, 0.0012*2.0, 0.0001)

        # funding stress
        fund3 = aggregate_pnl(ind, btc_regime, sig_fn, folds, tp, sl, mom,
                              8, 0.0012, 0.0003)

        # adjacent sensitivity (TP+/-1step, SL+/-1step from best)
        tp_levels = [30, 50, 80, 100, 150, 200, 300, 500]
        sl_levels = [-15, -20, -25, -30, -35, -40, -50]
        try: ti = tp_levels.index(tp)
        except: ti = -1
        try: si = sl_levels.index(sl)
        except: si = -1
        adj_pass = 0; adj_total = 0
        adj_cells = []
        for di in [-1, 0, 1]:
            for dj in [-1, 0, 1]:
                if di==0 and dj==0: continue
                if ti+di<0 or ti+di>=len(tp_levels): continue
                if si+dj<0 or si+dj>=len(sl_levels): continue
                tp_a = tp_levels[ti+di]; sl_a = sl_levels[si+dj]
                net_a, pf_a, n_a = aggregate_pnl(ind, btc_regime, sig_fn, folds,
                                                  tp_a, sl_a, mom, 8, 0.0012, 0.0001)
                adj_total += 1
                if net_a > 0: adj_pass += 1
                adj_cells.append({"tp": tp_a, "sl": sl_a, "net": net_a, "pf": pf_a})

        # verdict — must survive slip=10bps, cost=1.5x, fund=3x, and 6/8 adj cells profitable
        survived = (slip_results[10]["net"] > 0
                    and cost15[0] > 0
                    and fund3[0] > 0
                    and adj_pass >= max(adj_total - 2, 6))
        slip20_survived = slip_results[20]["net"] > 0
        # rank verdict
        if survived and slip20_survived:
            verdict = "🥇 STRONG"
        elif survived:
            verdict = "🥈 OK"
        elif slip_results[10]["net"] > 0:
            verdict = "⚠️ MARGINAL"
        else:
            verdict = "❌ WEAK"

        results.append({
            "signal": c["signal"], "symbol": sym, "mom_min": mom,
            "best_tp": tp, "best_sl": sl,
            "slip": slip_results,
            "cost15x": {"net": cost15[0], "pf": cost15[1]},
            "cost20x": {"net": cost20[0], "pf": cost20[1]},
            "fund3x": {"net": fund3[0], "pf": fund3[1]},
            "adj_pass": adj_pass, "adj_total": adj_total,
            "adj_cells": adj_cells,
            "verdict": verdict,
        })
        print(f"{len(results):>3} {c['signal']:<16} {sym:<10} {f'+{tp}/{sl}':>9} "
              f"${slip_results[0]['net']:>+6.0f} ${slip_results[5]['net']:>+6.0f} "
              f"${slip_results[10]['net']:>+6.0f} ${slip_results[20]['net']:>+6.0f} "
              f"${cost15[0]:>+7.0f} ${fund3[0]:>+6.0f} {adj_pass:>2}/{adj_total} {verdict}")

    # rank: STRONG > OK > MARGINAL, then by slip10 net
    rank_key = {"🥇 STRONG":0, "🥈 OK":1, "⚠️ MARGINAL":2, "❌ WEAK":3}
    results.sort(key=lambda r: (rank_key[r["verdict"]], -r["slip"][10]["net"]))

    print(f"\n=== STAGE 3 FINAL RANKING ===")
    print(f"{'rank':>4} {'sig':<16} {'sym':<10} {'mom':>5} {'TP/SL':>9} "
          f"{'net@slip10':>10} {'PF@slip10':>10} {'cost1.5x':>9} {'adj':>5} verdict")
    for i, r in enumerate(results):
        print(f"{i+1:>4} {r['signal']:<16} {r['symbol']:<10} {r['mom_min']*100:>4.0f}% "
              f"{f'+{r['best_tp']}/{r['best_sl']}':>9} "
              f"${r['slip'][10]['net']:>+9.0f} {r['slip'][10]['pf']:>9.2f} "
              f"${r['cost15x']['net']:>+8.0f} {r['adj_pass']}/{r['adj_total']} {r['verdict']}")

    out = Path("quant_runtime/output/auto4h/stage3_stress.json")
    with open(out, "w") as f:
        json.dump({"results": results}, f, indent=2, default=str)
    print(f"\n[saved] {out}")
    print(f"Stage 3 runtime: {time.time()-t0:.1f}s")

    strong = [r for r in results if r["verdict"] == "🥇 STRONG"]
    ok = [r for r in results if r["verdict"] == "🥈 OK"]
    print(f"\nFinal: {len(strong)} STRONG + {len(ok)} OK candidates")
    print(f"\n🥇 STRONG winners (paper bot candidates):")
    for r in strong:
        print(f"  {r['signal']:<16} {r['symbol']:<10} mom{r['mom_min']*100:.0f}% "
              f"TP+{r['best_tp']}/SL{r['best_sl']}: "
              f"slip10 ${r['slip'][10]['net']:+.0f} PF={r['slip'][10]['pf']:.2f}")


if __name__ == "__main__":
    run()
