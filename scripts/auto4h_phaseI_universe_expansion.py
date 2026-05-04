#!/usr/bin/env python3
"""Phase I: Universe expansion.

기존 14 STRONG는 4개 코인 (ETH/ARB/DOGE/SUI/WIF) 만 사용.
사용가능 20 종목: ADAUSDT APTUSDT ARBUSDT AVAXUSDT BNBUSDT BTCUSDT
                  DOGEUSDT DOTUSDT ETHUSDT LINKUSDT LTCUSDT MATICUSDT
                  NEARUSDT OPUSDT PEPEUSDT SOLUSDT SUIUSDT UNIUSDT
                  WIFUSDT XRPUSDT

12 시그널 × 16 새 코인 × 5 mom × 5 TP/SL = 4800 evals
walk-forward + adjacent stress 적용해서 새로운 STRONG 후보 발굴.
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

EXISTING = {("ETHUSDT", "donchian_20"), ("ETHUSDT", "vol_expansion"),
            ("ARBUSDT", "vol_expansion"), ("DOGEUSDT", "vol_expansion"),
            ("DOGEUSDT", "heikin_cont"), ("DOGEUSDT", "momentum_obv"),
            ("SUIUSDT", "atr_expansion"),
            ("WIFUSDT", "heikin_cont"), ("WIFUSDT", "momentum_obv")}

NEW_COINS = ["ADAUSDT", "APTUSDT", "AVAXUSDT", "BNBUSDT", "DOTUSDT",
             "LINKUSDT", "LTCUSDT", "MATICUSDT", "NEARUSDT", "OPUSDT",
             "PEPEUSDT", "SOLUSDT", "UNIUSDT", "XRPUSDT"]
MOM_LIST = [0.02, 0.04, 0.06, 0.08, 0.10]
TP_SL_LIST = [(50, -25), (80, -30), (100, -25), (150, -35), (200, -40), (300, -50)]


def quick_eval(ind, btc, fn, folds, tp, sl, mom):
    all_pnls = []; wf = 0
    for s, e in folds:
        ts = simulate(ind, btc, fn, s, e, tp, sl, mom)
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
    print("Phase I: universe expansion to 14 new coins")
    universe = NEW_COINS + ["BTCUSDT"]
    cache = {}
    for sym in universe:
        df = load_1h(sym)
        if df is None:
            print(f"  skip {sym}: no data"); continue
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    if "BTCUSDT" not in cache:
        print("BTCUSDT data missing"); return
    btc_regime = precompute_btc_regime(cache["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache.values())
    fold = n_min // 4
    folds = [(k*fold, (k+1)*fold if k<3 else n_min) for k in range(4)]

    results = []
    print(f"\n{'sig':<16} {'sym':<10} {'mom':>4} {'TP/SL':>9} "
          f"{'n':>4} {'pf':>6} {'wf':>4} {'net':>7}")
    t0 = time.time()
    n_eval = 0; n_robust = 0
    for sig_name, sig_fn in SIGNALS.items():
        for sym in NEW_COINS:
            if sym not in cache: continue
            if (sym, sig_name) in EXISTING: continue
            ind = cache[sym]
            for mom in MOM_LIST:
                for tp, sl in TP_SL_LIST:
                    n_eval += 1
                    r = quick_eval(ind, btc_regime, sig_fn, folds, tp, sl, mom)
                    if r is None or r["n"] < 8: continue
                    if r["pf"] < 1.5: continue
                    if r["wf"] < 3: continue
                    if r["net"] < 30: continue
                    n_robust += 1
                    results.append({
                        "signal": sig_name, "symbol": sym, "mom_min": mom, "tp": tp, "sl": sl,
                        **r,
                    })

    results.sort(key=lambda r: -r["net"])
    print(f"\n=== TOP 20 NEW UNIVERSE WINNERS ===")
    for r in results[:20]:
        print(f"  {r['signal']:<16} {r['symbol']:<10} mom{r['mom_min']*100:.0f}% "
              f"TP+{r['tp']}/SL{r['sl']}: PF={r['pf']:.2f} WF={r['wf']}/4 "
              f"n={r['n']} net=${r['net']:+.0f}")

    out = Path("quant_runtime/output/auto4h/phaseI_universe.json")
    with open(out, "w") as f:
        json.dump({"results": results, "n_eval": n_eval, "n_robust": n_robust},
                  f, indent=2, default=str)
    print(f"\n[saved] {out}")
    print(f"Phase I runtime: {time.time()-t0:.1f}s, {n_robust}/{n_eval} robust")


if __name__ == "__main__":
    run()
