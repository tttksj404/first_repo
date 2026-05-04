#!/usr/bin/env python3
"""Phase D: Signal ensemble — top winners를 AND/OR 조합.

각 STRONG에 대한 보조 시그널을 더해 false positive 줄이기 (AND 조합).
또는 두 시그널 OR로 entry frequency 늘리기 (OR 조합).
"""
from __future__ import annotations
import sys, json, time
from pathlib import Path
import numpy as np
from itertools import combinations

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv
from auto4h_signal_library import SIGNALS
from auto4h_stage1_matrix import precompute_btc_regime, simulate

# 14 STRONG (signal, symbol, mom, tp, sl)
STRONG = [
    ("donchian_20",   "ETHUSDT",  0.02,  50, -35),
    ("vol_expansion", "ETHUSDT",  0.02,  50, -25),
    ("vol_expansion", "ARBUSDT",  0.04,  50, -20),
    ("vol_expansion", "DOGEUSDT", 0.04,  80, -30),
    ("heikin_cont",   "DOGEUSDT", 0.06,  80, -35),
    ("atr_expansion", "SUIUSDT",  0.02,  80, -35),
    ("atr_expansion", "SUIUSDT",  0.04, 150, -40),
    ("heikin_cont",   "WIFUSDT",  0.06, 100, -25),
]

UNIVERSE = sorted(set(s[1] for s in STRONG) | {"BTCUSDT"})


def make_and(fn1, fn2):
    return lambda ind, i: fn1(ind, i) and fn2(ind, i)

def make_or(fn1, fn2):
    return lambda ind, i: fn1(ind, i) or fn2(ind, i)


def quick_eval(ind, btc_regime, sig_fn, folds, tp, sl, mom):
    all_pnls = []; wf = 0
    for s, e in folds:
        ts = simulate(ind, btc_regime, sig_fn, s, e, tp, sl, mom)
        fp = [t["pnl"] for t in ts]
        if fp:
            a = np.array(fp); w = a[a>0].sum(); l = abs(a[a<0].sum())
            pf_f = w/l if l>0 else 99
            if pf_f > 1.0 and len(a) >= 3: wf += 1
        all_pnls.extend(fp)
    if not all_pnls: return None
    a = np.array(all_pnls); pf = a[a>0].sum() / max(abs(a[a<0].sum()), 1e-9)
    return {"net": float(a.sum()), "pf": float(pf), "n": len(a), "wf": int(wf)}


def run():
    print(f"Phase D: signal ensemble on {len(STRONG)} STRONG")
    cache = {}
    for sym in UNIVERSE:
        df = load_1h(sym)
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_regime = precompute_btc_regime(cache["BTCUSDT"])
    n_min = min(len(cache[s]["close"]) for s in UNIVERSE)
    fold = n_min // 4
    folds = [(k*fold, (k+1)*fold if k<3 else n_min) for k in range(4)]

    other_sigs = list(SIGNALS.keys())
    results = []
    t0 = time.time()

    for sig_name, sym, mom, tp, sl in STRONG:
        primary = SIGNALS[sig_name]
        ind = cache[sym]
        baseline = quick_eval(ind, btc_regime, primary, folds, tp, sl, mom)
        if baseline is None: continue
        for op_name, op_make in [("AND", make_and), ("OR", make_or)]:
            for other in other_sigs:
                if other == sig_name: continue
                ens = op_make(primary, SIGNALS[other])
                r = quick_eval(ind, btc_regime, ens, folds, tp, sl, mom)
                if r is None or r["n"] < 5: continue
                if r["wf"] < 3: continue
                if r["pf"] < 1.5: continue
                # only report improvement
                if r["net"] <= baseline["net"]: continue
                if r["pf"] < baseline["pf"] * 0.9: continue
                results.append({
                    "primary": sig_name, "secondary": other, "op": op_name,
                    "symbol": sym, "mom_min": mom, "tp": tp, "sl": sl,
                    "baseline_net": baseline["net"], "baseline_pf": baseline["pf"],
                    "baseline_n": baseline["n"], "baseline_wf": baseline["wf"],
                    **{f"ens_{k}": v for k, v in r.items()},
                })

    results.sort(key=lambda r: -r["ens_net"])
    print(f"\n=== TOP 20 ENSEMBLE IMPROVEMENTS ===")
    print(f"{'primary':<16} {'op':>3} {'secondary':<16} {'sym':<10} {'mom':>4} {'TP/SL':>9} "
          f"{'base_net':>9} {'ens_net':>9} {'base_pf':>7} {'ens_pf':>7} {'wf':>5}")
    for r in results[:20]:
        print(f"{r['primary']:<16} {r['op']:>3} {r['secondary']:<16} {r['symbol']:<10} "
              f"{r['mom_min']*100:>3.0f}% {f'+{r['tp']}/{r['sl']}':>9} "
              f"${r['baseline_net']:>+8.0f} ${r['ens_net']:>+8.0f} "
              f"{r['baseline_pf']:>7.2f} {r['ens_pf']:>7.2f} {r['ens_wf']}/4")

    out = Path("quant_runtime/output/auto4h/phaseD_ensemble.json")
    with open(out, "w") as f:
        json.dump({"results": results}, f, indent=2, default=str)
    print(f"\n[saved] {out}")
    print(f"Phase D runtime: {time.time()-t0:.1f}s, {len(results)} improvements")


if __name__ == "__main__":
    run()
