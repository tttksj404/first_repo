#!/usr/bin/env python3
"""Phase VV: Short-side correlation matrix.

Concern: 6 shorts (eth/near/sui/arb/dot/link) all gated on btc_bear regime.
If they enter simultaneously on bear flips → cluster risk: portfolio loses
6× margin in single bad bear-trap reversal.

Measure:
  1. Pairwise PnL correlation across 4 historical folds
  2. Co-occupancy: % of bars where 2+ shorts are simultaneously open
  3. Worst simultaneous-loss day (all 6 in red same bar)

If max pairwise corr > 0.7 → cluster too tight, recommend cap.
If 4+ shorts open simultaneously > 5% of bars → reduce to 3 shorts.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv
from auto4h_phaseQ_short_side import SHORT_SIGNALS, precompute_bear_regime
from auto4h_phaseV_extra_shorts import EXTRA_SHORT_SIGNALS

ALL_SHORT = {**SHORT_SIGNALS, **EXTRA_SHORT_SIGNALS}

LEVERAGE = 10
MARGIN = 50.0
COST_RT = 0.0012
FUNDING_8H = 0.00012
SLIPPAGE_BPS = 8
LIQ_ROE = -95.0
COOLDOWN_EXIT = 12
COOLDOWN_LOSS = 24

SHORTS = [
    ("eth_heikin_S", "short_heikin_cont", "ETHUSDT", -0.04, 80, -30),
    ("near_atrexp_S", "short_atr_expansion", "NEARUSDT", -0.02, 200, -40),
    ("sui_momobv_S", "short_momentum_obv", "SUIUSDT", -0.06, 200, -40),
    ("arb_rsi_S", "short_rsi_breakdown", "ARBUSDT", -0.02, 200, -40),
    ("dot_adx_S", "short_adx_trend_dn", "DOTUSDT", -0.02, 150, -35),
    ("link_adx_S", "short_adx_trend_dn", "LINKUSDT", -0.06, 200, -40),
]


def sim_short_track(ind, gate, sig_fn, n_total, mom, tp, sl):
    """Returns occupancy[i] in {0,1} per bar AND realized pnl[i] (only at exit bars)."""
    occupancy = np.zeros(n_total, dtype=np.int8)
    pnl_arr = np.zeros(n_total, dtype=np.float64)
    in_pos = False; entry_px = 0; entry_idx = 0
    last_exit = -1; last_loss = -1
    slip = SLIPPAGE_BPS / 10000.0
    for i in range(50, n_total):
        if not in_pos:
            if last_exit >= 0 and (i - last_exit) < COOLDOWN_EXIT: continue
            if last_loss >= 0 and (i - last_loss) < COOLDOWN_LOSS: continue
            if i < len(gate) and not gate[i]: continue
            if ind["mom24"][i] > mom: continue
            if not sig_fn(ind, i): continue
            entry_px = ind["close"][i] * (1 - slip)
            entry_idx = i; in_pos = True; occupancy[i] = 1
        else:
            occupancy[i] = 1
            hi = ind["high"][i]; lo = ind["low"][i]; cl = ind["close"][i]
            roe_lo = (entry_px / lo - 1) * LEVERAGE * 100
            roe_hi = (entry_px / hi - 1) * LEVERAGE * 100
            roe_cl = (entry_px / cl - 1) * LEVERAGE * 100
            exit_roe = None
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
                pnl_arr[i] = pnl
                in_pos = False; last_exit = i
                if pnl < 0: last_loss = i
    return occupancy, pnl_arr


def run():
    print("Phase VV: short-side correlation matrix")
    universe = sorted(set([s[2] for s in SHORTS]) | {"BTCUSDT"})
    cache = {}
    for sym in universe:
        df = load_1h(sym)
        if df is None: continue
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_bear = precompute_bear_regime(cache["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache.values())

    occ_map = {}; pnl_map = {}
    for sid, sig, sym, mom, tp, sl in SHORTS:
        if sym not in cache: continue
        occ, pnl = sim_short_track(cache[sym], btc_bear, ALL_SHORT[sig], n_min, mom, tp, sl)
        occ_map[sid] = occ; pnl_map[sid] = pnl
        print(f"  {sid}: occupancy={occ.sum()}/{n_min} ({100*occ.sum()/n_min:.1f}%) pnl_events={int((pnl!=0).sum())}")

    sids = list(occ_map.keys())
    n_sids = len(sids)

    # Co-occupancy stats
    occ_stack = np.stack([occ_map[s] for s in sids])  # (n_sids, n_bars)
    concurrent_count = occ_stack.sum(axis=0)  # how many shorts open per bar
    pct_2plus = (concurrent_count >= 2).mean() * 100
    pct_3plus = (concurrent_count >= 3).mean() * 100
    pct_4plus = (concurrent_count >= 4).mean() * 100
    pct_all6 = (concurrent_count >= 6).mean() * 100
    max_concurrent = int(concurrent_count.max())

    print(f"\n=== Co-occupancy ===")
    print(f"  ≥2 shorts open: {pct_2plus:.1f}% of bars")
    print(f"  ≥3 shorts open: {pct_3plus:.1f}% of bars")
    print(f"  ≥4 shorts open: {pct_4plus:.1f}% of bars")
    print(f"  all 6 open:     {pct_all6:.1f}% of bars")
    print(f"  max concurrent: {max_concurrent}")

    # Pairwise PnL correlation (resampled to daily — 24h windows)
    daily_n = n_min // 24
    daily_pnl = {}
    for sid in sids:
        d = pnl_map[sid][:daily_n*24].reshape(daily_n, 24).sum(axis=1)
        daily_pnl[sid] = d
    print(f"\n=== Pairwise daily-PnL correlation ===")
    print("        " + " ".join([f"{s.split('_')[0][:5]:>6}" for s in sids]))
    corr_max_offdiag = 0.0
    corr_pairs = []
    for i, sa in enumerate(sids):
        row = [sa.split("_")[0][:5]]
        for j, sb in enumerate(sids):
            if i == j: row.append("  1.00")
            else:
                a = daily_pnl[sa]; b = daily_pnl[sb]
                if a.std() == 0 or b.std() == 0:
                    c = 0.0
                else:
                    c = float(np.corrcoef(a, b)[0,1])
                row.append(f"  {c:+.2f}")
                if i < j:
                    corr_pairs.append((sa, sb, c))
                    corr_max_offdiag = max(corr_max_offdiag, abs(c))
        print("  " + row[0] + ":" + " ".join(row[1:]))

    # Worst simultaneous-loss day
    daily_total = np.sum([daily_pnl[s] for s in sids], axis=0)
    worst_day_idx = int(np.argmin(daily_total))
    worst_day_pnl = float(daily_total[worst_day_idx])

    print(f"\n=== Cluster-loss extreme ===")
    print(f"  worst day net (all 6 shorts): ${worst_day_pnl:+.2f}")
    print(f"  max |corr| off-diagonal:      {corr_max_offdiag:+.2f}")

    if corr_max_offdiag > 0.7:
        verdict = f"CLUSTER — max corr {corr_max_offdiag:.2f} > 0.7. Cap shorts to 3."
    elif pct_4plus > 5:
        verdict = f"CO-OCCUPANCY — 4+ shorts open {pct_4plus:.1f}% > 5%. Reduce to 4."
    elif worst_day_pnl < -200:
        verdict = f"FRAGILE — worst day ${worst_day_pnl:+.0f}. Add per-side dollar cap."
    else:
        verdict = f"OK — max corr {corr_max_offdiag:.2f}, ≥4 open {pct_4plus:.1f}%, worst day ${worst_day_pnl:+.0f}."
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseVV_short_corr.json")
    with open(out_path, "w") as f:
        json.dump({
            "co_occupancy": {"pct_2plus": pct_2plus, "pct_3plus": pct_3plus,
                             "pct_4plus": pct_4plus, "pct_all6": pct_all6,
                             "max_concurrent": max_concurrent},
            "pairwise_corr": [{"a": a, "b": b, "corr": c} for a, b, c in corr_pairs],
            "max_corr_offdiag": corr_max_offdiag,
            "worst_day_pnl": worst_day_pnl,
            "verdict": verdict,
        }, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
