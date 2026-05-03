#!/usr/bin/env python3
"""Phase V-validate: OOS + adj for Phase V extra short winners."""
from __future__ import annotations
import sys, json, time
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv
from auto4h_phaseQ_short_side import simulate_short, precompute_bear_regime
from auto4h_phaseV_extra_shorts import EXTRA_SHORT_SIGNALS


def quick_eval(ind, btc_bear, fn, folds, tp, sl, mom):
    all_pnls = []; wf = 0
    for s, e in folds:
        ts = simulate_short(ind, btc_bear, fn, s, e, tp, sl, mom)
        fp = [t["pnl"] for t in ts]
        if fp:
            a = np.array(fp); w = a[a>0].sum(); l = abs(a[a<0].sum())
            pf_f = w/l if l>0 else 99
            if pf_f > 1.0 and len(a) >= 3: wf += 1
        all_pnls.extend(fp)
    if not all_pnls: return None
    a = np.array(all_pnls); pf = a[a>0].sum() / max(abs(a[a<0].sum()), 1e-9)
    return {"net": float(a.sum()), "pf": float(pf), "n": len(a), "wf": int(wf)}


def folds_split(n, train_frac=0.7):
    train_end = int(n * train_frac)
    train_size = train_end // 4
    train_folds = [(k*train_size, (k+1)*train_size if k<3 else train_end) for k in range(4)]
    return train_folds, [(train_end, n)]


def run():
    print("Phase V-validate: OOS + adj for Phase V winners")
    inp = Path("quant_runtime/output/auto4h/phaseV_extra_shorts.json")
    data = json.loads(inp.read_text())
    cands = sorted(data["results"], key=lambda r: -r["net"])[:25]
    print(f"  validating top 25 of {len(data['results'])}")

    universe = sorted(set(r["symbol"] for r in cands) | {"BTCUSDT"})
    cache = {}
    for sym in universe:
        df = load_1h(sym)
        if df is None: continue
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_bear = precompute_bear_regime(cache["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache.values())
    train_folds, oos_folds = folds_split(n_min)

    def adj_eval(ind, fn, tp, sl, mom):
        cnt = 0
        for tp_v in [tp*0.8, tp, tp*1.2]:
            for sl_v in [sl*0.85, sl, sl*1.15]:
                for mom_v in [mom*0.85, mom, mom*1.15]:
                    r = quick_eval(ind, btc_bear, fn, train_folds, int(tp_v), sl_v, mom_v)
                    if r and r["pf"] >= 1.5 and r["wf"] >= 3:
                        cnt += 1
        return cnt

    print(f"\n{'sig':<24} {'sym':<8} {'mom':>4} {'TP/SL':>9} | "
          f"{'tr_pf':>5} {'tr_n':>4} | {'oos_pf':>6} {'oos_n':>5} {'oos_net':>7} adj/27 verdict")
    out = []
    t0 = time.time()
    for c in cands:
        sym = c["symbol"]; sig = c["signal"]; mom = c["mom_max"]; tp = c["tp"]; sl = c["sl"]
        if sym not in cache: continue
        fn = EXTRA_SHORT_SIGNALS[sig]; ind = cache[sym]
        tr = quick_eval(ind, btc_bear, fn, train_folds, tp, sl, mom)
        oo = quick_eval(ind, btc_bear, fn, oos_folds, tp, sl, mom)
        if tr is None or oo is None:
            verdict = "❌ FAIL"
            out.append({**c, "verdict": verdict})
            continue
        adj_pass = adj_eval(ind, fn, tp, sl, mom)
        if oo["pf"] >= 1.5 and oo["net"] > 0 and adj_pass >= 18:
            verdict = "🥇 OOS_STRONG"
        elif oo["pf"] >= 1.0 and oo["net"] > -30 and adj_pass >= 12:
            verdict = "🥈 OOS_OK"
        elif oo["n"] == 0:
            verdict = "⚠️ NO_OOS_TRADES"
        else:
            verdict = "❌ OOS_FAIL"
        out.append({**c, "train": tr, "oos": oo, "adj_pass": adj_pass, "verdict": verdict})
        print(f"{sig:<24} {sym:<8} {mom*100:>+3.0f}% {f'+{tp}/{sl}':>9} | "
              f"{tr['pf']:>5.2f} {tr['n']:>4} | {oo['pf']:>6.2f} {oo['n']:>5} ${oo['net']:>+5.0f} "
              f"{adj_pass:>3}/27 {verdict}")

    rank = {"🥇 OOS_STRONG":0,"🥈 OOS_OK":1,"⚠️ NO_OOS_TRADES":2,"❌ OOS_FAIL":3,"❌ FAIL":4}
    out.sort(key=lambda r: (rank.get(r["verdict"],5), -r.get("oos",{}).get("net",-1)))
    out_path = Path("quant_runtime/output/auto4h/phaseV_validate.json")
    with open(out_path, "w") as f:
        json.dump({"results": out}, f, indent=2, default=str)
    strong = [r for r in out if r["verdict"] == "🥇 OOS_STRONG"]
    ok = [r for r in out if r["verdict"] == "🥈 OOS_OK"]
    print(f"\n=== EXTRA SHORTS: {len(strong)} STRONG + {len(ok)} OK ===")
    for r in strong + ok:
        print(f"  {r['signal']:<24} {r['symbol']:<8} mom{r['mom_max']*100:>+3.0f}% "
              f"TP+{r['tp']}/SL{r['sl']}: OOS PF={r['oos']['pf']:.2f} "
              f"net=${r['oos']['net']:+.0f} adj={r['adj_pass']}/27")
    print(f"\n[saved] {out_path}")
    print(f"Phase V-validate runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    run()
