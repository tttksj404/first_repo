#!/usr/bin/env python3
"""Phase UU: 4-fold regime diversity check.

GPT/Gemini concern: "Are the 4 WF folds in Phase QQ truly diverse market regimes,
or are they all bull/bear in the same 12-month window?"

For each fold, measure:
  - BTC return (start→end %)
  - BTC realized vol (std of returns × sqrt(N))
  - bear_frac (ema20 < ema50 ratio in fold)
  - mean ATR/price (volatility)
  - max drawdown intra-fold

If all 4 folds look similar → backtest is single-regime, WF score 13/13 is weaker than it appears.
If folds diverge meaningfully (different return signs, vol bands) → diversity confirmed.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv


def fold_stats(ind, ts_arr, start, end):
    cl = ind["close"][start:end]
    ts = ts_arr[start:end]
    if len(cl) < 10:
        return None
    ema20 = ind["ema20"][start:end]; ema50 = ind["ema50"][start:end]
    atr = ind["atr"][start:end] if "atr" in ind else None

    ret = (cl[-1] / cl[0] - 1) * 100
    log_ret = np.diff(np.log(cl))
    vol = float(np.std(log_ret) * np.sqrt(24*365) * 100)  # annualized
    bear_frac = float((ema20 < ema50).mean()) * 100

    # Max drawdown intra-fold
    peak = np.maximum.accumulate(cl)
    dd = (cl/peak - 1) * 100
    max_dd = float(dd.min())

    atr_pct = float(np.mean(atr / cl) * 100) if atr is not None and len(atr) == len(cl) else None

    return {
        "start_ts": int(ts[0]), "end_ts": int(ts[-1]),
        "start_iso": datetime.fromtimestamp(int(ts[0])/1000).strftime("%Y-%m-%d"),
        "end_iso": datetime.fromtimestamp(int(ts[-1])/1000).strftime("%Y-%m-%d"),
        "btc_start": float(cl[0]), "btc_end": float(cl[-1]),
        "ret_pct": ret, "vol_ann_pct": vol, "bear_frac_pct": bear_frac,
        "max_dd_pct": max_dd, "atr_pct": atr_pct, "n_bars": len(cl),
    }


def run():
    print("Phase UU: 4-fold regime diversity")
    df = load_1h("BTCUSDT")
    ts_arr = df[:, 0]  # column 0 is timestamp ms
    ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
    n = len(ind["close"])
    fold_n = n // 4
    folds = [(k*fold_n, (k+1)*fold_n) for k in range(4)]

    results = []
    for k, (s, e) in enumerate(folds):
        r = fold_stats(ind, ts_arr, s, e)
        if r is None: continue
        r["fold"] = k+1
        results.append(r)
        print(f"  Fold {k+1}: {r['start_iso']} → {r['end_iso']} | "
              f"ret={r['ret_pct']:+6.1f}% vol={r['vol_ann_pct']:.0f}% "
              f"bear={r['bear_frac_pct']:.0f}% maxDD={r['max_dd_pct']:.1f}%")

    rets = [r["ret_pct"] for r in results]
    vols = [r["vol_ann_pct"] for r in results]
    bears = [r["bear_frac_pct"] for r in results]

    ret_range = max(rets) - min(rets)
    vol_range = max(vols) - min(vols)
    bear_range = max(bears) - min(bears)

    print(f"\n=== Diversity ranges ===")
    print(f"  return:    {min(rets):+.1f}% ~ {max(rets):+.1f}% (range {ret_range:.1f}pp)")
    print(f"  volatility: {min(vols):.0f}% ~ {max(vols):.0f}% (range {vol_range:.0f}pp)")
    print(f"  bear_frac: {min(bears):.0f}% ~ {max(bears):.0f}% (range {bear_range:.0f}pp)")

    # Diversity verdict
    n_bull = sum(1 for r in rets if r > 5)
    n_bear = sum(1 for r in rets if r < -5)
    n_chop = sum(1 for r in rets if -5 <= r <= 5)
    print(f"\n  fold types: {n_bull} bull (>+5%), {n_bear} bear (<-5%), {n_chop} chop (±5%)")

    if n_bull >= 1 and n_bear >= 1 and bear_range >= 30:
        verdict = "DIVERSE — folds span bull/bear/chop, bear_frac varies 30+pp. WF 13/13 is genuine."
    elif ret_range >= 30 or bear_range >= 25:
        verdict = "MODERATE — folds show meaningful spread but missing one regime extreme."
    else:
        verdict = "LIMITED — all 4 folds look similar; WF score may overstate generalization."
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseUU_regime_diversity.json")
    with open(out_path, "w") as f:
        json.dump({"folds": results,
                   "ret_range_pp": ret_range, "vol_range_pp": vol_range,
                   "bear_range_pp": bear_range, "verdict": verdict},
                  f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
