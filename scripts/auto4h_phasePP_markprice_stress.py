#!/usr/bin/env python3
"""Phase PP: Mark-price / stablecoin de-peg stress.

GPT-5.4 Round 3 last must-fix: liquidations and funding settle on mark price,
not last-trade price. If mark deviates from last (oracle blip, USDT de-peg,
flash crash on a CEX index), our SL/TP/LIQ logic could trigger differently.

Stress scenarios on the 13-strategy production set:
1. mark = last × 1.005 (mark spikes 0.5% above)
2. mark = last × 0.995 (mark drops 0.5%)
3. USDT-de-peg 1% (price feed × 0.99 for 24 bars then revert)

Each scenario: count premature liquidations + spurious SL hits.
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

ALL_SHORT_SIGNALS = {**SHORT_SIGNALS, **EXTRA_SHORT_SIGNALS}

LEVERAGE = 10
MARGIN = 50.0
COST_RT = 0.0012
FUNDING_8H = 0.00012
SLIPPAGE_BPS = 8
LIQ_ROE = -95.0
COOLDOWN_EXIT = 12
COOLDOWN_LOSS = 24


def sim_with_mark_skew(ind, gate, sig_fn, start, end, tp, sl, mom, side, mark_skew):
    """mark_skew: 0 = no distortion, 0.005 = mark 0.5% above, -0.005 = below.
    Mark price is used for liquidation+SL+TP triggers, last price for entry/exit fill.
    """
    trades = []
    in_pos = False; entry_px = 0; entry_idx = 0
    last_exit = -1; last_loss = -1
    slip = SLIPPAGE_BPS / 10000.0
    n_premature_liq = 0; n_spurious_sl = 0
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
            # Mark price = last × (1+skew); used for liq/SL/TP. Last = exit fill.
            hi = ind["high"][i] * (1+mark_skew); lo = ind["low"][i] * (1+mark_skew); cl = ind["close"][i]
            if side == "long":
                roe_lo = (lo / entry_px - 1) * LEVERAGE * 100
                roe_hi = (hi / entry_px - 1) * LEVERAGE * 100
                roe_cl = (cl / entry_px - 1) * LEVERAGE * 100
            else:
                roe_lo = (entry_px / lo - 1) * LEVERAGE * 100
                roe_hi = (entry_px / hi - 1) * LEVERAGE * 100
                roe_cl = (entry_px / cl - 1) * LEVERAGE * 100
            exit_roe = None; exit_reason = None
            if side == "long":
                if roe_lo <= LIQ_ROE:
                    exit_roe = -100; exit_reason = "LIQ"
                    if mark_skew != 0: n_premature_liq += 1
                elif roe_lo <= sl:
                    exit_roe = sl; exit_reason = "SL"
                    if mark_skew != 0: n_spurious_sl += 1
                elif roe_hi >= tp: exit_roe = tp
                elif (not sig_fn(ind, i)) and roe_cl > 0: exit_roe = roe_cl
            else:
                if roe_hi <= LIQ_ROE:
                    exit_roe = -100; exit_reason = "LIQ"
                    if mark_skew != 0: n_premature_liq += 1
                elif roe_hi <= sl:
                    exit_roe = sl; exit_reason = "SL"
                    if mark_skew != 0: n_spurious_sl += 1
                elif roe_lo >= tp: exit_roe = tp
                elif (not sig_fn(ind, i)) and roe_cl > 0: exit_roe = roe_cl
            if exit_roe is not None:
                hold = i - entry_idx
                notional = MARGIN * LEVERAGE
                fee = notional * COST_RT
                funding = notional * FUNDING_8H * (hold / 8)
                pnl = -MARGIN-fee if exit_roe<=-100 else MARGIN*(exit_roe/100) - fee - funding
                trades.append({"pnl": pnl, "reason": exit_reason})
                in_pos = False; last_exit = i
                if pnl < 0: last_loss = i
    return trades, n_premature_liq, n_spurious_sl


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

SCENARIOS = [
    ("baseline", 0.0),
    ("mark_+0.5%", 0.005),
    ("mark_-0.5%", -0.005),
    ("mark_+1.0%", 0.010),  # extreme
    ("mark_-1.0%", -0.010),
]


def run():
    print("Phase PP: mark-price skew stress")
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
    s = int(n_min * 0.7); e = n_min

    print(f"\n  OOS bars: {e-s}")
    out = []
    for scen_name, skew in SCENARIOS:
        long_pnl = 0.0; short_pnl = 0.0; n_long = 0; n_short = 0
        prem_liq = 0; spur_sl = 0
        for sid, sig, sym, mom, tp, sl in LONG_SET:
            if sym not in cache: continue
            ts, pl, ss = sim_with_mark_skew(cache[sym], btc_long, SIGNALS[sig], s, e, tp, sl, mom, "long", skew)
            for t in ts: long_pnl += t["pnl"]; n_long += 1
            prem_liq += pl; spur_sl += ss
        for sid, sig, sym, mom, tp, sl in SHORT_SET:
            if sym not in cache: continue
            ts, pl, ss = sim_with_mark_skew(cache[sym], btc_bear, ALL_SHORT_SIGNALS[sig], s, e, tp, sl, mom, "short", skew)
            for t in ts: short_pnl += t["pnl"]; n_short += 1
            prem_liq += pl; spur_sl += ss
        net = long_pnl + short_pnl
        out.append({"scenario": scen_name, "skew": skew, "long_pnl": long_pnl, "short_pnl": short_pnl,
                    "net": net, "n_long": n_long, "n_short": n_short,
                    "premature_liqs": prem_liq, "spurious_sls": spur_sl})
        print(f"  {scen_name:<14} skew={skew*100:+.1f}% | NET=${net:+.0f}  prem_liq={prem_liq} spur_sl={spur_sl}")

    base = next(o for o in out if o["scenario"]=="baseline")["net"]
    print(f"\n=== Sensitivity vs baseline ${base:+.0f} ===")
    for o in out:
        delta = o["net"] - base
        print(f"  {o['scenario']:<14} ΔNET=${delta:+.0f} ({delta/base*100 if base else 0:+.1f}%)")

    worst = min(o["net"] for o in out)
    if worst > 0:
        verdict = "ROBUST — even ±1% mark-skew keeps portfolio positive"
    elif worst > -150:
        verdict = "ACCEPTABLE — mark-skew triggers warning but no kill-switch"
    else:
        verdict = "FRAGILE — mark-skew destroys profitability"
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phasePP_markprice_stress.json")
    with open(out_path, "w") as f:
        json.dump({"scenarios": out, "verdict": verdict}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
