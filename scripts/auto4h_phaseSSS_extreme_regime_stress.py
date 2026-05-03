#!/usr/bin/env python3
"""Phase SSS: Extreme regime sub-period stress.

We've tested across normal regime mix. This phase finds the EXTREME
30-day sub-periods in our 12.5mo data:
  - max BTC up-move 30d (extreme bull)
  - max BTC down-move 30d (extreme bear)
  - min BTC range 30d (extreme chop)

For each, compute Stage 1 P&L. Confirms bot survives all regime extremes.

Threshold:
  All 3 extreme periods positive (or break-even): ROBUST
  Any one negative > -10% of capital: STRESS RISK
"""
from __future__ import annotations
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def run():
    print("Phase SSS: Extreme regime sub-period stress test")

    from quant_rotation_engine import load_1h, compute_indicators
    from quant_phase15_signal_library import add_extra_features
    from quant_phase16_robustness import add_obv
    from auto4h_signal_library import SIGNALS
    from auto4h_phaseQ_short_side import SHORT_SIGNALS, precompute_bear_regime
    from auto4h_phaseV_extra_shorts import EXTRA_SHORT_SIGNALS
    from auto4h_stage1_matrix import precompute_btc_regime
    ALL_SHORT = {**SHORT_SIGNALS, **EXTRA_SHORT_SIGNALS}

    LEVERAGE = 10; LONG_M = 35.0; SHORT_M = 15.0
    COST_RT = 0.0012; FUNDING_8H = 0.00012; SLIP = 0.0008
    LIQ_ROE = -95.0; CD_E = 12; CD_L = 24

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

    universe = sorted(set([s[2] for s in LONG_SET] + [s[2] for s in SHORT_SET]) | {"BTCUSDT"})
    cache = {}
    raw_ts = {}
    for sym in universe:
        df = load_1h(sym)
        if df is None: continue
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
        raw_ts[sym] = df[:, 0]
    btc_long = precompute_btc_regime(cache["BTCUSDT"])
    btc_bear = precompute_bear_regime(cache["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache.values())

    # Find extreme 30d periods in BTC data
    btc_close = cache["BTCUSDT"]["close"]
    btc_high = cache["BTCUSDT"]["high"]
    btc_low = cache["BTCUSDT"]["low"]
    btc_ts = raw_ts["BTCUSDT"]

    WIN_HOURS = 30 * 24

    print("\n  Scanning for extreme 30d BTC regimes...")
    max_up_pct = -1e9; max_up_start = 0
    max_dn_pct = 1e9; max_dn_start = 0
    min_range_pct = 1e9; min_range_start = 0

    for i in range(50, n_min - WIN_HOURS):
        st = btc_close[i]; en = btc_close[i + WIN_HOURS]
        if st <= 0: continue
        chg = (en / st - 1) * 100
        # range over window
        win_hi = max(btc_high[i:i+WIN_HOURS])
        win_lo = min(btc_low[i:i+WIN_HOURS])
        rng = (win_hi / win_lo - 1) * 100 if win_lo > 0 else 0

        if chg > max_up_pct:
            max_up_pct = chg; max_up_start = i
        if chg < max_dn_pct:
            max_dn_pct = chg; max_dn_start = i
        if rng < min_range_pct and rng > 0:
            min_range_pct = rng; min_range_start = i

    print(f"  Extreme BULL  30d: BTC {max_up_pct:+.1f}% (bar {max_up_start})")
    print(f"  Extreme BEAR  30d: BTC {max_dn_pct:+.1f}% (bar {max_dn_start})")
    print(f"  Extreme CHOP  30d: BTC range only {min_range_pct:.1f}% (bar {min_range_start})")

    def sim_window(start_bar, end_bar, ind, gate, sig_fn, mom, tp, sl, side, margin):
        trades = []
        in_pos = False; entry_px = 0; entry_idx = 0
        last_exit = -1; last_loss = -1
        for i in range(max(50, start_bar), min(end_bar, n_min)):
            if not in_pos:
                if last_exit >= 0 and (i - last_exit) < CD_E: continue
                if last_loss >= 0 and (i - last_loss) < CD_L: continue
                if i < len(gate) and not gate[i]: continue
                if side == "long":
                    if ind["mom24"][i] < mom: continue
                else:
                    if ind["mom24"][i] > mom: continue
                if not sig_fn(ind, i): continue
                entry_px = ind["close"][i] * (1 + SLIP if side=="long" else 1 - SLIP)
                entry_idx = i; in_pos = True
            else:
                hi_ = ind["high"][i]; lo_ = ind["low"][i]; cl_ = ind["close"][i]
                if side == "long":
                    roe_lo = (lo_ / entry_px - 1) * LEVERAGE * 100
                    roe_hi = (hi_ / entry_px - 1) * LEVERAGE * 100
                    roe_cl = (cl_ / entry_px - 1) * LEVERAGE * 100
                else:
                    roe_lo = (entry_px / lo_ - 1) * LEVERAGE * 100
                    roe_hi = (entry_px / hi_ - 1) * LEVERAGE * 100
                    roe_cl = (entry_px / cl_ - 1) * LEVERAGE * 100
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
                    notional = margin * LEVERAGE
                    fee = notional * COST_RT
                    funding = notional * FUNDING_8H * (hold/8)
                    pnl = -margin-fee if exit_roe<=-100 else margin*(exit_roe/100) - fee - funding
                    trades.append(pnl)
                    in_pos = False; last_exit = i
                    if pnl < 0: last_loss = i
        return trades

    S1_FACTOR = 0.0539
    STAGE1_CAP = 5.0

    def portfolio_window_pnl(start_bar):
        end_bar = start_bar + WIN_HOURS
        all_trades = []
        for sid, sig, sym, mom, tp, sl in LONG_SET:
            if sym not in cache: continue
            t = sim_window(start_bar, end_bar, cache[sym], btc_long, SIGNALS[sig], mom, tp, sl, "long", LONG_M)
            all_trades.extend(t)
        for sid, sig, sym, mom, tp, sl in SHORT_SET:
            if sym not in cache: continue
            t = sim_window(start_bar, end_bar, cache[sym], btc_bear, ALL_SHORT[sig], mom, tp, sl, "short", SHORT_M)
            all_trades.extend(t)
        return all_trades

    print(f"\n  Running 13-strategy portfolio in each extreme window...\n")
    print(f"  {'regime':<14} {'BTC chg':>9} {'n_trades':>9} {'S5_pnl':>9} {'S1_pnl':>9} {'%cap':>6} {'WR%':>5}")
    print(f"  {'-'*14} {'-'*9} {'-'*9} {'-'*9} {'-'*9} {'-'*6} {'-'*5}")

    extremes = [
        ("Extreme BULL", max_up_pct, max_up_start),
        ("Extreme BEAR", max_dn_pct, max_dn_start),
        ("Extreme CHOP", min_range_pct, min_range_start),
    ]
    results = []
    for name, btc_chg, start in extremes:
        trades = portfolio_window_pnl(start)
        n = len(trades)
        s5_pnl = sum(trades)
        s1_pnl = s5_pnl * S1_FACTOR
        pct_cap = s1_pnl / STAGE1_CAP * 100
        wins = sum(1 for t in trades if t > 0)
        wr = wins/n*100 if n else 0
        print(f"  {name:<14} {btc_chg:>+8.1f}% {n:>9} ${s5_pnl:>+7.2f} ${s1_pnl:>+7.3f} {pct_cap:>+5.1f}% {wr:>4.1f}%")
        results.append({"regime": name, "btc_chg_pct": btc_chg, "n_trades": n,
                        "s5_pnl": s5_pnl, "s1_pnl": s1_pnl, "pct_capital": pct_cap,
                        "wr": wr, "start_bar": start})

    # Compare to baseline avg 30d
    baseline_avg_s1 = 4.89  # from PPP
    print(f"\n  Baseline avg 30d (Phase PPP): ${baseline_avg_s1:+.2f}/30d ({baseline_avg_s1/STAGE1_CAP*100:+.1f}%)")
    print(f"\n  Delta vs baseline:")
    for r in results:
        d = r["s1_pnl"] - baseline_avg_s1
        print(f"    {r['regime']:<14} ${r['s1_pnl']:+.2f} (Δ ${d:+.2f} vs avg)")

    # Verdict
    n_pos = sum(1 for r in results if r["s1_pnl"] > 0)
    worst = min(r["s1_pnl"] for r in results)
    worst_pct = worst / STAGE1_CAP * 100
    if n_pos == 3:
        verdict = f"ROBUST — all 3 extreme regimes profitable. worst = ${worst:+.2f} ({worst_pct:+.1f}%)."
    elif n_pos == 2 and worst_pct > -20:
        verdict = f"MOSTLY ROBUST — 2/3 extremes profit, worst ${worst:+.2f} ({worst_pct:+.1f}%) bounded."
    elif worst_pct > -30:
        verdict = f"VULNERABLE — worst extreme ${worst:+.2f} ({worst_pct:+.1f}%) painful but not ruinous."
    else:
        verdict = f"FRAGILE — worst extreme ${worst:+.2f} ({worst_pct:+.1f}%) unacceptable. Need extreme-regime circuit breaker."
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseSSS_extreme_regime_stress.json")
    with open(out_path, "w") as f:
        json.dump({"results": results, "n_positive": n_pos,
                   "worst_s1_pnl": worst, "worst_pct_capital": worst_pct,
                   "baseline_avg_30d_s1": baseline_avg_s1,
                   "verdict": verdict}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
