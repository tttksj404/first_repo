#!/usr/bin/env python3
"""Phase H: Volatility regime sub-buckets.

각 STRONG 시그널을 volatility regime별로 분리:
  - low vol (atr_rank < 0.33)
  - mid vol (0.33 ≤ atr_rank < 0.67)
  - high vol (atr_rank ≥ 0.67)
  - low+high vol (mid 제외 = 변동성 극단 only)

가설: vol_expansion 시그널은 high vol 에서만 작동, momentum 은 mid 에서 좋을 수도.
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
COST_RT = 0.0012
FUNDING_8H = 0.0001
SLIPPAGE_BPS = 8
LIQ_ROE = -95.0
SIGNAL_OFF_MIN_ROE = 0.0
COOLDOWN_AFTER_EXIT_H = 12
COOLDOWN_AFTER_LOSS_H = 24


def compute_atr_rank(ind):
    n = len(ind["close"])
    high = ind["high"]; low = ind["low"]; close = ind["close"]
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
    atr24 = np.zeros(n)
    for i in range(n):
        s = max(0, i-23); atr24[i] = np.mean(tr[s:i+1])
    atr_rank = np.zeros(n)
    for i in range(n):
        s = max(0, i-199); seg = atr24[s:i+1]
        atr_rank[i] = (seg <= atr24[i]).mean() if len(seg) else 0.5
    return atr_rank


def simulate_volbucket(ind, btc_regime, sig_fn, start, end, tp, sl, mom_min,
                       atr_rank, vol_lo, vol_hi):
    trades = []
    in_pos = False; entry_px = 0.0; entry_idx = 0
    last_exit = -1; last_loss = -1
    slip = SLIPPAGE_BPS / 10000.0
    for i in range(max(start, 50), end):
        if not in_pos:
            if last_exit >= 0 and (i - last_exit) < COOLDOWN_AFTER_EXIT_H: continue
            if last_loss >= 0 and (i - last_loss) < COOLDOWN_AFTER_LOSS_H: continue
            if i < len(btc_regime) and not btc_regime[i]: continue
            if ind["mom24"][i] < mom_min: continue
            if not sig_fn(ind, i): continue
            ar = atr_rank[i] if i < len(atr_rank) else 0.5
            if not (vol_lo <= ar < vol_hi): continue
            entry_px = ind["close"][i] * (1 + slip)
            entry_idx = i; in_pos = True
        else:
            hi = ind["high"][i]; lo = ind["low"][i]; cl = ind["close"][i]
            roe_lo = (lo / entry_px - 1) * LEVERAGE * 100
            roe_hi = (hi / entry_px - 1) * LEVERAGE * 100
            roe_cl = (cl / entry_px - 1) * LEVERAGE * 100
            exit_roe = None
            if roe_lo <= LIQ_ROE: exit_roe = -100.0
            elif roe_lo <= sl:
                sl_px = entry_px * (1 + sl/100/LEVERAGE)
                exit_roe = (sl_px*(1-slip)/entry_px - 1)*LEVERAGE*100
            elif roe_hi >= tp:
                tp_px = entry_px * (1 + tp/100/LEVERAGE)
                exit_roe = (tp_px*(1-slip)/entry_px - 1)*LEVERAGE*100
            elif (not sig_fn(ind, i)) and roe_cl > SIGNAL_OFF_MIN_ROE:
                exit_roe = (cl*(1-slip)/entry_px - 1)*LEVERAGE*100
            if exit_roe is not None:
                hold_h = i - entry_idx
                notional = MARGIN * LEVERAGE
                fee = notional * COST_RT
                funding = notional * FUNDING_8H * (hold_h / 8)
                pnl = -MARGIN-fee if exit_roe <= -100 else MARGIN*(exit_roe/100) - fee - funding
                trades.append({"pnl": pnl})
                in_pos = False; last_exit = i
                if pnl < 0: last_loss = i
    return trades


def quick_eval(ind, btc, fn, folds, tp, sl, mom, ar, lo, hi):
    all_pnls = []; wf = 0
    for s, e in folds:
        ts = simulate_volbucket(ind, btc, fn, s, e, tp, sl, mom, ar, lo, hi)
        fp = [t["pnl"] for t in ts]
        if fp:
            a = np.array(fp); w = a[a>0].sum(); l = abs(a[a<0].sum())
            pf_f = w/l if l>0 else 99
            if pf_f > 1.0 and len(a) >= 3: wf += 1
        all_pnls.extend(fp)
    if not all_pnls: return None
    a = np.array(all_pnls); pf = a[a>0].sum() / max(abs(a[a<0].sum()), 1e-9)
    return {"net": float(a.sum()), "pf": float(pf), "n": len(a), "wf": int(wf)}


STRONG = [
    ("donchian_20",   "ETHUSDT",  0.02,  50, -35),
    ("vol_expansion", "ETHUSDT",  0.02,  50, -25),
    ("vol_expansion", "ARBUSDT",  0.04,  50, -20),
    ("vol_expansion", "DOGEUSDT", 0.04,  80, -30),
    ("heikin_cont",   "DOGEUSDT", 0.06,  80, -35),
    ("atr_expansion", "SUIUSDT",  0.02,  80, -35),
    ("atr_expansion", "SUIUSDT",  0.04, 150, -40),
    ("heikin_cont",   "WIFUSDT",  0.06, 100, -25),
    ("momentum_obv",  "WIFUSDT",  0.02, 300, -25),
]
UNIVERSE = sorted(set(s[1] for s in STRONG) | {"BTCUSDT"})

VOL_BUCKETS = {
    "all": (0.0, 1.01),
    "low": (0.0, 0.33),
    "mid": (0.33, 0.67),
    "high": (0.67, 1.01),
    "low_high_extremes": None,  # special
    "above_50pct": (0.5, 1.01),
    "above_70pct": (0.7, 1.01),
}


def run():
    print("Phase H: volatility regime sub-buckets")
    cache = {}; ar_cache = {}
    for sym in UNIVERSE:
        df = load_1h(sym)
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
        ar_cache[sym] = compute_atr_rank(ind)
    btc_regime = precompute_btc_regime(cache["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache.values())
    fold = n_min // 4
    folds = [(k*fold, (k+1)*fold if k<3 else n_min) for k in range(4)]

    results = []
    print(f"\n{'sig':<16} {'sym':<10} {'bucket':<22} {'n':>4} {'pf':>5} {'wf':>4} {'net':>7}")
    t0 = time.time()
    for sig_name, sym, mom, tp, sl in STRONG:
        sig_fn = SIGNALS[sig_name]; ind = cache[sym]; ar = ar_cache[sym]
        bl = quick_eval(ind, btc_regime, sig_fn, folds, tp, sl, mom, ar, 0.0, 1.01)
        if bl is None: continue
        for bname, rg in VOL_BUCKETS.items():
            if bname == "all": continue
            if bname == "low_high_extremes":
                # union: low (<0.33) OR high (>=0.67)
                # custom: simulate with "in [0,0.33) OR [0.67,1.01)"
                # implement as: pass (0,1.01) but do entry filter via mid mask.
                # easiest: re-use simulate twice and merge -- simpler: skip for now
                continue
            r = quick_eval(ind, btc_regime, sig_fn, folds, tp, sl, mom, ar, rg[0], rg[1])
            if r is None or r["n"] < 5: continue
            improved = r["net"] > bl["net"] * 1.1 and r["pf"] >= 1.5 and r["wf"] >= 3
            tag = "🥇" if improved else "  "
            results.append({
                "signal": sig_name, "symbol": sym, "mom_min": mom, "tp": tp, "sl": sl,
                "bucket": bname, "vol_lo": rg[0], "vol_hi": rg[1], **r,
                "baseline_net": bl["net"], "baseline_pf": bl["pf"],
                "improved": improved,
            })
            if improved:
                print(f"{tag} {sig_name:<16} {sym:<10} {bname:<22} "
                      f"{r['n']:>4} {r['pf']:>5.2f} {r['wf']:>3}/4 ${r['net']:>+6.0f} "
                      f"(was ${bl['net']:+.0f} PF={bl['pf']:.2f})")

    out = Path("quant_runtime/output/auto4h/phaseH_volregime.json")
    with open(out, "w") as f:
        json.dump({"results": results}, f, indent=2, default=str)
    improvements = [r for r in results if r["improved"]]
    print(f"\n[saved] {out}")
    print(f"Phase H runtime: {time.time()-t0:.1f}s, {len(improvements)} improvements")


if __name__ == "__main__":
    run()
