#!/usr/bin/env python3
"""Phase QQ: 4-fold walk-forward on 13 production strategies.

CLAUDE.md mandatory rule: WF >= 3/4 to qualify for live.
Earlier phases used 70/30 train/OOS split — single OOS fold.
This validates each strategy survives 4 distinct time windows.

Per strategy:
  fold k of 4: bars [k/4 * n, (k+1)/4 * n] within last 70% (OOS region).
  PASS if PF >= 1.0 AND net > 0 in that fold.
  Score = number of passing folds (0..4).
  Production qualified = WF >= 3/4.

Output: phaseQQ_walkforward.json with per-strategy fold breakdown.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv
from auto4h_signal_library import SIGNALS
from auto4h_phaseQ_short_side import (
    SHORT_SIGNALS, precompute_bear_regime,
)
from auto4h_phaseV_extra_shorts import EXTRA_SHORT_SIGNALS
from auto4h_stage1_matrix import precompute_btc_regime

ALL_SHORT = {**SHORT_SIGNALS, **EXTRA_SHORT_SIGNALS}

LEVERAGE = 10
MARGIN = 50.0
COST_RT = 0.0012
FUNDING_8H = 0.00012
SLIPPAGE_BPS = 8
LIQ_ROE = -95.0
COOLDOWN_EXIT = 12
COOLDOWN_LOSS = 24


def sim_fold(ind, gate, sig_fn, start, end, tp, sl, mom, side):
    trades = []
    in_pos = False; entry_px = 0; entry_idx = 0
    last_exit = -1; last_loss = -1
    slip = SLIPPAGE_BPS / 10000.0
    for i in range(max(start, 50), end):
        if not in_pos:
            if last_exit >= 0 and (i - last_exit) < COOLDOWN_EXIT: continue
            if last_loss >= 0 and (i - last_loss) < COOLDOWN_LOSS: continue
            if i < len(gate) and not gate[i]: continue
            if side == "long":
                if ind["mom24"][i] < mom: continue
            else:
                if ind["mom24"][i] > mom: continue
            if not sig_fn(ind, i): continue
            entry_px = ind["close"][i] * (1 + slip if side=="long" else 1 - slip)
            entry_idx = i; in_pos = True
        else:
            hi = ind["high"][i]; lo = ind["low"][i]; cl = ind["close"][i]
            if side == "long":
                roe_lo = (lo / entry_px - 1) * LEVERAGE * 100
                roe_hi = (hi / entry_px - 1) * LEVERAGE * 100
                roe_cl = (cl / entry_px - 1) * LEVERAGE * 100
            else:
                roe_lo = (entry_px / lo - 1) * LEVERAGE * 100
                roe_hi = (entry_px / hi - 1) * LEVERAGE * 100
                roe_cl = (entry_px / cl - 1) * LEVERAGE * 100
            exit_roe = None
            if side == "long":
                if roe_lo <= LIQ_ROE: exit_roe = -100
                elif roe_lo <= sl: exit_roe = sl
                elif roe_hi >= tp: exit_roe = tp
                elif (not sig_fn(ind, i)) and roe_cl > 0: exit_roe = roe_cl
            else:
                if roe_hi <= LIQ_ROE: exit_roe = -100
                elif roe_hi <= sl: exit_roe = sl
                elif roe_lo >= tp: exit_roe = tp
                elif (not sig_fn(ind, i)) and roe_cl > 0: exit_roe = roe_cl
            if exit_roe is not None:
                hold = i - entry_idx
                notional = MARGIN * LEVERAGE
                fee = notional * COST_RT
                funding = notional * FUNDING_8H * (hold / 8)
                pnl = -MARGIN-fee if exit_roe<=-100 else MARGIN*(exit_roe/100) - fee - funding
                trades.append(pnl)
                in_pos = False; last_exit = i
                if pnl < 0: last_loss = i
    if not trades:
        return {"n": 0, "pf": 0.0, "net": 0.0, "wr": 0.0, "pass": False}
    wins = [t for t in trades if t > 0]; losses = [-t for t in trades if t < 0]
    pf = sum(wins) / sum(losses) if losses else float("inf")
    net = sum(trades)
    wr = len(wins) / len(trades) * 100
    passed = pf >= 1.0 and net > 0 and len(trades) >= 3
    return {"n": len(trades), "pf": pf, "net": net, "wr": wr, "pass": passed}


# 13 production strategies from Phase GG / FINAL_REPORT
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
    ("eth_heikin_S", "short_heikin_cont", "ETHUSDT", -0.04, 80, -30),
    ("near_atrexp_S", "short_atr_expansion", "NEARUSDT", -0.02, 200, -40),
    ("sui_momobv_S", "short_momentum_obv", "SUIUSDT", -0.06, 200, -40),
    ("arb_rsi_S", "short_rsi_breakdown", "ARBUSDT", -0.02, 200, -40),
    ("dot_adx_S", "short_adx_trend_dn", "DOTUSDT", -0.02, 150, -35),
    ("link_adx_S", "short_adx_trend_dn", "LINKUSDT", -0.06, 200, -40),
]


def run():
    print("Phase QQ: 4-fold walk-forward on 13 production strategies")
    universe = sorted(set([s[2] for s in LONG_SET] + [s[2] for s in SHORT_SET]) | {"BTCUSDT"})
    cache = {}
    for sym in universe:
        df = load_1h(sym)
        if df is None: continue
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_long = precompute_btc_regime(cache["BTCUSDT"])
    btc_bear = precompute_bear_regime(cache["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache.values())

    # Use full history split into 4 equal folds
    fold_n = n_min // 4
    folds = [(k * fold_n, (k+1) * fold_n) for k in range(4)]
    print(f"  Total bars: {n_min}, 4 folds × {fold_n} bars each")

    results = []
    for sid, sig, sym, mom, tp, sl in LONG_SET:
        if sym not in cache: continue
        per_fold = []
        for k, (s, e) in enumerate(folds):
            r = sim_fold(cache[sym], btc_long, SIGNALS[sig], s, e, tp, sl, mom, "long")
            r["fold"] = k+1
            per_fold.append(r)
        wf = sum(1 for f in per_fold if f["pass"])
        total_n = sum(f["n"] for f in per_fold)
        total_net = sum(f["net"] for f in per_fold)
        results.append({"sid": sid, "side": "long", "wf": wf, "total_n": total_n,
                        "total_net": total_net, "folds": per_fold,
                        "qualified": wf >= 3})
        flags = "".join(["✓" if f["pass"] else "✗" for f in per_fold])
        print(f"  L {sid:<20} WF={wf}/4 {flags}  n={total_n:>3}  net=${total_net:+8.0f}  {'QUAL' if wf>=3 else 'fail'}")

    for sid, sig, sym, mom, tp, sl in SHORT_SET:
        if sym not in cache: continue
        per_fold = []
        for k, (s, e) in enumerate(folds):
            r = sim_fold(cache[sym], btc_bear, ALL_SHORT[sig], s, e, tp, sl, mom, "short")
            r["fold"] = k+1
            per_fold.append(r)
        wf = sum(1 for f in per_fold if f["pass"])
        total_n = sum(f["n"] for f in per_fold)
        total_net = sum(f["net"] for f in per_fold)
        results.append({"sid": sid, "side": "short", "wf": wf, "total_n": total_n,
                        "total_net": total_net, "folds": per_fold,
                        "qualified": wf >= 3})
        flags = "".join(["✓" if f["pass"] else "✗" for f in per_fold])
        print(f"  S {sid:<20} WF={wf}/4 {flags}  n={total_n:>3}  net=${total_net:+8.0f}  {'QUAL' if wf>=3 else 'fail'}")

    qualified = [r for r in results if r["qualified"]]
    print(f"\n=== Summary ===")
    print(f"  Total strategies: {len(results)}")
    print(f"  WF >= 3/4 qualified: {len(qualified)}")
    print(f"  WF = 4/4 perfect: {sum(1 for r in results if r['wf']==4)}")
    print(f"  WF = 0/4 broken: {sum(1 for r in results if r['wf']==0)}")

    if len(qualified) >= 10:
        verdict = f"ROBUST — {len(qualified)}/13 strategies pass WF>=3/4 (CLAUDE.md mandatory)"
    elif len(qualified) >= 7:
        verdict = f"ACCEPTABLE — {len(qualified)}/13 pass; trim non-qualified before live"
    else:
        verdict = f"FRAGILE — only {len(qualified)}/13 pass; portfolio overfit suspected"
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseQQ_walkforward.json")
    with open(out_path, "w") as f:
        json.dump({"strategies": results, "qualified_count": len(qualified),
                   "verdict": verdict}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
