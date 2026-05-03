#!/usr/bin/env python3
"""Phase F: Dynamic exit — trailing stop, ATR multiple, time-stop.

기존: 고정 SL/TP. 14 STRONG TP는 +50~+300% 인데 도달까지 며칠 걸려서 펀딩 드래그.
대안:
  - trailing stop: high after entry × 0.95 (move with profit)
  - ATR-multiple: SL = entry - ATR*2, TP = entry + ATR*5 (volatility-adaptive)
  - time-stop: 48h 후 강제 청산 (펀딩 드래그 방지)
  - hybrid: TP 고정 + trailing 따라가다 trail price 떨어지면 청산
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


def simulate_dynamic(ind, btc_regime, sig_fn, start, end, mom_min,
                     exit_mode="fixed", tp_roe=200, sl_roe=-30,
                     trail_pct=5.0, atr_mult_sl=2.0, atr_mult_tp=5.0,
                     time_stop_h=72):
    trades = []
    in_pos = False; entry_px = 0.0; entry_idx = 0; trail_high = 0.0
    last_exit = -1; last_loss = -1
    slip = SLIPPAGE_BPS / 10000.0
    # ATR(14)
    n = len(ind["close"])
    high = ind["high"]; low = ind["low"]; close = ind["close"]
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
    atr14 = np.zeros(n)
    for i in range(n):
        s = max(0, i-13); atr14[i] = np.mean(tr[s:i+1])

    for i in range(max(start, 50), end):
        if not in_pos:
            if last_exit >= 0 and (i - last_exit) < COOLDOWN_AFTER_EXIT_H: continue
            if last_loss >= 0 and (i - last_loss) < COOLDOWN_AFTER_LOSS_H: continue
            btc_r = bool(btc_regime[i]) if i < len(btc_regime) else False
            if not btc_r: continue
            if ind["mom24"][i] < mom_min: continue
            if not sig_fn(ind, i): continue
            entry_px = ind["close"][i] * (1 + slip)
            entry_idx = i; in_pos = True; trail_high = entry_px
            entry_atr = atr14[i]
        else:
            hi = high[i]; lo = low[i]; cl = close[i]
            trail_high = max(trail_high, hi)
            roe_lo = (lo / entry_px - 1) * LEVERAGE * 100
            roe_hi = (hi / entry_px - 1) * LEVERAGE * 100
            roe_cl = (cl / entry_px - 1) * LEVERAGE * 100
            exit_roe = None; reason = None
            if roe_lo <= LIQ_ROE: exit_roe = -100.0; reason = "LIQ"
            else:
                if exit_mode == "fixed":
                    if roe_lo <= sl_roe:
                        sl_px = entry_px * (1 + sl_roe/100/LEVERAGE)
                        exit_roe = (sl_px*(1-slip)/entry_px - 1)*LEVERAGE*100; reason = "SL"
                    elif roe_hi >= tp_roe:
                        tp_px = entry_px * (1 + tp_roe/100/LEVERAGE)
                        exit_roe = (tp_px*(1-slip)/entry_px - 1)*LEVERAGE*100; reason = "TP"
                elif exit_mode == "trailing":
                    # SL: trail_high * (1 - trail_pct/100)
                    sl_px = trail_high * (1 - trail_pct/100)
                    if lo <= sl_px:
                        exit_roe = (sl_px*(1-slip)/entry_px - 1)*LEVERAGE*100
                        reason = "TRAIL_SL"
                    elif roe_lo <= sl_roe:  # initial SL
                        sl_px = entry_px * (1 + sl_roe/100/LEVERAGE)
                        exit_roe = (sl_px*(1-slip)/entry_px - 1)*LEVERAGE*100; reason = "INIT_SL"
                elif exit_mode == "atr":
                    sl_px = entry_px - entry_atr * atr_mult_sl
                    tp_px = entry_px + entry_atr * atr_mult_tp
                    if lo <= sl_px:
                        exit_roe = (sl_px*(1-slip)/entry_px - 1)*LEVERAGE*100; reason = "ATR_SL"
                    elif hi >= tp_px:
                        exit_roe = (tp_px*(1-slip)/entry_px - 1)*LEVERAGE*100; reason = "ATR_TP"
                elif exit_mode == "hybrid_trail":
                    # initial SL fixed, after profit reaches +50% start trailing
                    sl_px = entry_px * (1 + sl_roe/100/LEVERAGE)
                    if roe_hi >= 50:
                        sl_px = max(sl_px, trail_high * (1 - trail_pct/100))
                    if lo <= sl_px:
                        exit_roe = (sl_px*(1-slip)/entry_px - 1)*LEVERAGE*100
                        reason = "TRAIL_HIT" if sl_px > entry_px else "SL"
                    elif roe_hi >= tp_roe:
                        tp_px = entry_px * (1 + tp_roe/100/LEVERAGE)
                        exit_roe = (tp_px*(1-slip)/entry_px - 1)*LEVERAGE*100; reason = "TP"
                # time stop applies to all modes
                if exit_roe is None and (i - entry_idx) >= time_stop_h:
                    exit_roe = (cl*(1-slip)/entry_px - 1)*LEVERAGE*100; reason = "TIME"
                # signal off
                if exit_roe is None and (not sig_fn(ind, i)) and roe_cl > SIGNAL_OFF_MIN_ROE:
                    exit_roe = (cl*(1-slip)/entry_px - 1)*LEVERAGE*100; reason = "SIG_OFF"
            if exit_roe is not None:
                hold_h = i - entry_idx
                notional = MARGIN * LEVERAGE
                fee = notional * COST_RT
                funding = notional * FUNDING_8H * (hold_h / 8)
                pnl = -MARGIN-fee if exit_roe <= -100 else MARGIN*(exit_roe/100) - fee - funding
                trades.append({"pnl": pnl, "roe": exit_roe, "reason": reason, "hold_h": hold_h})
                in_pos = False; last_exit = i
                if pnl < 0: last_loss = i
    return trades


def quick_eval(ind, btc, fn, folds, mom, **kwargs):
    all_pnls = []; wf = 0
    for s, e in folds:
        ts = simulate_dynamic(ind, btc, fn, s, e, mom, **kwargs)
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
UNIVERSE = sorted(set(s[1] for s in STRONG) | {"BTCUSDT"})


def run():
    print(f"Phase F: dynamic exit modes")
    cache = {}
    for sym in UNIVERSE:
        df = load_1h(sym)
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_regime = precompute_btc_regime(cache["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache.values())
    fold = n_min // 4
    folds = [(k*fold, (k+1)*fold if k<3 else n_min) for k in range(4)]

    print(f"\n{'sig':<16} {'sym':<10} {'mode':<14} {'param':<22} "
          f"{'n':>4} {'pf':>5} {'wf':>4} {'net':>7}")
    results = []
    t0 = time.time()
    for sig_name, sym, mom, tp, sl in STRONG:
        sig_fn = SIGNALS[sig_name]; ind = cache[sym]

        # baseline = fixed
        bl = quick_eval(ind, btc_regime, sig_fn, folds, mom,
                        exit_mode="fixed", tp_roe=tp, sl_roe=sl)

        if bl is None: continue

        # variants
        configs = [
            ("fixed_baseline", {"exit_mode": "fixed", "tp_roe": tp, "sl_roe": sl}),
            ("trailing_5pct", {"exit_mode": "trailing", "trail_pct": 5.0, "sl_roe": sl}),
            ("trailing_10pct", {"exit_mode": "trailing", "trail_pct": 10.0, "sl_roe": sl}),
            ("atr_2_5", {"exit_mode": "atr", "atr_mult_sl": 2.0, "atr_mult_tp": 5.0}),
            ("atr_3_8", {"exit_mode": "atr", "atr_mult_sl": 3.0, "atr_mult_tp": 8.0}),
            ("hybrid_trail_5", {"exit_mode": "hybrid_trail", "tp_roe": tp, "sl_roe": sl, "trail_pct": 5.0}),
            ("hybrid_trail_10", {"exit_mode": "hybrid_trail", "tp_roe": tp, "sl_roe": sl, "trail_pct": 10.0}),
            ("time_stop_24h", {"exit_mode": "fixed", "tp_roe": tp, "sl_roe": sl, "time_stop_h": 24}),
            ("time_stop_48h", {"exit_mode": "fixed", "tp_roe": tp, "sl_roe": sl, "time_stop_h": 48}),
        ]
        for name, cfg in configs:
            r = quick_eval(ind, btc_regime, sig_fn, folds, mom, **cfg)
            if r is None: continue
            improved = r["net"] > bl["net"] * 1.1 and r["pf"] >= 1.5 and r["wf"] >= 3
            tag = "🥇" if improved else "  "
            results.append({
                "signal": sig_name, "symbol": sym, "mom_min": mom, "tp": tp, "sl": sl,
                "exit_mode": name, "config": cfg, **r,
                "baseline_net": bl["net"], "baseline_pf": bl["pf"],
                "improved": improved,
            })
            if improved:
                param_str = ", ".join(f"{k}={v}" for k,v in cfg.items() if k!="exit_mode")
                print(f"{tag} {sig_name:<16} {sym:<10} {name:<14} {param_str:<22} "
                      f"{r['n']:>4} {r['pf']:>5.2f} {r['wf']:>3}/4 ${r['net']:>+6.0f} "
                      f"(was ${bl['net']:+.0f} PF={bl['pf']:.2f})")

    out = Path("quant_runtime/output/auto4h/phaseF_dynexit.json")
    with open(out, "w") as f:
        json.dump({"results": results}, f, indent=2, default=str)
    improvements = [r for r in results if r["improved"]]
    print(f"\n[saved] {out}")
    print(f"Phase F runtime: {time.time()-t0:.1f}s, {len(improvements)} improvements")


if __name__ == "__main__":
    run()
