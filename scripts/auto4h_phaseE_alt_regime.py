#!/usr/bin/env python3
"""Phase E: Alternative regime gates.

기존: BTC EMA20>EMA50 + BTC ATR_rank>=0.4
대안:
  - ETH gate (ETH 가 더 알트 코인과 상관)
  - 부재 (no regime, 항상 ON)
  - vol_percentile (BTC ATR rank only, no EMA filter)
  - dual: BTC + ETH 둘 다 ON 일 때만
  - inverse: BTC RSI < 70 (oversold/neutral 만)
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

LEVERAGE = 10
MARGIN = 50.0
COST_RT = 0.0012
FUNDING_8H = 0.0001
SLIPPAGE_BPS = 8
LIQ_ROE = -95.0
SIGNAL_OFF_MIN_ROE = 0.0
COOLDOWN_AFTER_EXIT_H = 12
COOLDOWN_AFTER_LOSS_H = 24


def precompute_regime(ind, mode="btc_default", atr_min=0.4, rsi_max=70):
    n = len(ind["close"])
    high = ind["high"]; low = ind["low"]; close = ind["close"]
    ema20 = ind["ema20"]; ema50 = ind["ema50"]
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
    regime = np.zeros(n, dtype=bool)
    if mode == "always_on":
        regime[:] = True
    elif mode == "atr_only":
        regime = atr_rank >= atr_min
    elif mode == "ema_only":
        regime = ema20 > ema50
    elif mode == "btc_default":
        regime = (ema20 > ema50) & (atr_rank >= atr_min)
    elif mode == "rsi_neutral":
        # close-based RSI
        delta = np.diff(close, prepend=close[0])
        up = np.maximum(delta, 0); dn = np.maximum(-delta, 0)
        rsi = np.zeros(n); avg_u = avg_d = 0.0
        for i in range(1, n):
            if i <= 14:
                avg_u = np.mean(up[1:i+1]); avg_d = np.mean(dn[1:i+1])
            else:
                avg_u = (avg_u*13 + up[i])/14; avg_d = (avg_d*13 + dn[i])/14
            rsi[i] = 100 if avg_d == 0 else 100 - 100/(1 + avg_u/avg_d)
        regime = (ema20 > ema50) & (atr_rank >= atr_min) & (rsi < rsi_max)
    return regime


def simulate_with_regime(ind, regime, sig_fn, start, end, tp, sl, mom_min):
    trades = []
    in_pos = False; entry_px = 0.0; entry_idx = 0
    last_exit = -1; last_loss = -1
    slip = SLIPPAGE_BPS / 10000.0
    for i in range(max(start, 50), end):
        if not in_pos:
            if last_exit >= 0 and (i - last_exit) < COOLDOWN_AFTER_EXIT_H: continue
            if last_loss >= 0 and (i - last_loss) < COOLDOWN_AFTER_LOSS_H: continue
            if i >= len(regime) or not regime[i]: continue
            if ind["mom24"][i] < mom_min: continue
            if not sig_fn(ind, i): continue
            entry_px = ind["close"][i] * (1 + slip)
            entry_idx = i; in_pos = True
        else:
            hi = ind["high"][i]; lo = ind["low"][i]; cl = ind["close"][i]
            roe_lo = (lo / entry_px - 1) * LEVERAGE * 100
            roe_hi = (hi / entry_px - 1) * LEVERAGE * 100
            roe_cl = (cl / entry_px - 1) * LEVERAGE * 100
            exit_roe = None; reason = None
            if roe_lo <= LIQ_ROE: exit_roe = -100.0; reason = "LIQ"
            elif roe_lo <= sl:
                sl_px = entry_px * (1 + sl/100/LEVERAGE)
                exit_roe = (sl_px*(1-slip)/entry_px - 1)*LEVERAGE*100; reason = "SL"
            elif roe_hi >= tp:
                tp_px = entry_px * (1 + tp/100/LEVERAGE)
                exit_roe = (tp_px*(1-slip)/entry_px - 1)*LEVERAGE*100; reason = "TP"
            else:
                if (not sig_fn(ind, i)) and roe_cl > SIGNAL_OFF_MIN_ROE:
                    exit_roe = (cl*(1-slip)/entry_px - 1)*LEVERAGE*100; reason = "SIG_OFF"
            if exit_roe is not None:
                hold_h = i - entry_idx
                notional = MARGIN * LEVERAGE
                fee = notional * COST_RT
                funding = notional * FUNDING_8H * (hold_h / 8)
                pnl = -MARGIN-fee if exit_roe <= -100 else MARGIN*(exit_roe/100) - fee - funding
                trades.append({"pnl": pnl, "roe": exit_roe})
                in_pos = False; last_exit = i
                if pnl < 0: last_loss = i
    return trades


def quick_eval(ind, regime, sig_fn, folds, tp, sl, mom):
    all_pnls = []; wf = 0
    for s, e in folds:
        ts = simulate_with_regime(ind, regime, sig_fn, s, e, tp, sl, mom)
        fp = [t["pnl"] for t in ts]
        if fp:
            a = np.array(fp); w = a[a>0].sum(); l = abs(a[a<0].sum())
            pf_f = w/l if l>0 else 99
            if pf_f > 1.0 and len(a) >= 3: wf += 1
        all_pnls.extend(fp)
    if not all_pnls: return None
    a = np.array(all_pnls); pf = a[a>0].sum() / max(abs(a[a<0].sum()), 1e-9)
    return {"net": float(a.sum()), "pf": float(pf), "n": len(a), "wf": int(wf)}


# 14 STRONG
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
UNIVERSE = sorted(set(s[1] for s in STRONG) | {"BTCUSDT", "ETHUSDT"})

REGIMES = ["btc_default", "always_on", "atr_only", "ema_only", "rsi_neutral"]


def run():
    print(f"Phase E: alternative regime gates")
    cache = {}
    for sym in UNIVERSE:
        df = load_1h(sym)
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    n_min = min(len(c["close"]) for c in cache.values())
    fold = n_min // 4
    folds = [(k*fold, (k+1)*fold if k<3 else n_min) for k in range(4)]

    btc = cache["BTCUSDT"]; eth = cache["ETHUSDT"]
    regimes = {}
    for mode in REGIMES:
        regimes[f"btc_{mode}"] = precompute_regime(btc, mode)
        regimes[f"eth_{mode}"] = precompute_regime(eth, mode)
    # dual
    regimes["dual_btc_eth"] = (precompute_regime(btc, "btc_default")
                                & precompute_regime(eth, "btc_default"))

    results = []
    print(f"\n{'sig':<16} {'sym':<10} {'mom':>4} {'TP/SL':>9} {'regime':<22} "
          f"{'n':>4} {'pf':>5} {'wf':>4} {'net':>7}")
    t0 = time.time()
    for sig_name, sym, mom, tp, sl in STRONG:
        sig_fn = SIGNALS[sig_name]; ind = cache[sym]
        # baseline: btc_btc_default
        bl_reg = regimes["btc_btc_default"]
        baseline = quick_eval(ind, bl_reg, sig_fn, folds, tp, sl, mom)
        if baseline is None: continue
        for reg_name, reg in regimes.items():
            if len(reg) < n_min: continue
            r = quick_eval(ind, reg, sig_fn, folds, tp, sl, mom)
            if r is None: continue
            improved = r["net"] > baseline["net"] * 1.1 and r["pf"] >= 1.5 and r["wf"] >= 3
            tag = "🥇" if improved else "  "
            results.append({
                "signal": sig_name, "symbol": sym, "mom_min": mom, "tp": tp, "sl": sl,
                "regime": reg_name, **r,
                "baseline_net": baseline["net"], "baseline_pf": baseline["pf"],
                "improved": improved,
            })
            if improved:
                print(f"{tag} {sig_name:<16} {sym:<10} {mom*100:>3.0f}% "
                      f"{f'+{tp}/{sl}':>9} {reg_name:<22} "
                      f"{r['n']:>4} {r['pf']:>5.2f} {r['wf']:>3}/4 ${r['net']:>+6.0f} "
                      f"(was ${baseline['net']:+.0f} PF={baseline['pf']:.2f})")

    out = Path("quant_runtime/output/auto4h/phaseE_regime.json")
    with open(out, "w") as f:
        json.dump({"results": results}, f, indent=2, default=str)
    improvements = [r for r in results if r["improved"]]
    print(f"\n[saved] {out}")
    print(f"Phase E runtime: {time.time()-t0:.1f}s, {len(improvements)} improvements over baseline")


if __name__ == "__main__":
    run()
