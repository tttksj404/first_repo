#!/usr/bin/env python3
"""Phase JJ: Black swan stress test v2 — NON-OVERLAPPING windows.

GPT-5.4 Round 3 비판: Phase X 의 worst 5 windows 가 같은 BTC crash 의 overlapping slices.
실제로는 1개 evt 를 5번 카운트한 셈. 비판 정당.

수정:
1. 7-day rolling DD 계산
2. min DD 윈도우 선택 후, 그 윈도우 ±7일 mask out (non-overlap)
3. 5개 distinct events 추출
4. link_atrexp_S 도 라인업에서 제외 (Round 2 drop 반영)
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
# link_atrexp_S DROPPED (Round 2 PF=194 artifact)
SHORT_SET = [
    ("eth_heikin_S", "short_heikin_cont", "ETHUSDT", -0.04, 80, -30),
    ("near_atrexp_S", "short_atr_expansion", "NEARUSDT", -0.02, 200, -40),
    ("sui_momobv_S", "short_momentum_obv", "SUIUSDT", -0.06, 200, -40),
    ("arb_rsi_S", "short_rsi_breakdown", "ARBUSDT", -0.02, 200, -40),
    ("dot_adx_S", "short_adx_trend_dn", "DOTUSDT", -0.02, 150, -35),
    ("link_adx_S", "short_adx_trend_dn", "LINKUSDT", -0.06, 200, -40),
]


def find_distinct_worst_weeks(btc_close, k=5, gap_days=14):
    """Non-overlapping: after each pick, mask ±gap_days around it."""
    n = len(btc_close)
    wk = 24*7
    gap = 24*gap_days
    # compute all 7d DDs
    dds = np.zeros(n)
    dds[:] = np.nan
    for i in range(wk, n):
        peak = btc_close[i-wk:i].max()
        trough = btc_close[i-wk:i].min()
        dds[i] = (trough/peak - 1) * 100
    masked = dds.copy()
    picks = []
    for _ in range(k):
        if np.all(np.isnan(masked)):
            break
        idx = int(np.nanargmin(masked))
        picks.append((idx, float(masked[idx])))
        # mask ±gap
        s = max(0, idx - gap); e = min(n, idx + gap)
        masked[s:e] = np.nan
    return picks


def trades_in_window(ind, btc, fn, win_s, win_e, tp, sl, mom, side="long"):
    if side == "long":
        return sim_long(ind, btc, fn, max(50, win_s), win_e, tp, sl, mom)
    return simulate_short(ind, btc, fn, max(50, win_s), win_e, tp, sl, mom)


def run():
    print("Phase JJ: black swan v2 — DISTINCT non-overlapping windows")
    universe = sorted(set([s[2] for s in LONG_SET] + [s[2] for s in SHORT_SET]) | {"BTCUSDT"})
    cache = {}
    for sym in universe:
        df = load_1h(sym)
        if df is None: continue
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_long = precompute_btc_regime(cache["BTCUSDT"])
    btc_bear = precompute_bear_regime(cache["BTCUSDT"])
    btc_close = cache["BTCUSDT"]["close"]
    n_min = min(len(c["close"]) for c in cache.values())

    distinct = find_distinct_worst_weeks(btc_close[:n_min], k=5, gap_days=14)
    wk = 24*7
    print(f"\n=== {len(distinct)} DISTINCT 7-day BTC drawdown windows (gap ≥14d) ===")
    print(f"{'end_idx':>8} {'dd%':>7}  approx_period")
    for end_idx, dd in distinct:
        pct_pos = end_idx / n_min
        print(f"{end_idx:>8} {dd:>+6.1f}%   ~{pct_pos*100:.0f}% of dataset")

    print(f"\n=== Per-window portfolio simulation (link_atrexp_S excluded) ===")
    summary = []
    for end_idx, dd in distinct:
        s = end_idx - wk
        e = end_idx
        long_pnl = 0.0; short_pnl = 0.0
        long_trades = 0; short_trades = 0
        long_losers = 0; short_losers = 0
        for sid, sig, sym, mom, tp, sl in LONG_SET:
            if sym not in cache: continue
            ts = trades_in_window(cache[sym], btc_long, SIGNALS[sig], s, e, tp, sl, mom, "long")
            for t in ts:
                long_pnl += t["pnl"]; long_trades += 1
                if t["pnl"] < 0: long_losers += 1
        for sid, sig, sym, mom, tp, sl in SHORT_SET:
            if sym not in cache: continue
            fn = ALL_SHORT_SIGNALS[sig]
            ts = trades_in_window(cache[sym], btc_bear, fn, s, e, tp, sl, mom, "short")
            for t in ts:
                short_pnl += t["pnl"]; short_trades += 1
                if t["pnl"] < 0: short_losers += 1
        net = long_pnl + short_pnl
        summary.append({
            "end_idx": end_idx, "btc_dd_pct": dd,
            "long_pnl": long_pnl, "long_trades": long_trades, "long_losers": long_losers,
            "short_pnl": short_pnl, "short_trades": short_trades, "short_losers": short_losers,
            "net_pnl": net,
        })
        print(f"  end_idx={end_idx} BTC_dd={dd:+.1f}%: "
              f"L=${long_pnl:+.0f}({long_trades}t,{long_losers}L) "
              f"S=${short_pnl:+.0f}({short_trades}t,{short_losers}L) "
              f"NET=${net:+.0f}")

    if summary:
        avg_net = float(np.mean([s["net_pnl"] for s in summary]))
        worst_net = min(s["net_pnl"] for s in summary)
        short_helped = sum(1 for s in summary if s["short_pnl"] > 0)
        long_pos = sum(1 for s in summary if s["long_pnl"] > 0)
        print(f"\n=== Black swan v2 summary ({len(summary)} distinct events) ===")
        print(f"  Avg portfolio PnL: ${avg_net:+.0f}")
        print(f"  Worst single event: ${worst_net:+.0f}")
        print(f"  Short side profitable in {short_helped}/{len(summary)} events")
        print(f"  Long side profitable in {long_pos}/{len(summary)} events")
        if worst_net > -150:
            verdict = "ROBUST — kill-switch never triggered ($-150 threshold)"
        elif worst_net > -300:
            verdict = "ACCEPTABLE — kill-switch triggers but recovers"
        else:
            verdict = "FRAGILE — single event could halt portfolio"
        print(f"  Verdict: {verdict}")
    else:
        avg_net = worst_net = 0.0; verdict = "INSUFFICIENT_DATA"

    out = Path("quant_runtime/output/auto4h/phaseJJ_blackswan_v2.json")
    with open(out, "w") as f:
        json.dump({"summary": summary, "avg_net": avg_net, "worst_net": worst_net,
                   "verdict": verdict, "n_distinct": len(summary)}, f, indent=2, default=str)
    print(f"\n[saved] {out}")


if __name__ == "__main__":
    run()
