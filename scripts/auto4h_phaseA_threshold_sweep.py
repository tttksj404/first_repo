#!/usr/bin/env python3
"""Phase A: Signal threshold parameter sweep on 14 STRONG winners + base 12 signals.

Stage 1-3에서 12 신호를 고정 임계값으로 테스트했으나 임계값 sweep을 못함.
이 phase는 각 신호의 핵심 임계값을 5단계 grid → 신호당 ~125 조합 → 12신호 = ~1500 조합.

각 후보의 best TP/SL은 stage2/3에서 가져온 값 그대로 사용.
"""
from __future__ import annotations
import sys, json, time
from pathlib import Path
import numpy as np
from itertools import product

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv
from auto4h_stage1_matrix import precompute_btc_regime, simulate as base_simulate

LEVERAGE = 10
MARGIN = 50.0
COST_RT = 0.0012
FUNDING_8H = 0.0001
SLIPPAGE_BPS = 8


# === parameterized signals ===
def make_vol_expansion(bb_rank=0.7, mom_min=0.03, vol_r_min=1.5):
    def fn(ind, i):
        if i < 30: return False
        return (ind["bb_width_rank"][i] >= bb_rank and ind["mom24"][i] > mom_min
                and ind["close"][i] > ind["bb_upper"][i] and ind["vol_r"][i] >= vol_r_min)
    return fn

def make_momentum_obv(mom_min=0.05, adx_min=22, vol_r_min=1.3):
    def fn(ind, i):
        if i < 25: return False
        return (ind["mom24"][i] > mom_min and ind["ema20"][i] > ind["ema50"][i]
                and ind["adx"][i] > adx_min and ind["vol_r"][i] >= vol_r_min
                and ind["obv_slope"][i] > 0)
    return fn

def make_donchian(window=20, vol_r_min=1.5, mom_min=0.02):
    def fn(ind, i):
        if i < window+1: return False
        h = ind["high"][i-window:i]
        return (ind["close"][i] > np.max(h) and ind["vol_r"][i] >= vol_r_min
                and ind["mom24"][i] > mom_min)
    return fn

def make_atr_expansion(mult=1.2, vol_r_min=1.3):
    def fn(ind, i):
        if i < 50: return False
        bb_w = ind["bb_width"]
        s = max(0, i-49); ma = np.mean(bb_w[s:i+1])
        return (bb_w[i] > ma * mult and ind["close"][i] > ind["ema50"][i]
                and ind["close"][i] > ind["close"][i-1] and ind["vol_r"][i] >= vol_r_min)
    return fn

def make_heikin_cont(n_bars=3, vol_r_min=1.4):
    def fn(ind, i):
        if i < n_bars: return False
        bullish = all(ind["close"][k] > ind["close"][k-1] for k in range(i-n_bars+1, i+1))
        return bullish and ind["close"][i] > ind["ema20"][i] and ind["vol_r"][i] >= vol_r_min
    return fn

def make_fractal(window=5, vol_r_min=1.4):
    def fn(ind, i):
        if i < window+1: return False
        h = max(ind["high"][i-window:i])
        return (ind["close"][i] > h and ind["vol_r"][i] > vol_r_min
                and ind["ema20"][i] > ind["ema50"][i])
    return fn

def make_adx_trend(adx_min=30, mom_min=0.03, vol_r_min=1.2):
    def fn(ind, i):
        if i < 50: return False
        return (ind["adx"][i] > adx_min and ind["ema20"][i] > ind["ema50"][i]
                and ind["close"][i] > ind["ema20"][i] and ind["vol_r"][i] >= vol_r_min
                and ind["mom24"][i] > mom_min)
    return fn


# parameter grids
SWEEPS = {
    "vol_expansion": {
        "params": list(product([0.6, 0.7, 0.8], [0.02, 0.03, 0.04, 0.05], [1.3, 1.5, 1.8, 2.0])),
        "make": lambda p: make_vol_expansion(*p),
        "names": ("bb_rank", "mom_min", "vol_r"),
    },
    "momentum_obv": {
        "params": list(product([0.03, 0.05, 0.07, 0.10], [18, 22, 25, 30], [1.0, 1.3, 1.5])),
        "make": lambda p: make_momentum_obv(*p),
        "names": ("mom_min", "adx_min", "vol_r"),
    },
    "donchian": {
        "params": list(product([10, 15, 20, 30, 40], [1.2, 1.5, 1.8], [0.0, 0.02, 0.04])),
        "make": lambda p: make_donchian(*p),
        "names": ("window", "vol_r", "mom_min"),
    },
    "atr_expansion": {
        "params": list(product([1.0, 1.2, 1.5, 1.8], [1.0, 1.3, 1.5, 1.8])),
        "make": lambda p: make_atr_expansion(*p),
        "names": ("mult", "vol_r"),
    },
    "heikin_cont": {
        "params": list(product([2, 3, 4, 5], [1.0, 1.2, 1.4, 1.6])),
        "make": lambda p: make_heikin_cont(*p),
        "names": ("n_bars", "vol_r"),
    },
    "fractal": {
        "params": list(product([3, 5, 7, 10], [1.0, 1.2, 1.4, 1.6])),
        "make": lambda p: make_fractal(*p),
        "names": ("window", "vol_r"),
    },
    "adx_trend": {
        "params": list(product([20, 25, 30, 35], [0.0, 0.02, 0.04], [1.0, 1.2, 1.5])),
        "make": lambda p: make_adx_trend(*p),
        "names": ("adx_min", "mom_min", "vol_r"),
    },
}

