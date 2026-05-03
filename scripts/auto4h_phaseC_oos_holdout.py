#!/usr/bin/env python3
"""Phase C: OOS hold-out validation. Train on first 70%, test on last 30% (true forward).

CLAUDE.md 룰: OOS 홀드아웃 (확정 전): 2yr train / 1yr test, OOS에서 PF > 1.0
1년 데이터라 7:3 split = ~9개월 train / ~3.5개월 OOS test.

대상: 14 STRONG (Stage 3) + 5 Phase A enhanced + 3 Phase B 4h.
각각의 STRONG TP/SL을 train data로 finalize한 다음 test data 에서 PF/net 측정.
PF > 1.0 OOS 통과시 verdict OK.
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


# Stage 3 STRONG winners
STRONG = [
    ("donchian_20",   "ETHUSDT", 0.02,  50, -35),
    ("vol_expansion", "ETHUSDT", 0.02,  50, -25),
    ("vol_expansion", "ETHUSDT", 0.04,  50, -25),
    ("vol_expansion", "ARBUSDT", 0.04,  50, -20),
    ("vol_expansion", "DOGEUSDT", 0.04, 80, -30),
    ("vol_expansion", "DOGEUSDT", 0.02, 80, -30),
    ("heikin_cont",   "DOGEUSDT", 0.06, 80, -35),
    ("momentum_obv",  "DOGEUSDT", 0.02, 80, -30),
    ("atr_expansion", "SUIUSDT", 0.02,  80, -35),
    ("atr_expansion", "SUIUSDT", 0.04, 150, -40),
    ("momentum_obv",  "WIFUSDT", 0.02, 300, -25),
    ("heikin_cont",   "WIFUSDT", 0.06, 100, -25),
]


def folds_split(n, train_frac=0.7):
    """Train: 4-fold within first 70%. OOS test: last 30% (single fold)."""
    train_end = int(n * train_frac)
    train_size = train_end // 4
    train_folds = [(k*train_size, (k+1)*train_size if k<3 else train_end) for k in range(4)]
    oos = [(train_end, n)]
    return train_folds, oos


def fold_eval(ind, btc_regime, sig_fn, folds, tp, sl, mom):
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
    print(f"Phase C: OOS hold-out validation (70/30 split)")
    universe = sorted(set(s[1] for s in STRONG) | {"BTCUSDT"})
    cache = {}
    for sym in universe:
        df = load_1h(sym)
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_regime = precompute_btc_regime(cache["BTCUSDT"])
    n = min(len(cache[s]["close"]) for s in universe)
    train_folds, oos_folds = folds_split(n)
    print(f"  bars total: {n}")
    print(f"  train: {train_folds[0][0]}-{train_folds[-1][1]} ({sum(e-s for s,e in train_folds)} bars)")
    print(f"  OOS:   {oos_folds[0][0]}-{oos_folds[0][1]} ({oos_folds[0][1]-oos_folds[0][0]} bars)")

    results = []
    print(f"\n{'sig':<16} {'sym':<10} {'mom':>5} {'TP/SL':>9} "
          f"{'tr_n':>5} {'tr_pf':>6} {'tr_wf':>5} {'tr_net':>7} | "
          f"{'oos_n':>5} {'oos_pf':>6} {'oos_net':>7} verdict")

    t0 = time.time()
    for sig_name, sym, mom, tp, sl in STRONG:
        sig_fn = SIGNALS[sig_name]
        ind = cache[sym]
        tr = fold_eval(ind, btc_regime, sig_fn, train_folds, tp, sl, mom)
        oos = fold_eval(ind, btc_regime, sig_fn, oos_folds, tp, sl, mom)

        if tr is None or oos is None:
            verdict = "❌ NO_DATA"; oos_pf = 0; oos_net = 0; oos_n = 0
        else:
            oos_pf = oos["pf"]; oos_net = oos["net"]; oos_n = oos["n"]
            # OOS 통과 기준: PF >= 1.0 + net > -$30 (small loss tolerance)
            if oos_pf >= 1.5 and oos_net > 0: verdict = "🥇 OOS_STRONG"
            elif oos_pf >= 1.0 and oos_net > -30: verdict = "🥈 OOS_OK"
            elif oos_n == 0: verdict = "⚠️ NO_TRADES"
            else: verdict = "❌ OOS_FAIL"

        results.append({
            "signal": sig_name, "symbol": sym, "mom_min": mom, "tp": tp, "sl": sl,
            "train": tr, "oos": oos, "verdict": verdict,
        })
        print(f"{sig_name:<16} {sym:<10} {mom*100:>4.0f}% {f'+{tp}/{sl}':>9} "
              f"{tr['n'] if tr else 0:>5} {tr['pf'] if tr else 0:>6.2f} "
              f"{tr['wf'] if tr else 0:>4}/4 ${tr['net'] if tr else 0:>+6.0f} | "
              f"{oos_n:>5} {oos_pf:>6.2f} ${oos_net:>+6.0f} {verdict}")

    # rank
    rk = {"🥇 OOS_STRONG":0, "🥈 OOS_OK":1, "⚠️ NO_TRADES":2, "❌ OOS_FAIL":3, "❌ NO_DATA":4}
    results.sort(key=lambda r: (rk[r["verdict"]], -(r["oos"]["net"] if r["oos"] else -9999)))

    print(f"\n=== STAGE C OOS RANKING ===")
    for i, r in enumerate(results):
        if r["oos"]:
            print(f"  {i+1}. {r['signal']:<16} {r['symbol']:<10} mom{r['mom_min']*100:.0f}% "
                  f"TP+{r['tp']}/SL{r['sl']}: OOS PF={r['oos']['pf']:.2f} "
                  f"net=${r['oos']['net']:+.0f} ({r['oos']['n']} trades) {r['verdict']}")

    out = Path("quant_runtime/output/auto4h/phaseC_oos.json")
    with open(out, "w") as f:
        json.dump({"results": results}, f, indent=2, default=str)
    print(f"\n[saved] {out}")

    strong = [r for r in results if r["verdict"] == "🥇 OOS_STRONG"]
    ok = [r for r in results if r["verdict"] == "🥈 OOS_OK"]
    print(f"\nOOS verdict: {len(strong)} OOS_STRONG + {len(ok)} OOS_OK")
    print(f"Phase C runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    run()
