#!/usr/bin/env python3
"""auto4h Stage 1: signal × coin × mom_min baseline matrix.

각 (signal, coin, mom_min) 조합을 fixed TP=200/SL=-30 으로 1년 백테.
WF 4-fold + PF + n trades 계산.

통과 기준 (Stage 2 후보):
  - PF > 1.0 globally
  - WF >= 3/4
  - n_trades >= 8 (1년 / fold 2개)
  - net > $30
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
REGIME_ATR_MIN = 0.4

TP_BASELINE = 200.0
SL_BASELINE = -30.0


def precompute_btc_regime(btc_ind):
    n = len(btc_ind["close"])
    high = btc_ind["high"]; low = btc_ind["low"]; close = btc_ind["close"]
    ema20 = btc_ind["ema20"]; ema50 = btc_ind["ema50"]
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
    atr24 = np.zeros(n)
    for i in range(n):
        s = max(0, i - 23); atr24[i] = np.mean(tr[s:i+1])
    atr_rank = np.zeros(n)
    for i in range(n):
        s = max(0, i - 199); seg = atr24[s:i+1]
        atr_rank[i] = (seg <= atr24[i]).mean() if len(seg) else 0.5
    regime = np.zeros(n, dtype=bool)
    for i in range(n):
        regime[i] = (ema20[i] > ema50[i]) and (atr_rank[i] >= REGIME_ATR_MIN)
    return regime


def simulate(ind, btc_regime, sig_fn, start_idx, end_idx, tp_roe, sl_roe, mom_min):
    trades = []
    in_pos = False; entry_px = 0.0; entry_idx = 0
    last_exit_i = -1; last_loss_i = -1
    slip = SLIPPAGE_BPS / 10000.0

    for i in range(max(start_idx, 50), end_idx):
        if not in_pos:
            if last_exit_i >= 0 and (i - last_exit_i) < COOLDOWN_AFTER_EXIT_H: continue
            if last_loss_i >= 0 and (i - last_loss_i) < COOLDOWN_AFTER_LOSS_H: continue
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
            elif roe_lo <= sl_roe:
                sl_px = entry_px * (1 + sl_roe/100/LEVERAGE)
                fill = sl_px * (1 - slip)
                exit_roe = (fill / entry_px - 1) * LEVERAGE * 100
                reason = "SL"
            elif roe_hi >= tp_roe:
                tp_px = entry_px * (1 + tp_roe/100/LEVERAGE)
                fill = tp_px * (1 - slip)
                exit_roe = (fill / entry_px - 1) * LEVERAGE * 100
                reason = "TP"
            else:
                if (not sig_fn(ind, i)) and roe_cl > SIGNAL_OFF_MIN_ROE:
                    fill = cl * (1 - slip)
                    exit_roe = (fill / entry_px - 1) * LEVERAGE * 100
                    reason = "SIG_OFF"
            if exit_roe is not None:
                hold_h = i - entry_idx
                notional = MARGIN * LEVERAGE
                fee = notional * COST_RT
                funding = notional * FUNDING_8H * (hold_h / 8)
                if exit_roe <= -100:
                    pnl = -MARGIN - fee
                else:
                    pnl = MARGIN * (exit_roe / 100) - fee - funding
                trades.append({"pnl": pnl, "roe": exit_roe, "reason": reason, "hold_h": hold_h})
                in_pos = False; last_exit_i = i
                if pnl < 0: last_loss_i = i
    return trades


def run():
    universe = json.load(open("quant_runtime/output/auto4h/universe_check.json"))["ok"]
    print(f"Stage 1: {len(universe)} coins × {len(SIGNALS)} signals × 3 mom_min = "
          f"{len(universe)*len(SIGNALS)*3} combos")

    print("loading data...")
    cache = {}
    for sym in universe:
        df = load_1h(sym)
        ind = compute_indicators(df)
        ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind

    btc_regime = precompute_btc_regime(cache["BTCUSDT"])
    n_min = min(len(cache[s]["close"]) for s in universe)
    fold_size = n_min // 4
    folds = [(k*fold_size, (k+1)*fold_size if k<3 else n_min) for k in range(4)]

    results = []
    t0 = time.time()
    for sig_name, sig_fn in SIGNALS.items():
        for sym in universe:
            for mom_min in [0.02, 0.04, 0.06]:
                fold_pnls_per_fold = []
                all_pnls = []
                tp_count = sl_count = sig_count = liq_count = 0
                for s_i, e_i in folds:
                    trades = simulate(cache[sym], btc_regime, sig_fn,
                                      s_i, e_i, TP_BASELINE, SL_BASELINE, mom_min)
                    fold_pnls = [t["pnl"] for t in trades]
                    fold_pnls_per_fold.append(fold_pnls)
                    all_pnls.extend(fold_pnls)
                    for t in trades:
                        if t["reason"] == "TP": tp_count += 1
                        elif t["reason"] == "SL": sl_count += 1
                        elif t["reason"] == "LIQ": liq_count += 1
                        else: sig_count += 1
                wf_pass = 0
                for fp in fold_pnls_per_fold:
                    if fp:
                        a = np.array(fp)
                        w = a[a>0].sum(); l = abs(a[a<0].sum())
                        pf_f = w/l if l>0 else 99
                        if pf_f > 1.0 and len(a) >= 3: wf_pass += 1
                if all_pnls:
                    pn = np.array(all_pnls)
                    wins = pn[pn>0]; losses = pn[pn<0]
                    pf = wins.sum()/abs(losses.sum()) if losses.sum()<0 else 99
                    wr = (pn>0).mean()*100
                    net = pn.sum()
                else:
                    pf=0; wr=0; net=0
                results.append({
                    "signal": sig_name, "symbol": sym, "mom_min": mom_min,
                    "n": len(all_pnls), "wr": float(wr), "pf": float(pf),
                    "net": float(net), "wf": int(wf_pass),
                    "tp_n": tp_count, "sl_n": sl_count, "sig_n": sig_count, "liq_n": liq_count,
                })
        elapsed = time.time() - t0
        done = (list(SIGNALS.keys()).index(sig_name)+1) * len(universe) * 3
        total = len(SIGNALS) * len(universe) * 3
        print(f"  {sig_name:18s} done. {done}/{total}, elapsed={elapsed:.1f}s")

    # rank
    results.sort(key=lambda r: (-r["wf"], -r["net"]))
    print(f"\n=== TOP 30 (by WF, net) ===")
    print(f"{'rank':>4} {'signal':<16} {'sym':<10} {'mom':>5} {'n':>4} {'WR%':>5} {'PF':>5} {'WF':>3} {'NET$':>7}  reasons")
    for k, r in enumerate(results[:30]):
        print(f"{k+1:>4} {r['signal']:<16} {r['symbol']:<10} {r['mom_min']*100:>4.0f}% "
              f"{r['n']:>4} {r['wr']:>4.1f} {r['pf']:>5.2f} {r['wf']:>3}/4 {r['net']:>+7.0f}  "
              f"TP{r['tp_n']}/SL{r['sl_n']}/SIG{r['sig_n']}/LIQ{r['liq_n']}")

    # passing criteria for Stage 2: PF > 1.0, WF >= 3, n >= 8, net > 30
    passers = [r for r in results
               if r["pf"] > 1.0 and r["wf"] >= 3 and r["n"] >= 8 and r["net"] > 30]
    print(f"\n=== Stage 2 candidates (PF>1, WF>=3, n>=8, net>$30): {len(passers)} ===")
    for r in passers:
        print(f"  {r['signal']:<16} {r['symbol']:<10} mom{r['mom_min']*100:.0f}% "
              f"PF={r['pf']:.2f} WF={r['wf']}/4 n={r['n']} net=${r['net']:+.0f}")

    out = Path("quant_runtime/output/auto4h/stage1_matrix.json")
    with open(out, "w") as f:
        json.dump({"all_results": results, "passers": passers,
                   "config": {"tp": TP_BASELINE, "sl": SL_BASELINE,
                              "n_universe": len(universe), "n_signals": len(SIGNALS)}},
                  f, indent=2, default=str)
    print(f"\n[saved] {out}")
    print(f"Total runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    run()
