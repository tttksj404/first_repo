#!/usr/bin/env python3
"""Phase QQQ: Promotion ladder with chop-aware (active-day) timer.

Phase OOO found chop regime fires 0 trades (43.9% of bars idle).
Phase NNN's fold4 stalled at S3 due to chop concentration in eval window.

This phase re-runs NNN but with v14 enhancement:
  promotion timer counts only ACTIVE bars (bull or bear), not calendar days.
  i.e., a 7d Stage 1 window = 7 × 24 active bars = 168 active hours.

If chop is 44%, this means actual elapsed calendar time per active 7d
≈ 7 / 0.56 ≈ 12.5 calendar days. Timer pauses during chop.

Expected: fold4 should now reach Stage 5 (or get further).
"""
from __future__ import annotations
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def run():
    print("Phase QQQ: Active-day (chop-aware) promotion-ladder timer simulation")

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

    btc_ts = raw_ts["BTCUSDT"]
    # Build per-bar active flag (True if bull or bear regime, False if chop)
    active_at_bar = []
    for i in range(n_min):
        bull = btc_long[i] if i < len(btc_long) else False
        bear = btc_bear[i] if i < len(btc_bear) else False
        active_at_bar.append(bull or bear)

    # Cumulative active-bars at each bar index (lookup)
    cum_active = [0] * n_min
    c = 0
    for i in range(n_min):
        if active_at_bar[i]: c += 1
        cum_active[i] = c

    # ts → bar lookup
    ts_to_bar = {int(btc_ts[i]): i for i in range(min(len(btc_ts), n_min))}
    bar_to_ts = {i: int(btc_ts[i]) for i in range(min(len(btc_ts), n_min))}

    def find_active_window_end_bar(start_bar, target_active_bars):
        """Find bar i such that cum_active[i] - cum_active[start_bar] >= target_active_bars."""
        if start_bar >= len(cum_active): return None
        target = cum_active[start_bar] + target_active_bars
        # binary search
        lo, hi = start_bar, len(cum_active) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if cum_active[mid] >= target: hi = mid
            else: lo = mid + 1
        if cum_active[lo] >= target: return lo
        return None

    def sim_collect(ind, ts_arr, gate, sig_fn, mom, tp, sl, side, margin):
        trades = []
        in_pos = False; entry_px = 0; entry_idx = 0; entry_ts = 0
        last_exit = -1; last_loss = -1
        for i in range(50, n_min):
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
                entry_idx = i; entry_ts = int(ts_arr[i]); in_pos = True
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
                    notional = margin * LEVERAGE
                    fee = notional * COST_RT
                    funding = notional * FUNDING_8H * (hold/8)
                    pnl = -margin-fee if exit_roe<=-100 else margin*(exit_roe/100) - fee - funding
                    trades.append((entry_ts, pnl))
                    in_pos = False; last_exit = i
                    if pnl < 0: last_loss = i
        return trades

    print("\n  Collecting trades...")
    all_trades = []
    for sid, sig, sym, mom, tp, sl in LONG_SET:
        if sym not in cache: continue
        ts = sim_collect(cache[sym], raw_ts[sym], btc_long, SIGNALS[sig], mom, tp, sl, "long", LONG_M)
        all_trades.extend(ts)
    for sid, sig, sym, mom, tp, sl in SHORT_SET:
        if sym not in cache: continue
        ts = sim_collect(cache[sym], raw_ts[sym], btc_bear, ALL_SHORT[sig], mom, tp, sl, "short", SHORT_M)
        all_trades.extend(ts)
    all_trades.sort()
    print(f"  Total trades: {len(all_trades)}")

    # STAGES (amended): (stage, active_days, min_n, min_wr, min_net_pct)
    # active_days = 7/14/21 — these now mean BAR-COUNT-based, not calendar
    STAGES = [
        (1, 7,   6, 0.35, -0.10),
        (2, 7,   9, 0.38, -0.05),
        (3, 14, 15, 0.40,  0.05),
        (4, 21, 29, 0.42,  0.10),
    ]

    def eval_stage_active(stage_idx, start_bar, all_trades_sorted):
        stage, win_d, min_n, min_wr, min_net = STAGES[stage_idx]
        target_active_bars = win_d * 24
        end_bar = find_active_window_end_bar(start_bar, target_active_bars)
        if end_bar is None: return None
        start_ts = bar_to_ts.get(start_bar, 0)
        end_ts = bar_to_ts.get(end_bar, 0)
        win_trades = [t for t in all_trades_sorted if start_ts <= t[0] < end_ts]
        n = len(win_trades)
        wins = sum(1 for _, p in win_trades if p > 0)
        wr = wins/n if n else 0
        net = sum(p for _, p in win_trades)
        net_pct = net / 50.0
        gates_pass = {"n": n >= min_n, "wr": wr >= min_wr, "net": net_pct >= min_net}
        n_fail = sum(1 for g in gates_pass.values() if not g)
        return {"n": n, "wr": wr*100, "net_pct": net_pct*100,
                "gates_pass": gates_pass, "n_fail": n_fail,
                "result": "promote" if n_fail == 0 else ("stay" if n_fail == 1 else "retreat"),
                "end_bar": end_bar, "end_ts": end_ts}

    # Run from 4 different start bars (matching NNN folds)
    if not all_trades: return
    ts_min = all_trades[0][0]
    ts_max = all_trades[-1][0]
    span_ms = ts_max - ts_min
    quarter = span_ms // 4
    fold_start_ts = [ts_min, ts_min + quarter, ts_min + 2*quarter, ts_min + int(2.5*quarter)]
    fold_labels = ["fold1", "fold2", "fold3", "fold4"]

    # Map start_ts → start_bar (find first bar with ts >= fold_start_ts)
    def ts_to_first_bar(t):
        for i in range(n_min):
            if int(btc_ts[i]) >= t: return i
        return n_min - 1

    print(f"\n  Simulating with active-day timer:\n")
    print(f"  {'fold':>5} {'cal_days_to_S5':>14} {'active_days_to_S5':>17} {'promotions':>11} {'stays':>6} {'retreats':>9} {'final_stage':>12}")
    print(f"  {'-'*5} {'-'*14} {'-'*17} {'-'*11} {'-'*6} {'-'*9} {'-'*12}")

    sim_results = []
    for label, start_ts in zip(fold_labels, fold_start_ts):
        start_bar = ts_to_first_bar(start_ts)
        cur_bar = start_bar
        cur_stage_idx = 0
        n_promo = 0; n_stays = 0; n_retreats = 0
        max_stage_reached = 1
        cal_days_to_s5 = None
        active_days_to_s5 = None
        iterations = 0
        max_active_bars_budget = 365 * 24  # equivalent to 365 active days
        while iterations < 1000:
            iterations += 1
            r = eval_stage_active(cur_stage_idx, cur_bar, all_trades)
            if r is None: break
            if r["result"] == "promote":
                n_promo += 1
                cur_stage_idx += 1
                if cur_stage_idx >= 4:
                    cal_days_to_s5 = (r["end_ts"] - start_ts) / 86400000
                    active_days_to_s5 = (cum_active[r["end_bar"]] - cum_active[start_bar]) / 24
                    max_stage_reached = 5
                    cur_bar = r["end_bar"]
                    break
                cur_bar = r["end_bar"]
                max_stage_reached = max(max_stage_reached, cur_stage_idx + 1)
            elif r["result"] == "stay":
                n_stays += 1
                cur_bar = r["end_bar"]
            else:
                n_retreats += 1
                if cur_stage_idx > 0: cur_stage_idx -= 1
                cur_bar = r["end_bar"]
            # active-bars budget cap
            if cum_active[cur_bar] - cum_active[start_bar] >= max_active_bars_budget: break
            if cur_bar >= n_min - 1: break

        final_t = bar_to_ts.get(cur_bar, ts_max)
        final_cal_d = (final_t - start_ts) / 86400000
        final_active_d = (cum_active[cur_bar] - cum_active[start_bar]) / 24
        cd_str = f"{cal_days_to_s5:>13.0f}d" if cal_days_to_s5 is not None else "          ----"
        ad_str = f"{active_days_to_s5:>16.0f}d" if active_days_to_s5 is not None else "             ----"
        final_stage = cur_stage_idx + 1 if cal_days_to_s5 is None else 5
        print(f"  {label:>5} {cd_str:>14} {ad_str:>17} {n_promo:>11} {n_stays:>6} {n_retreats:>9} {final_stage:>11}")
        sim_results.append({"fold": label,
                            "cal_days_to_s5": cal_days_to_s5,
                            "active_days_to_s5": active_days_to_s5,
                            "promotions": n_promo, "stays": n_stays, "retreats": n_retreats,
                            "max_stage": max_stage_reached, "final_stage": final_stage,
                            "final_cal_d": final_cal_d, "final_active_d": final_active_d})

    # Compare vs NNN (calendar timer)
    print(f"\n  Compare vs NNN (calendar timer):")
    print(f"  {'fold':>5} {'NNN cal_days':>14} {'QQQ cal_days':>14} {'NNN final':>10} {'QQQ final':>10}")
    print(f"  {'-'*5} {'-'*14} {'-'*14} {'-'*10} {'-'*10}")
    nnn_d2s5 = [63, 168, 77, None]  # from NNN run
    nnn_final = [5, 5, 5, 3]
    for i, label in enumerate(fold_labels):
        qqq = sim_results[i]
        nnn_str = f"{nnn_d2s5[i]:>13}d" if nnn_d2s5[i] is not None else "        ----"
        qqq_str = f"{qqq['cal_days_to_s5']:>13.0f}d" if qqq['cal_days_to_s5'] is not None else "        ----"
        print(f"  {label:>5} {nnn_str:>14} {qqq_str:>14} {nnn_final[i]:>10} {qqq['final_stage']:>10}")

    n_reached_qqq = sum(1 for r in sim_results if r["cal_days_to_s5"] is not None)
    n_reached_nnn = sum(1 for d in nnn_d2s5 if d is not None)

    print(f"\n  Summary: NNN calendar timer reached S5 in {n_reached_nnn}/4 folds")
    print(f"           QQQ active-day timer reached S5 in {n_reached_qqq}/4 folds")

    if n_reached_qqq > n_reached_nnn:
        verdict = f"v14 active-day timer IMPROVES outcome — {n_reached_qqq}/4 vs {n_reached_nnn}/4 folds reach S5. Fold 4 stall RESOLVED."
    elif n_reached_qqq == n_reached_nnn:
        verdict = f"v14 active-day timer EQUIVALENT — {n_reached_qqq}/4 folds reach S5 with both timers. Stall is in trade quality, not timer."
    else:
        verdict = f"v14 active-day timer WORSE — {n_reached_qqq}/4 folds vs {n_reached_nnn}/4. Don't implement."
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseQQQ_active_day_timer.json")
    with open(out_path, "w") as f:
        json.dump({"folds_qqq": sim_results,
                   "n_reached_qqq": n_reached_qqq,
                   "n_reached_nnn": n_reached_nnn,
                   "nnn_cal_days_ref": nnn_d2s5,
                   "verdict": verdict}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
