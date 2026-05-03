#!/usr/bin/env python3
"""Phase Z: Dynamic capital allocator.

GPT/Gemini Round 2 비판: short capital ~70% idle (bear regime 29.7%).
실제 라이브 = $50 단일 자본. 어떻게 할당하는 게 최적?

3 모드 비교:
A) STATIC EQUAL: 7 long + 6 short 각 strategy 에 $50 margin (paper = 13 × $50 = $650 시뮬)
B) STATIC PROPORTIONAL: long 70% / short 30% (regime occupancy 비례)
C) DYNAMIC: BTC bear ON → short pool 만 active, OFF → long pool 만 active

각 모드의 OOS net + per-bar capital efficiency 측정.
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
from auto4h_stage1_matrix import simulate as sim_long, precompute_btc_regime
from auto4h_phaseQ_short_side import (
    SHORT_SIGNALS, simulate_short, precompute_bear_regime,
)
from auto4h_phaseV_extra_shorts import EXTRA_SHORT_SIGNALS

ALL_SHORT_SIGNALS = {**SHORT_SIGNALS, **EXTRA_SHORT_SIGNALS}

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


def collect_trades(LONG_SET, SHORT_SET, cache, btc_long, btc_bear, oos_s, oos_e):
    """Return per-strategy OOS trade list with entry_idx, exit_idx, pnl."""
    out = {"long": {}, "short": {}}
    # Note: simulate() returns trades but not entry/exit indices.
    # Use net pnl per strategy for analysis.
    for sid, sig, sym, mom, tp, sl in LONG_SET:
        if sym not in cache: continue
        ts = sim_long(cache[sym], btc_long, SIGNALS[sig], oos_s, oos_e, tp, sl, mom)
        out["long"][sid] = sum(t["pnl"] for t in ts)
    for sid, sig, sym, mom, tp, sl in SHORT_SET:
        if sym not in cache: continue
        fn = ALL_SHORT_SIGNALS[sig]
        ts = simulate_short(cache[sym], btc_bear, fn, oos_s, oos_e, tp, sl, mom)
        out["short"][sid] = sum(t["pnl"] for t in ts)
    return out


def run():
    print("Phase Z: dynamic capital allocator backtest")
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
    oos_s = int(n_min * 0.7)
    oos_e = n_min

    bear_frac = btc_bear[oos_s:oos_e].mean()
    bull_frac = btc_long[oos_s:oos_e].mean()
    print(f"  OOS bars: {oos_e-oos_s}, bear regime: {bear_frac*100:.1f}%, bull regime: {bull_frac*100:.1f}%")

    pnls = collect_trades(LONG_SET, SHORT_SET, cache, btc_long, btc_bear, oos_s, oos_e)
    long_total = sum(pnls["long"].values())
    short_total = sum(pnls["short"].values())
    n_long = len(pnls["long"]); n_short = len(pnls["short"])

    print(f"\n  Long pool OOS net: ${long_total:+.0f} across {n_long} strategies")
    for sid, p in sorted(pnls["long"].items(), key=lambda x: -x[1]):
        print(f"    {sid:<16} ${p:+.0f}")
    print(f"\n  Short pool OOS net: ${short_total:+.0f} across {n_short} strategies")
    for sid, p in sorted(pnls["short"].items(), key=lambda x: -x[1]):
        print(f"    {sid:<16} ${p:+.0f}")

    # MODE A: each strategy $50 margin (current paper bot mode)
    # Total OOS net = sum of all (already what pnls represent — each used $50)
    mode_a_net = long_total + short_total
    mode_a_alloc = (n_long + n_short) * 50  # paper "simulated" capital = $650

    # MODE B: scale margins so total = $50.
    # long pool gets 70.3% (bull frac), short gets 29.7% (bear frac)
    # Each strategy in pool gets equal slice
    long_margin_b = (50 * (1-bear_frac)) / n_long if n_long else 0
    short_margin_b = (50 * bear_frac) / n_short if n_short else 0
    mode_b_net = (long_total / 50) * long_margin_b * n_long + (short_total / 50) * short_margin_b * n_short
    # simpler: scale by ratio
    mode_b_net = long_total * (1-bear_frac) + short_total * bear_frac

    # MODE C: dynamic — only top long active in bull, only top short active in bear
    # Approximation: assume best strategy per pool
    best_long = max(pnls["long"].values()) if pnls["long"] else 0
    best_short = max(pnls["short"].values()) if pnls["short"] else 0
    mode_c_net = best_long + best_short  # only top of each pool gets all $50

    # MODE D: dynamic-pool — bull: split $50 across long pool; bear: split $50 across short pool
    # Each long gets $50/n_long during bull, $0 otherwise; each short gets $50/n_short during bear
    # Per-strategy effective margin = $50 / pool_size only when its regime is on.
    # But our pnls already used $50 each, so we scale by 1/pool_size
    mode_d_net = long_total / n_long + short_total / n_short

    print(f"\n=== Allocation mode comparison (OOS) ===")
    print(f"  Mode A (each $50, paper):     net=${mode_a_net:+.0f}  capital=${mode_a_alloc}")
    print(f"  Mode B (split 70/30 always):  net=${mode_b_net:+.0f}  capital=$50")
    print(f"  Mode C (top-1 per pool dyn):  net=${mode_c_net:+.0f}  capital=$50")
    print(f"  Mode D (full pool dyn):       net=${mode_d_net:+.0f}  capital=$50")

    print(f"\n  Capital efficiency (return per $1 capital):")
    print(f"    A: {mode_a_net/mode_a_alloc:+.3f}")
    print(f"    B: {mode_b_net/50:+.3f}")
    print(f"    C: {mode_c_net/50:+.3f}")
    print(f"    D: {mode_d_net/50:+.3f}")

    best_mode = max([("A", mode_a_net/mode_a_alloc), ("B", mode_b_net/50),
                     ("C", mode_c_net/50), ("D", mode_d_net/50)], key=lambda x: x[1])
    print(f"\n  Best mode by ROI: {best_mode[0]} ({best_mode[1]:+.3f} per $1)")

    out_path = Path("quant_runtime/output/auto4h/phaseZ_dyn_alloc.json")
    with open(out_path, "w") as f:
        json.dump({
            "long_pnls": pnls["long"], "short_pnls": pnls["short"],
            "bear_frac": bear_frac, "bull_frac": bull_frac,
            "mode_a_net": mode_a_net, "mode_a_capital": mode_a_alloc,
            "mode_b_net": mode_b_net,
            "mode_c_net": mode_c_net,
            "mode_d_net": mode_d_net,
            "best_mode": best_mode[0],
        }, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
