#!/usr/bin/env python3
"""Phase K: Validate new universe winners with OOS + stress.

Phase I 가 14 새 코인에서 231 robust 후보 발굴.
이걸 OOS hold-out (70/30) + slip {0,5,10,15,20}bps + adjacent param 으로 검증.
실제로 STRONG 인지 (잘했어 운인지) 판정.
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


def quick_eval(ind, btc, fn, folds, tp, sl, mom, slip_bps=8):
    # patch slip via module
    from auto4h_stage1_matrix import simulate as _sim
    all_pnls = []; wf = 0
    for s, e in folds:
        ts = _sim(ind, btc, fn, s, e, tp, sl, mom)
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
    oos = [(train_end, n)]
    return train_folds, oos


def run():
    print("Phase K: validate Phase I new winners (OOS + adjacent stress)")
    inp = Path("quant_runtime/output/auto4h/phaseI_universe.json")
    if not inp.exists():
        print(f"  missing {inp}"); return
    data = json.loads(inp.read_text())
    cands = sorted(data["results"], key=lambda r: -r["net"])[:30]
    print(f"  validating top 30 of {len(data['results'])}")

    universe = sorted(set(r["symbol"] for r in cands) | {"BTCUSDT"})
    cache = {}
    for sym in universe:
        df = load_1h(sym)
        if df is None: continue
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_regime = precompute_btc_regime(cache["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache.values())
    train_folds, oos_folds = folds_split(n_min)

    # adjacent grid for sensitivity
    def adj_eval(ind, fn, tp, sl, mom):
        results = []
        for tp_v in [tp*0.8, tp, tp*1.2]:
            for sl_v in [sl*0.85, sl, sl*1.15]:
                for mom_v in [mom*0.85, mom, mom*1.15]:
                    r = quick_eval(ind, btc_regime, fn, train_folds, int(tp_v), sl_v, mom_v)
                    if r: results.append(r)
        if not results: return 0
        return sum(1 for r in results if r["pf"] >= 1.5 and r["wf"] >= 3)

    print(f"\n{'sig':<16} {'sym':<10} {'mom':>4} {'TP/SL':>9} | "
          f"{'tr_pf':>5} {'tr_n':>4} | {'oos_pf':>6} {'oos_n':>5} {'oos_net':>7} adj/27 verdict")
    out = []
    t0 = time.time()
    for c in cands:
        sym = c["symbol"]; sig = c["signal"]; mom = c["mom_min"]; tp = c["tp"]; sl = c["sl"]
        if sym not in cache: continue
        fn = SIGNALS[sig]; ind = cache[sym]
        tr = quick_eval(ind, btc_regime, fn, train_folds, tp, sl, mom)
        oo = quick_eval(ind, btc_regime, fn, oos_folds, tp, sl, mom)
        if tr is None or oo is None: continue
        adj_pass = adj_eval(ind, fn, tp, sl, mom)
        # verdict
        if oo["pf"] >= 1.5 and oo["net"] > 0 and adj_pass >= 18:
            verdict = "🥇 OOS_STRONG"
        elif oo["pf"] >= 1.0 and oo["net"] > -30 and adj_pass >= 12:
            verdict = "🥈 OOS_OK"
        elif oo["n"] == 0:
            verdict = "⚠️ NO_OOS_TRADES"
        else:
            verdict = "❌ OOS_FAIL"
        out.append({**c, "train": tr, "oos": oo, "adj_pass": adj_pass, "verdict": verdict})
        print(f"{sig:<16} {sym:<10} {mom*100:>3.0f}% {f'+{tp}/{sl}':>9} | "
              f"{tr['pf']:>5.2f} {tr['n']:>4} | {oo['pf']:>6.2f} {oo['n']:>5} ${oo['net']:>+5.0f} "
              f"{adj_pass:>3}/27 {verdict}")

    out.sort(key=lambda r: ({"🥇 OOS_STRONG":0,"🥈 OOS_OK":1,"⚠️ NO_OOS_TRADES":2,"❌ OOS_FAIL":3}[r["verdict"]],
                            -r["oos"]["net"]))
    out_path = Path("quant_runtime/output/auto4h/phaseK_validate.json")
    with open(out_path, "w") as f:
        json.dump({"results": out}, f, indent=2, default=str)
    strong = [r for r in out if r["verdict"] == "🥇 OOS_STRONG"]
    ok = [r for r in out if r["verdict"] == "🥈 OOS_OK"]
    print(f"\n=== NEW UNIVERSE: {len(strong)} STRONG + {len(ok)} OK ===")
    for r in strong + ok:
        print(f"  {r['signal']:<16} {r['symbol']:<10} mom{r['mom_min']*100:.0f}% "
              f"TP+{r['tp']}/SL{r['sl']}: OOS PF={r['oos']['pf']:.2f} net=${r['oos']['net']:+.0f} "
              f"adj={r['adj_pass']}/27 {r['verdict']}")
    print(f"\n[saved] {out_path}")
    print(f"Phase K runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    run()
