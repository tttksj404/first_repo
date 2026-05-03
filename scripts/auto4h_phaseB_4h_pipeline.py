#!/usr/bin/env python3
"""Phase B: 4h timeframe full pipeline (same Stage 1-3 logic but on 4h candles).

1h timeframe에서 14 STRONG 발견했지만 "4시간 잭팟" 컨셉이라 4h candle 자체 검증.
Cooldown은 시간 단위 → 4h에서는 hours/4 = bar 수.
"""
from __future__ import annotations
import sys, json, time
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import HIST, compute_indicators
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
# 4h candle: cooldown in bars (1h units → bars: 12h=3bars, 24h=6bars)
COOLDOWN_AFTER_EXIT_BARS = 3
COOLDOWN_AFTER_LOSS_BARS = 6
REGIME_ATR_MIN = 0.4

UNIVERSE = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT", "WIFUSDT",
            "SUIUSDT", "ARBUSDT", "OPUSDT", "AVAXUSDT", "NEARUSDT", "APTUSDT",
            "MATICUSDT", "LINKUSDT", "UNIUSDT", "PEPEUSDT"]


def load_4h(symbol):
    path = HIST / symbol / "4h.json"
    if not path.exists(): return None
    raw = json.loads(path.read_text())
    if len(raw) < 500: return None
    return np.array([[r["open_time"], r["open_price"], r["high_price"],
                      r["low_price"], r["close_price"], r.get("base_volume", 0.0)]
                     for r in raw], dtype=np.float64)


def precompute_btc_regime_4h(btc_ind):
    n = len(btc_ind["close"])
    high = btc_ind["high"]; low = btc_ind["low"]; close = btc_ind["close"]
    ema20 = btc_ind["ema20"]; ema50 = btc_ind["ema50"]
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
    # 24h on 4h = 6 bars
    atr_w = 6
    atr = np.zeros(n)
    for i in range(n):
        s = max(0, i - atr_w + 1); atr[i] = np.mean(tr[s:i+1])
    rank = np.zeros(n)
    for i in range(n):
        s = max(0, i - 49); seg = atr[s:i+1]
        rank[i] = (seg <= atr[i]).mean() if len(seg) else 0.5
    regime = np.zeros(n, dtype=bool)
    for i in range(n):
        regime[i] = (ema20[i] > ema50[i]) and (rank[i] >= REGIME_ATR_MIN)
    return regime


def simulate_4h(ind, btc_regime, sig_fn, start, end, tp, sl, mom_min):
    trades = []
    in_pos = False; entry_px = 0.0; entry_idx = 0
    last_exit = -1; last_loss = -1
    slip = SLIPPAGE_BPS / 10000.0
    for i in range(max(start, 50), end):
        if not in_pos:
            if last_exit >= 0 and (i - last_exit) < COOLDOWN_AFTER_EXIT_BARS: continue
            if last_loss >= 0 and (i - last_loss) < COOLDOWN_AFTER_LOSS_BARS: continue
            btc_r = bool(btc_regime[i]) if i < len(btc_regime) else False
            if not btc_r: continue
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
            if roe_lo <= LIQ_ROE:
                exit_roe = -100.0; reason = "LIQ"
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
                hold_bars = i - entry_idx
                hold_h = hold_bars * 4  # 4h bars
                notional = MARGIN * LEVERAGE
                fee = notional * COST_RT
                funding = notional * FUNDING_8H * (hold_h / 8)
                pnl = -MARGIN-fee if exit_roe <= -100 else MARGIN*(exit_roe/100) - fee - funding
                trades.append({"pnl": pnl, "roe": exit_roe, "reason": reason, "hold_h": hold_h})
                in_pos = False; last_exit = i
                if pnl < 0: last_loss = i
    return trades


