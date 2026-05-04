#!/usr/bin/env python3
"""Phase Q: Short side exploration.

기존 모든 전략 long-only. 베어 사이클에서는 무수익.
12 시그널 의 inverse (반대 신호) 를 short entry 로 시도:
  - vol_expansion 의 반대 = bb_lower 돌파 + 모멘텀 음수
  - momentum_obv 의 반대 = ema20<ema50 + obv slope <0
  - heikin_cont 의 반대 = 3 봉 연속 음봉
  - atr_expansion 반대 = bb 확장 + close < ema50

20 코인 × 5 short signal × 5 mom × 4 TP/SL = 2000 evals
"""
from __future__ import annotations
import sys, json, time
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv

LEVERAGE = 10
MARGIN = 50.0
COST_RT = 0.0012
FUNDING_8H = 0.0001
SLIPPAGE_BPS = 8
LIQ_ROE = -95.0
COOLDOWN_EXIT = 12
COOLDOWN_LOSS = 24


def short_vol_expansion(ind, i):
    if i < 30: return False
    return (ind["bb_width_rank"][i] >= 0.7 and ind["mom24"][i] < -0.03
            and ind["close"][i] < ind["bb_lower"][i] and ind["vol_r"][i] >= 1.5)


def short_momentum_obv(ind, i):
    if i < 25: return False
    if "obv_slope" not in ind: return False
    return (ind["mom24"][i] < -0.05 and ind["ema20"][i] < ind["ema50"][i]
            and ind["adx"][i] > 22 and ind["vol_r"][i] >= 1.3
            and ind["obv_slope"][i] < 0)


def short_donchian_20(ind, i):
    if i < 21: return False
    low20 = ind["low"][i-20:i]
    return (ind["close"][i] < np.min(low20) and ind["vol_r"][i] >= 1.5
            and ind["mom24"][i] < -0.02)


def short_heikin_cont(ind, i):
    if i < 3: return False
    bearish = all(ind["close"][k] < ind["close"][k-1] for k in range(i-2, i+1))
    return bearish and ind["close"][i] < ind["ema20"][i] and ind["vol_r"][i] > 1.4


def short_atr_expansion(ind, i):
    if i < 50: return False
    bb_w = ind["bb_width"]
    s = max(0, i-49); bb_w_ma = np.mean(bb_w[s:i+1])
    return (bb_w[i] > bb_w_ma * 1.2 and ind["close"][i] < ind["ema50"][i]
            and ind["close"][i] < ind["close"][i-1] and ind["vol_r"][i] >= 1.3)


SHORT_SIGNALS = {
    "short_vol_expansion": short_vol_expansion,
    "short_momentum_obv": short_momentum_obv,
    "short_donchian_20": short_donchian_20,
    "short_heikin_cont": short_heikin_cont,
    "short_atr_expansion": short_atr_expansion,
}


def precompute_bear_regime(ind):
    """BTC EMA20<EMA50 + ATR rank>=0.4 (bear regime mirror)."""
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
    return (ind["ema20"] < ind["ema50"]) & (atr_rank >= 0.4)


def simulate_short(ind, btc_bear, sig_fn, start, end, tp, sl, mom_max):
    """tp >0 = profit when short (price falls). sl <0 = loss when short."""
    trades = []
    in_pos = False; entry_px = 0; entry_idx = 0
    last_exit = -1; last_loss = -1
    slip = SLIPPAGE_BPS / 10000.0
    for i in range(max(start, 50), end):
        if not in_pos:
            if last_exit >= 0 and (i - last_exit) < COOLDOWN_EXIT: continue
            if last_loss >= 0 and (i - last_loss) < COOLDOWN_LOSS: continue
            if i < len(btc_bear) and not btc_bear[i]: continue
            if ind["mom24"][i] > mom_max: continue
            if not sig_fn(ind, i): continue
            entry_px = ind["close"][i] * (1 - slip)  # short: shave entry
            entry_idx = i; in_pos = True
        else:
            hi = ind["high"][i]; lo = ind["low"][i]; cl = ind["close"][i]
            # short: profit when price falls
            roe_lo = (entry_px / lo - 1) * LEVERAGE * 100  # max profit if low hits
            roe_hi = (entry_px / hi - 1) * LEVERAGE * 100  # min if high hits (loss)
            roe_cl = (entry_px / cl - 1) * LEVERAGE * 100
            exit_roe = None
            if roe_hi <= -95: exit_roe = -100  # liquidation if price spiked up
            elif roe_hi <= sl:  # SL hit (negative roe = loss)
                sl_px = entry_px * (1 - sl/100/LEVERAGE)  # short SL is HIGHER
                exit_roe = (entry_px / (sl_px*(1+slip)) - 1)*LEVERAGE*100
            elif roe_lo >= tp:  # TP hit
                tp_px = entry_px * (1 - tp/100/LEVERAGE)
                exit_roe = (entry_px / (tp_px*(1+slip)) - 1)*LEVERAGE*100
            elif (not sig_fn(ind, i)) and roe_cl > 0:
                exit_roe = (entry_px / (cl*(1+slip)) - 1)*LEVERAGE*100
            if exit_roe is not None:
                hold = i - entry_idx
                notional = MARGIN * LEVERAGE
                pnl = -MARGIN-notional*COST_RT if exit_roe<=-100 else MARGIN*(exit_roe/100) - notional*COST_RT - notional*FUNDING_8H*(hold/8)
                trades.append({"pnl": pnl})
                in_pos = False; last_exit = i
                if pnl < 0: last_loss = i
    return trades


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
    print("Phase Q: short side exploration")
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

    bear_fraction = float(btc_bear[:n_min].mean())
    print(f"  BTC bear regime: {bear_fraction*100:.1f}% of bars")

    if bear_fraction < 0.05:
        print(f"  ⚠️ Bear regime too rare ({bear_fraction*100:.1f}%) — skip short-side exploration")
        # save empty result
        out = Path("quant_runtime/output/auto4h/phaseQ_short.json")
        with open(out, "w") as f:
            json.dump({"bear_fraction": bear_fraction, "results": [], "note": "skipped"},
                      f, indent=2, default=str)
        return

    results = []
    print(f"\n{'sig':<22} {'sym':<10} {'mom':>5} {'TP/SL':>9} {'n':>4} {'pf':>5} {'wf':>4} {'net':>7}")
    t0 = time.time()
    n_eval = 0; n_robust = 0
    for sig_name, sig_fn in SHORT_SIGNALS.items():
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
    print(f"\n=== TOP 15 SHORT WINNERS ===")
    for r in results[:15]:
        print(f"  {r['signal']:<22} {r['symbol']:<10} mom{r['mom_max']*100:>+3.0f}% "
              f"TP+{r['tp']}/SL{r['sl']}: PF={r['pf']:.2f} WF={r['wf']}/4 "
              f"n={r['n']} net=${r['net']:+.0f}")
    out = Path("quant_runtime/output/auto4h/phaseQ_short.json")
    with open(out, "w") as f:
        json.dump({"bear_fraction": bear_fraction, "results": results,
                   "n_eval": n_eval, "n_robust": n_robust}, f, indent=2, default=str)
    print(f"\n[saved] {out}")
    print(f"Phase Q runtime: {time.time()-t0:.1f}s, {n_robust}/{n_eval} robust")


if __name__ == "__main__":
    run()
