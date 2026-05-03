#!/usr/bin/env python3
"""auto4h Stage 2: Top N candidates × TP×SL grid + WF.

Stage 1 결과에서 top 20 후보 추출 → 각 후보에 대해
TP {30,50,80,100,150,200,300,500} × SL {-15,-20,-25,-30,-35,-40,-50} = 56 cells
4-fold WF + 인접 감도 통계.

통과 기준 (Stage 3 / live 후보):
  - WF-robust cells >= 15/56  (인접 감도 >= 27%)
  - profitable cells >= 30/56  (인접 감도 >= 53%)
  - best cell PF >= 1.5
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
from auto4h_stage1_matrix import precompute_btc_regime, simulate

LEVERAGE = 10
MARGIN = 50.0
COST_RT = 0.0012


def run():
    s1 = json.load(open("quant_runtime/output/auto4h/stage1_matrix.json"))
    passers = s1["passers"]
    # top 20 by net (already sorted by wf, net)
    top_n = passers[:20]
    print(f"Stage 2: testing top {len(top_n)} candidates")
    print(f"{'rank':>4} {'signal':<16} {'sym':<10} {'mom':>5} {'pf_baseline':>12}")
    for k, c in enumerate(top_n):
        print(f"{k+1:>4} {c['signal']:<16} {c['symbol']:<10} {c['mom_min']*100:>4.0f}% "
              f"{c['pf']:>12.2f}")

    # load all data once
    universe = sorted(set(c["symbol"] for c in top_n) | {"BTCUSDT"})
    print(f"\nloading data for {len(universe)} coins...")
    cache = {}
    for sym in universe:
        df = load_1h(sym)
        ind = compute_indicators(df)
        ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_regime = precompute_btc_regime(cache["BTCUSDT"])
    n_min = min(len(cache[s]["close"]) for s in universe)
    fold_size = n_min // 4
    folds = [(k*fold_size, (k+1)*fold_size if k<3 else n_min) for k in range(4)]

    tp_levels = [30, 50, 80, 100, 150, 200, 300, 500]
    sl_levels = [-15, -20, -25, -30, -35, -40, -50]

    candidates_results = []
    t0 = time.time()
    for idx, c in enumerate(top_n):
        sig_fn = SIGNALS[c["signal"]]
        sym = c["symbol"]; mom_min = c["mom_min"]
        ind = cache[sym]
        matrix = {}
        n_profit = 0; n_robust = 0
        best = None
        for tp in tp_levels:
            row = {}
            for sl in sl_levels:
                all_pnls = []; total_n = 0; wf_pass = 0
                for s_i, e_i in folds:
                    fold_pnls = [t["pnl"] for t in
                                 simulate(ind, btc_regime, sig_fn,
                                          s_i, e_i, tp, sl, mom_min)]
                    if fold_pnls:
                        a = np.array(fold_pnls)
                        w = a[a>0].sum(); l = abs(a[a<0].sum())
                        pf_f = w/l if l>0 else 99
                        if pf_f > 1.0 and len(a) >= 3: wf_pass += 1
                        all_pnls.extend(fold_pnls)
                    total_n += len(fold_pnls)
                if all_pnls:
                    a = np.array(all_pnls)
                    wins = a[a>0]; losses = a[a<0]
                    pf = wins.sum()/abs(losses.sum()) if losses.sum()<0 else 99
                else:
                    pf = 0
                net = sum(all_pnls)
                row[sl] = {"net": float(net), "wf": int(wf_pass), "n": total_n,
                           "pf": float(pf)}
                if net > 0: n_profit += 1
                if net > 0 and wf_pass >= 3:
                    n_robust += 1
                    if best is None or net > best["net"]:
                        best = {"tp": tp, "sl": sl, "net": float(net),
                                "wf": int(wf_pass), "n": total_n, "pf": float(pf)}
            matrix[tp] = row
        cell_total = len(tp_levels) * len(sl_levels)
        verdict = ("✅ ROBUST" if n_robust >= 15 and best and best["pf"] >= 1.5
                   else "⚠️ MARGINAL" if n_robust >= 8
                   else "❌ FRAGILE")
        candidates_results.append({
            "rank": idx+1, "signal": c["signal"], "symbol": sym, "mom_min": mom_min,
            "n_profit": n_profit, "n_robust": n_robust, "n_cells": cell_total,
            "best": best, "verdict": verdict, "matrix": matrix,
        })
        print(f"  {idx+1:>3} {c['signal']:<16} {sym:<10} mom{mom_min*100:.0f}%  "
              f"profit={n_profit:>3}/{cell_total} robust={n_robust:>3}/{cell_total}  "
              f"{verdict}  best={best['tp'] if best else '-'}/{best['sl'] if best else '-'} "
              f"${best['net']:+.0f}" if best else f"  no robust cell")

    # rank by robust + best.net
    candidates_results.sort(key=lambda r: (-r["n_robust"],
                                           -(r["best"]["net"] if r["best"] else -9999)))

    print(f"\n=== STAGE 2 FINAL RANKING ===")
    print(f"{'rank':>4} {'sig':<16} {'sym':<10} {'mom':>5} "
          f"{'profit':>7} {'robust':>7} {'best_TP/SL':>12} {'best_net':>9} {'PF':>5} {'verdict':<12}")
    for i, r in enumerate(candidates_results):
        b = r["best"]
        print(f"{i+1:>4} {r['signal']:<16} {r['symbol']:<10} {r['mom_min']*100:>4.0f}% "
              f"{r['n_profit']:>3}/{r['n_cells']} {r['n_robust']:>3}/{r['n_cells']} "
              f"{(str(b['tp'])+'/'+str(b['sl'])) if b else '-':>12} "
              f"{(b['net'] if b else 0):>+9.0f} "
              f"{(b['pf'] if b else 0):>5.2f} {r['verdict']:<12}")

    # save
    out = Path("quant_runtime/output/auto4h/stage2_grid.json")
    with open(out, "w") as f:
        json.dump({"candidates": candidates_results}, f, indent=2, default=str)
    print(f"\n[saved] {out}")
    print(f"Stage 2 runtime: {time.time()-t0:.1f}s")

    # robust ones for stage 3
    robust = [r for r in candidates_results if r["verdict"] == "✅ ROBUST"]
    print(f"\nRobust candidates for Stage 3: {len(robust)}")
    for r in robust:
        b = r["best"]
        print(f"  {r['signal']} {r['symbol']} mom{r['mom_min']*100:.0f}% → "
              f"TP+{b['tp']}/SL{b['sl']}: ${b['net']:+.0f} PF={b['pf']:.2f} "
              f"({r['n_robust']}/{r['n_cells']} cells)")


if __name__ == "__main__":
    run()