def run():
    print(f"Phase B: 4h pipeline. {len(UNIVERSE)} coins x {len(SIGNALS)} signals")
    cache = {}
    for sym in UNIVERSE:
        arr = load_4h(sym)
        if arr is None:
            print(f"  skip {sym} (no 4h)"); continue
        ind = compute_indicators(arr); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    if "BTCUSDT" not in cache:
        print("BTC 4h missing — abort"); return
    btc_regime = precompute_btc_regime_4h(cache["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache.values())
    fold = n_min // 4
    folds = [(k*fold, (k+1)*fold if k<3 else n_min) for k in range(4)]
    print(f"  4h bars: {n_min}, BTC regime ON: {btc_regime.mean()*100:.1f}%")

    # Stage 1-equivalent: TP=200/SL=-30 baseline, 3 mom levels
    tp_base, sl_base = 200, -30
    mom_levels = [0.04, 0.08, 0.12]  # higher mom for 4h (24h = 6 bars)
    results = []
    t0 = time.time()
    for sig_name, fn in SIGNALS.items():
        for sym, ind in cache.items():
            for mom in mom_levels:
                all_pnls = []; wf_pass = 0
                for s, e in folds:
                    ts = simulate_4h(ind, btc_regime, fn, s, e, tp_base, sl_base, mom)
                    fp = [t["pnl"] for t in ts]
                    if fp:
                        a = np.array(fp); w = a[a>0].sum(); l = abs(a[a<0].sum())
                        pf_f = w/l if l>0 else 99
                        if pf_f > 1.0 and len(a) >= 3: wf_pass += 1
                    all_pnls.extend(fp)
                if not all_pnls: continue
                a = np.array(all_pnls); pf = a[a>0].sum() / max(abs(a[a<0].sum()), 1e-9)
                results.append({
                    "signal": sig_name, "symbol": sym, "mom_min": mom,
                    "n": len(a), "pf": float(pf), "net": float(a.sum()),
                    "wf": int(wf_pass),
                })
        print(f"  {sig_name:18s} done. elapsed={time.time()-t0:.1f}s")

    # Stage 2-equivalent: top by WF/net → grid TP×SL
    results.sort(key=lambda r: (-r["wf"], -r["net"]))
    passers = [r for r in results if r["pf"] > 1.0 and r["wf"] >= 3 and r["n"] >= 8 and r["net"] > 30]
    print(f"\n  Stage1-eq passers (4h baseline): {len(passers)}")
    for r in passers[:20]:
        print(f"    {r['signal']:<16} {r['symbol']:<10} mom{r['mom_min']*100:.0f}% "
              f"PF={r['pf']:.2f} WF={r['wf']}/4 n={r['n']} net=${r['net']:+.0f}")

    # grid for top 10
    tp_levels = [50, 100, 150, 200, 300, 500]
    sl_levels = [-15, -25, -35, -50]
    candidates_results = []
    print(f"\n=== 4h Grid TP×SL on top 10 ===")
    for c in passers[:10]:
        sig_fn = SIGNALS[c["signal"]]; sym = c["symbol"]; mom = c["mom_min"]
        ind = cache[sym]
        n_robust = 0; best = None
        for tp in tp_levels:
            for sl in sl_levels:
                all_pnls = []; wf_pass = 0
                for s, e in folds:
                    ts = simulate_4h(ind, btc_regime, sig_fn, s, e, tp, sl, mom)
                    fp = [t["pnl"] for t in ts]
                    if fp:
                        a = np.array(fp); w = a[a>0].sum(); l = abs(a[a<0].sum())
                        pf_f = w/l if l>0 else 99
                        if pf_f > 1.0 and len(a) >= 3: wf_pass += 1
                    all_pnls.extend(fp)
                if not all_pnls: continue
                a = np.array(all_pnls); net = float(a.sum())
                pf = a[a>0].sum() / max(abs(a[a<0].sum()), 1e-9)
                if net > 0 and wf_pass >= 3:
                    n_robust += 1
                    if best is None or net > best["net"]:
                        best = {"tp": tp, "sl": sl, "net": net, "pf": float(pf),
                                "wf": wf_pass, "n": len(a)}
        verdict = "✅ ROBUST" if n_robust >= 6 and best and best["pf"] >= 1.5 else "⚠️ WEAK"
        candidates_results.append({**c, "n_robust": n_robust, "best": best, "verdict": verdict})
        if best:
            print(f"  {c['signal']:<16} {sym:<10} mom{mom*100:.0f}% "
                  f"robust={n_robust:>2}/24 best=TP{best['tp']}/SL{best['sl']} "
                  f"${best['net']:+.0f} PF={best['pf']:.2f} {verdict}")

    out = Path("quant_runtime/output/auto4h/phaseB_4h.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump({"baseline_passers": passers, "grid_candidates": candidates_results},
                  f, indent=2, default=str)
    print(f"\n[saved] {out}")
    print(f"Phase B runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    run()
