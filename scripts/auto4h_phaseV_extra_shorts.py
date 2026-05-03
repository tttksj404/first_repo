#!/usr/bin/env python3
"""Phase V: Extra 7 short signals (mirror remaining longs).

Phase Q 는 5개 short 만 발굴 (vol/momobv/donchian/heikin/atr).
나머지 7 long signals (squeeze/ema_cross/pump/rsi/fractal/adx/trend_pullback) inverse 도 시도.
검증된 LINK/ETH/NEAR/SUI 외에 새 short 후보 발굴 목적.
"""
from __future__ import annotations
import sys, json, time
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv
from auto4h_phaseQ_short_side import precompute_bear_regime, simulate_short

LEVERAGE = 10
MARGIN = 50.0


# === 7 NEW SHORT SIGNALS ===
def short_squeeze_release(ind, i):
    """BB squeeze 5 bar 후 close < BB lower (downward break)."""
    if i < 22 or i < 5: return False
    if not all(ind["bb_width_rank"][k] < 0.30 for k in range(i-5, i)): return False
    return ind["close"][i] < ind["bb_lower"][i-1] and ind["vol_r"][i] > 1.3


def short_ema_cross_dn(ind, i):
    """EMA20 cross below EMA50 + volume."""
    if i < 51: return False
    cross = (ind["ema20"][i] < ind["ema50"][i]) and (ind["ema20"][i-1] >= ind["ema50"][i-1])
    return cross and ind["vol_r"][i] >= 1.5 and ind["mom24"][i] < 0.0


def short_dump_detect(ind, i):
    """1h 급락 + 거래량 폭발."""
    if i < 2: return False
    pct_1h = ind["close"][i] / ind["close"][i-1] - 1
    return pct_1h < -0.04 and ind["vol_r"][i] > 3.0


def short_rsi_breakdown(ind, i):
    """RSI < 40 + close < BB mid + ADX strong + downward."""
    if i < 14: return False
    gains = 0; losses = 0
    for k in range(i-13, i+1):
        d = ind["close"][k] - ind["close"][k-1] if k > 0 else 0
        if d > 0: gains += d
        else: losses += -d
    rsi = 100 if losses == 0 else 100 - (100 / (1 + gains/losses))
    bb_mid = (ind["bb_upper"][i] + ind["bb_lower"][i]) / 2
    return rsi < 40 and ind["close"][i] < bb_mid and ind["adx"][i] > 25 and ind["vol_r"][i] > 1.2


def short_fractal_break_dn(ind, i):
    """5-bar fractal low break."""
    if i < 6: return False
    fractal_low = min(ind["low"][i-5:i])
    return (ind["close"][i] < fractal_low and ind["vol_r"][i] > 1.4
            and ind["ema20"][i] < ind["ema50"][i])


def short_adx_trend_dn(ind, i):
    """ADX > 30 + downward EMA align + close < ema20 + mom < -3%."""
    if i < 50: return False
    return (ind["adx"][i] > 30 and ind["ema20"][i] < ind["ema50"][i]
            and ind["close"][i] < ind["ema20"][i] and ind["vol_r"][i] >= 1.2
            and ind["mom24"][i] < -0.03)


def short_trend_pullback_dn(ind, i):
    """Downtrend pullback to EMA20 from below — fade rallies in bear."""
    if i < 51: return False
    if ind["ema20"][i] >= ind["ema50"][i]: return False  # not in downtrend
    touched = any(ind["high"][k] >= ind["ema20"][k] * 0.995 for k in range(i-3, i))
    rejecting = ind["close"][i] < ind["ema20"][i] and ind["close"][i] < ind["close"][i-1]
    return touched and rejecting and ind["vol_r"][i] > 1.3 and ind["mom24"][i] < 0.0


EXTRA_SHORT_SIGNALS = {
    "short_squeeze_release":    short_squeeze_release,
    "short_ema_cross_dn":       short_ema_cross_dn,
    "short_dump_detect":        short_dump_detect,
    "short_rsi_breakdown":      short_rsi_breakdown,
    "short_fractal_break_dn":   short_fractal_break_dn,
    "short_adx_trend_dn":       short_adx_trend_dn,
    "short_trend_pullback_dn":  short_trend_pullback_dn,
}


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


COINS = ["ADAUSDT", "APTUSDT", "ARBUSDT", "AVAXUSDT", "BNBUSDT", "BTCUSDT",
         "DOGEUSDT", "DOTUSDT", "ETHUSDT", "LINKUSDT", "LTCUSDT", "NEARUSDT",
         "OPUSDT", "PEPEUSDT", "SOLUSDT", "SUIUSDT", "UNIUSDT", "WIFUSDT", "XRPUSDT"]
MOM_LIST = [-0.02, -0.04, -0.06, -0.08]
TP_SL_LIST = [(50, -25), (80, -30), (100, -25), (150, -35), (200, -40)]


def run():
    print("Phase V: extra 7 short signals × 19 coins × 4 mom × 5 TP/SL = 2660 evals")
    cache = {}
    for sym in COINS:
        df = load_1h(sym)
        if df is None: continue
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    if "BTCUSDT" not in cache:
        print("BTC missing"); return
    btc_bear = precompute_bear_regime(cache["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache.values())
    fold = n_min // 4
    folds = [(k*fold, (k+1)*fold if k<3 else n_min) for k in range(4)]

    print(f"  BTC bear regime: {btc_bear[:n_min].mean()*100:.1f}% of bars")

    results = []
    n_eval = 0; n_robust = 0
    t0 = time.time()
    for sig_name, sig_fn in EXTRA_SHORT_SIGNALS.items():
        for sym in COINS:
            if sym not in cache: continue
            ind = cache[sym]
            for mom in MOM_LIST:
                for tp, sl in TP_SL_LIST:
                    n_eval += 1
                    r = quick_eval(ind, btc_bear, sig_fn, folds, tp, sl, mom)
                    if r is None or r["n"] < 8: continue
                    if r["pf"] < 1.5 or r["wf"] < 3: continue
                    if r["net"] < 30: continue
                    n_robust += 1
                    results.append({
                        "signal": sig_name, "symbol": sym,
                        "mom_max": mom, "tp": tp, "sl": sl, **r,
                    })
    results.sort(key=lambda r: -r["net"])
    print(f"\n=== TOP 20 EXTRA SHORT WINNERS ===")
    for r in results[:20]:
        print(f"  {r['signal']:<24} {r['symbol']:<10} mom{r['mom_max']*100:>+3.0f}% "
              f"TP+{r['tp']}/SL{r['sl']}: PF={r['pf']:.2f} WF={r['wf']}/4 "
              f"n={r['n']} net=${r['net']:+.0f}")
    out = Path("quant_runtime/output/auto4h/phaseV_extra_shorts.json")
    with open(out, "w") as f:
        json.dump({"results": results, "n_eval": n_eval, "n_robust": n_robust},
                  f, indent=2, default=str)
    print(f"\n[saved] {out}")
    print(f"Phase V runtime: {time.time()-t0:.1f}s, {n_robust}/{n_eval} robust")


if __name__ == "__main__":
    run()
