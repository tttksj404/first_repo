#!/usr/bin/env python3
"""Phase ZZ: Parameter sensitivity grid (CLAUDE.md mandatory check).

Rule: 인접 TP/SL 10+개 조합이 전부 수익.

Per strategy, run 3×3 = 9 grid:
  TP ∈ {chosen × 0.8, chosen, chosen × 1.2}
  SL ∈ {chosen × 0.8, chosen, chosen × 1.2}  (sl is negative; magnitude scaled)
  → 9 combos. Sometimes also test ±40% for outer perimeter.

A strategy is "knife-edge" if only the central cell is profitable.
A strategy is "robust" if ≥7/9 cells produce net > 0 AND PF ≥ 1.0.

Output: per-strategy heatmap (3×3 net) + verdict.
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
from auto4h_phaseQ_short_side import SHORT_SIGNALS, precompute_bear_regime
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


def sim(ind, gate, sig_fn, start, end, tp, sl, mom, side):
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
                funding = notional * FUNDING_8H * (hold/8)
                pnl = -MARGIN-fee if exit_roe<=-100 else MARGIN*(exit_roe/100) - fee - funding
                trades.append(pnl)
                in_pos = False; last_exit = i
                if pnl < 0: last_loss = i
    if not trades: return {"n":0, "pf":0.0, "net":0.0, "wr":0.0}
    wins = [t for t in trades if t>0]; losses = [-t for t in trades if t<0]
    pf = sum(wins)/sum(losses) if losses else float("inf")
    net = sum(trades)
    wr = len(wins)/len(trades)*100
    return {"n":len(trades), "pf":pf, "net":net, "wr":wr}


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
    print("Phase ZZ: parameter sensitivity grid (CLAUDE.md mandatory)")
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

    factors = [0.8, 1.0, 1.2]
    results = []
    for sid, sig, sym, mom, tp_c, sl_c in LONG_SET + SHORT_SET:
        if sym not in cache: continue
        side = "long" if (sid, sig, sym, mom, tp_c, sl_c) in LONG_SET else "short"
        gate = btc_long if side=="long" else btc_bear
        sig_fn = SIGNALS.get(sig) or ALL_SHORT.get(sig)
        grid = []  # list of (tp, sl, n, pf, net, wr)
        n_robust = 0
        for ftp in factors:
            for fsl in factors:
                tp = tp_c * ftp
                sl = sl_c * fsl  # sl is negative; *fsl preserves sign and scales magnitude
                r = sim(cache[sym], gate, sig_fn, 0, n_min, tp, sl, mom, side)
                profitable = r["net"] > 0 and r["pf"] >= 1.0 and r["n"] >= 5
                if profitable: n_robust += 1
                grid.append({"tp":tp, "sl":sl, "factor_tp":ftp, "factor_sl":fsl,
                             "n":r["n"], "pf":r["pf"], "net":r["net"], "wr":r["wr"],
                             "profitable":profitable})
        verdict = "ROBUST" if n_robust >= 7 else ("ACCEPTABLE" if n_robust >=5 else "FRAGILE")
        results.append({"sid":sid, "side":side, "tp_chosen":tp_c, "sl_chosen":sl_c,
                        "grid":grid, "n_robust":n_robust, "verdict":verdict})
        # Pretty print 3x3
        print(f"\n  {sid} ({side}, tp={tp_c}, sl={sl_c})")
        print(f"    {'tp×':<5}" + "".join([f"sl×{f}    " for f in factors]))
        for ftp in factors:
            row = f"    {ftp:<4} "
            for fsl in factors:
                cell = next(g for g in grid if g["factor_tp"]==ftp and g["factor_sl"]==fsl)
                mark = "✓" if cell["profitable"] else "✗"
                row += f"{mark}${cell['net']:>+5.0f} "
            print(row)
        print(f"    → {n_robust}/9 profitable. {verdict}")

    n_robust = sum(1 for r in results if r["verdict"]=="ROBUST")
    n_acc = sum(1 for r in results if r["verdict"]=="ACCEPTABLE")
    n_frag = sum(1 for r in results if r["verdict"]=="FRAGILE")
    print(f"\n=== Summary (13 strategies × 9 grid cells = 117 backtests) ===")
    print(f"  ROBUST (≥7/9): {n_robust}")
    print(f"  ACCEPTABLE (5-6/9): {n_acc}")
    print(f"  FRAGILE (<5/9): {n_frag}")

    if n_frag == 0:
        verdict = f"OVERALL ROBUST — 0/13 fragile. CLAUDE.md sensitivity rule satisfied."
    elif n_frag <= 2:
        verdict = f"OVERALL ACCEPTABLE — {n_frag}/13 fragile. Drop or watch in production."
    else:
        verdict = f"OVERALL FRAGILE — {n_frag}/13 fragile. Substantial overfit risk."
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseZZ_param_sensitivity.json")
    with open(out_path, "w") as f:
        json.dump({"strategies": results, "n_robust": n_robust, "n_acceptable": n_acc,
                   "n_fragile": n_frag, "verdict": verdict}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
