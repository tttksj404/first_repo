#!/usr/bin/env python3
"""Phase W: Multi-timeframe confluence test.

기존 1h entry 에 4h trend gate 추가 시 OOS PF 개선되는지 측정.
4h trend = 4h EMA20 > EMA50 (long) / 4h EMA20 < EMA50 (short).
원리: 1h false breakout 을 4h 추세로 필터링.

테스트 대상 = production 7 long + 7 short = 14 strategies.
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
from auto4h_stage1_matrix import simulate as sim_long, precompute_btc_regime
from auto4h_phaseQ_short_side import (
    SHORT_SIGNALS, simulate_short, precompute_bear_regime,
)
from auto4h_phaseV_extra_shorts import EXTRA_SHORT_SIGNALS

# combined short signal map
ALL_SHORT_SIGNALS = {**SHORT_SIGNALS, **EXTRA_SHORT_SIGNALS}


def ema_arr(arr, period):
    out = np.empty_like(arr, dtype=float); out[0] = arr[0]
    alpha = 2.0/(period+1.0)
    for i in range(1, len(arr)):
        out[i] = alpha*arr[i] + (1-alpha)*out[i-1]
    return out


def compute_4h_trend(ind):
    """Resample 1h close to 4h, compute ema20/ema50, broadcast back to 1h index."""
    n = len(ind["close"])
    # group every 4 1h bars
    n4 = n // 4
    close4 = np.array([ind["close"][k*4 + 3] for k in range(n4)])  # last close in each 4h
    if len(close4) < 51:
        return np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    e20 = ema_arr(close4, 20)
    e50 = ema_arr(close4, 50)
    bull4 = e20 > e50
    bear4 = e20 < e50
    bull_1h = np.zeros(n, dtype=bool)
    bear_1h = np.zeros(n, dtype=bool)
    for k in range(n4):
        s = k*4; e = s+4
        if e > n: e = n
        bull_1h[s:e] = bull4[k]
        bear_1h[s:e] = bear4[k]
    return bull_1h, bear_1h


def folds_split(n, train_frac=0.7):
    train_end = int(n * train_frac)
    train_size = train_end // 4
    train_folds = [(k*train_size, (k+1)*train_size if k<3 else train_end) for k in range(4)]
    return train_folds, [(train_end, n)]


def quick_eval_long(ind, btc, fn, folds, tp, sl, mom):
    all_pnls = []; wf = 0
    for s, e in folds:
        ts = sim_long(ind, btc, fn, s, e, tp, sl, mom)
        fp = [t["pnl"] for t in ts]
        if fp:
            a = np.array(fp); w = a[a>0].sum(); l = abs(a[a<0].sum())
            pf_f = w/l if l>0 else 99
            if pf_f > 1.0 and len(a) >= 3: wf += 1
        all_pnls.extend(fp)
    if not all_pnls: return None
    a = np.array(all_pnls); pf = a[a>0].sum() / max(abs(a[a<0].sum()), 1e-9)
    return {"net": float(a.sum()), "pf": float(pf), "n": len(a), "wf": int(wf)}


def quick_eval_short(ind, btc_bear, fn, folds, tp, sl, mom):
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


def with_4h_filter(orig_fn, bull_1h):
    """Wrap signal fn — only fire if 4h bull (long) or bear (short)."""
    def f(ind, i):
        if i >= len(bull_1h): return False
        if not bull_1h[i]: return False
        return orig_fn(ind, i)
    return f


# Production 7 long + 7 short
LONG_SET = [
    ("eth_donchian", "donchian_20", "ETHUSDT", 0.02, 50, -35),
    ("sui_atrexp_2", "atr_expansion", "SUIUSDT", 0.02, 80, -35),
    ("doge_volexp_4", "vol_expansion", "DOGEUSDT", 0.04, 80, -30),
    ("wif_heikin", "heikin_cont", "WIFUSDT", 0.06, 100, -25),
    ("ada_heikin_2", "heikin_cont", "ADAUSDT", 0.02, 300, -50),
    ("pepe_atrexp", "atr_expansion", "PEPEUSDT", 0.08, 300, -50),
    ("op_atrexp", "atr_expansion", "OPUSDT", 0.06, 300, -50),
]
SHORT_SET = [
    ("link_atrexp_S", "short_atr_expansion", "LINKUSDT", -0.04, 80, -30),
    ("eth_heikin_S", "short_heikin_cont", "ETHUSDT", -0.04, 80, -30),
    ("near_atrexp_S", "short_atr_expansion", "NEARUSDT", -0.02, 200, -40),
    ("sui_momobv_S", "short_momentum_obv", "SUIUSDT", -0.06, 200, -40),
    ("arb_rsi_S", "short_rsi_breakdown", "ARBUSDT", -0.02, 200, -40),
    ("dot_adx_S", "short_adx_trend_dn", "DOTUSDT", -0.02, 150, -35),
    ("link_adx_S", "short_adx_trend_dn", "LINKUSDT", -0.06, 200, -40),
]


def run():
    print("Phase W: 4h trend confluence test")
    universe = sorted(set([s[2] for s in LONG_SET] + [s[2] for s in SHORT_SET]) | {"BTCUSDT"})
    cache = {}
    trend_4h = {}
    for sym in universe:
        df = load_1h(sym)
        if df is None: continue
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
        bull, bear = compute_4h_trend(ind)
        trend_4h[sym] = (bull, bear)
    btc = precompute_btc_regime(cache["BTCUSDT"])
    btc_bear = precompute_bear_regime(cache["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache.values())
    train_folds, oos_folds = folds_split(n_min)

    print(f"\n{'sid':<16} {'side':<5} | base_oos_pf base_n | 4h_oos_pf 4h_n | uplift")
    out = []
    for sid, sig, sym, mom, tp, sl in LONG_SET:
        if sym not in cache: continue
        ind = cache[sym]; fn = SIGNALS[sig]
        bull4, _ = trend_4h[sym]
        base = quick_eval_long(ind, btc, fn, oos_folds, tp, sl, mom)
        wrapped = with_4h_filter(fn, bull4)
        filt = quick_eval_long(ind, btc, wrapped, oos_folds, tp, sl, mom)
        b_pf = base["pf"] if base else 0; b_n = base["n"] if base else 0; b_net = base["net"] if base else 0
        f_pf = filt["pf"] if filt else 0; f_n = filt["n"] if filt else 0; f_net = filt["net"] if filt else 0
        uplift = f_net - b_net
        out.append({"sid": sid, "side": "long", "base": base, "filt": filt, "uplift": uplift})
        print(f"{sid:<16} long  | {b_pf:>10.2f} {b_n:>5} | {f_pf:>9.2f} {f_n:>4} | ${uplift:+.0f}")
    for sid, sig, sym, mom, tp, sl in SHORT_SET:
        if sym not in cache: continue
        ind = cache[sym]; fn = ALL_SHORT_SIGNALS[sig]
        _, bear4 = trend_4h[sym]
        base = quick_eval_short(ind, btc_bear, fn, oos_folds, tp, sl, mom)
        wrapped = with_4h_filter(fn, bear4)
        filt = quick_eval_short(ind, btc_bear, wrapped, oos_folds, tp, sl, mom)
        b_pf = base["pf"] if base else 0; b_n = base["n"] if base else 0; b_net = base["net"] if base else 0
        f_pf = filt["pf"] if filt else 0; f_n = filt["n"] if filt else 0; f_net = filt["net"] if filt else 0
        uplift = f_net - b_net
        out.append({"sid": sid, "side": "short", "base": base, "filt": filt, "uplift": uplift})
        print(f"{sid:<16} short | {b_pf:>10.2f} {b_n:>5} | {f_pf:>9.2f} {f_n:>4} | ${uplift:+.0f}")

    out_path = Path("quant_runtime/output/auto4h/phaseW_multi_tf.json")
    with open(out_path, "w") as f:
        json.dump({"results": out}, f, indent=2, default=str)
    n_uplift = sum(1 for r in out if r["uplift"] > 0)
    n_hurt = sum(1 for r in out if r["uplift"] < -10)
    n_neutral = len(out) - n_uplift - n_hurt
    print(f"\n=== Summary: {n_uplift} 개선 / {n_hurt} 악화 / {n_neutral} 중립 ===")
    if n_uplift >= 8: verdict = "ADOPT 4h gate (≥8 strategies improved)"
    elif n_uplift >= 5: verdict = "PARTIAL — apply 4h gate to improved strategies only"
    else: verdict = "REJECT — 4h gate hurts more than helps"
    print(f"  Verdict: {verdict}")
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