UNIVERSE = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT", "WIFUSDT",
            "SUIUSDT", "ARBUSDT", "OPUSDT", "AVAXUSDT", "NEARUSDT", "APTUSDT",
            "MATICUSDT", "LINKUSDT", "UNIUSDT", "PEPEUSDT"]

# 14 STRONG TP/SL targets to test against
STRONG_TARGETS = [
    ("ETHUSDT", 50, -35, 0.02),
    ("ETHUSDT", 50, -25, 0.02),
    ("ARBUSDT", 50, -20, 0.04),
    ("DOGEUSDT", 80, -30, 0.04),
    ("DOGEUSDT", 80, -30, 0.02),
    ("DOGEUSDT", 80, -35, 0.06),
    ("SUIUSDT", 80, -35, 0.02),
    ("SUIUSDT", 150, -40, 0.04),
    ("WIFUSDT", 100, -25, 0.06),
    ("WIFUSDT", 300, -25, 0.02),
]


def quick_eval(ind, btc_regime, sig_fn, folds, tp, sl, mom):
    all_pnls = []; wf_pass = 0
    for s, e in folds:
        ts = base_simulate(ind, btc_regime, sig_fn, s, e, tp, sl, mom)
        fp = [t["pnl"] for t in ts]
        if fp:
            a = np.array(fp); w = a[a>0].sum(); l = abs(a[a<0].sum())
            pf_f = w/l if l>0 else 99
            if pf_f > 1.0 and len(a) >= 3: wf_pass += 1
        all_pnls.extend(fp)
    if not all_pnls: return None
    a = np.array(all_pnls)
    pf = a[a>0].sum() / abs(a[a<0].sum()) if (a<0).any() else 99
    return {"net": float(a.sum()), "pf": float(pf), "n": len(a), "wf": wf_pass}


def run():
    print(f"Phase A: signal threshold sweep")
    print(f"  signals: {list(SWEEPS.keys())}")
    total_param_combos = sum(len(v["params"]) for v in SWEEPS.values())
    print(f"  total signal-param combos: {total_param_combos}")
    print(f"  STRONG targets: {len(STRONG_TARGETS)}")

    cache = {}
    for sym in UNIVERSE:
        df = load_1h(sym)
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_regime = precompute_btc_regime(cache["BTCUSDT"])
    n_min = min(len(cache[s]["close"]) for s in UNIVERSE)
    fold_size = n_min // 4
    folds = [(k*fold_size, (k+1)*fold_size if k<3 else n_min) for k in range(4)]

    results = []  # list of {sig_name, params, sym, tp, sl, mom, ...}
    t0 = time.time()
    n_evaluated = 0
    n_promising = 0
    for sig_name, sweep in SWEEPS.items():
        for p in sweep["params"]:
            sig_fn = sweep["make"](p)
            for sym, tp, sl, mom in STRONG_TARGETS:
                ind = cache[sym]
                r = quick_eval(ind, btc_regime, sig_fn, folds, tp, sl, mom)
                n_evaluated += 1
                if r is None: continue
                if r["wf"] >= 3 and r["pf"] >= 1.5 and r["net"] > 50:
                    n_promising += 1
                    results.append({
                        "signal": sig_name, "params": dict(zip(sweep["names"], p)),
                        "symbol": sym, "tp": tp, "sl": sl, "mom_min": mom,
                        **r,
                    })
        elapsed = time.time() - t0
        print(f"  {sig_name:18s} done. {n_evaluated} evals, {n_promising} promising, "
              f"elapsed={elapsed:.1f}s")

    # rank
    results.sort(key=lambda r: (-r["wf"], -r["pf"], -r["net"]))
    print(f"\n=== TOP 30 results ===")
    print(f"{'sig':<16} {'params':<45} {'sym':<10} {'tp/sl':>9} {'mom':>5} "
          f"{'n':>4} {'pf':>5} {'wf':>3} {'net':>7}")
    for r in results[:30]:
        params_str = ", ".join(f"{k}={v}" for k, v in r["params"].items())
        print(f"{r['signal']:<16} {params_str:<45} {r['symbol']:<10} "
              f"{f'+{r['tp']}/{r['sl']}':>9} {r['mom_min']*100:>4.0f}% "
              f"{r['n']:>4} {r['pf']:>5.2f} {r['wf']:>3}/4 {r['net']:>+7.0f}")

    out = Path("quant_runtime/output/auto4h/phaseA_threshold.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump({"results": results, "n_evaluated": n_evaluated}, f, indent=2, default=str)
    print(f"\n[saved] {out}")
    print(f"Phase A runtime: {time.time()-t0:.1f}s, {len(results)} promising / {n_evaluated} total")


if __name__ == "__main__":
    run()
