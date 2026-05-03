#!/usr/bin/env python3
"""Phase NNN: Promotion-ladder simulation with amended stage gates.

Phase MMM derived amended gates (S1≥6, S2≥9, S3≥15, S4≥29, S5≥29).
This phase walks the 12.5mo timeline and simulates the bot promoting
through stages, computing:
  - Days to reach Stage 5 from Stage 1
  - Number of stay/retreat events
  - 4 different start dates (WF-style robustness)

Stage capital factors (Mode B 70/30):
  Stage 1: $5  → 0.10 of Stage 5 ($50)
  Stage 2: $10 → 0.20
  Stage 3: $20 → 0.40
  Stage 4: $35 → 0.70
  Stage 5: $50 → 1.00

Gates evaluated per stage:
  S1: 7d  + ≥6  trades + WR≥35% + net≥-10% × stage_cap
  S2: 7d  + ≥9  trades + WR≥38% + net≥-5%  × stage_cap
  S3: 14d + ≥15 trades + WR≥40% + net≥+5%  × stage_cap
  S4: 21d + ≥29 trades + WR≥42% + net≥+10% × stage_cap
  S5: end-state. (debate ≥75 = manual, not simulated)

Retreat: 2+ gate fail → drop one stage.
Stay: 1 gate fail → next eval window.
Promote: all gates pass → advance.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import datetime as dt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def run():
    print("Phase NNN: Promotion-ladder simulation (amended gates)")

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

    def sim_collect(ind, ts_arr, gate, sig_fn, mom, tp, sl, side, margin):
        """Returns list of (entry_ts, pnl) tuples (pnl in Stage 5 dollars)."""
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

    print("\n  Collecting trades from 13 strategies...")
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
    if not all_trades:
        print("  No trades — abort"); return

    ts_min = all_trades[0][0]
    ts_max = all_trades[-1][0]
    span_days = (ts_max - ts_min) / 86400000.0
    print(f"  Span: {span_days:.0f} days")

    # Stage definitions (amended)
    # (stage, window_days, min_trades, min_wr_pct, min_net_pct, capital_factor)
    # capital_factor = stage_capital / 50 (since pnl was sim'd at LONG_M=35/SHORT_M=15 = $50 portfolio)
    # But the gate "net ≥ -10% × stage_capital" should compare to stage_capital, and pnl scales linearly.
    # So we just compare: pnl_in_window_at_stage_capital ≥ -0.10 × stage_capital
    # Simpler: convert pnl to %-of-stage by dividing by stage_capital. Since pnl scales linearly with capital,
    # pct_of_stage = pnl_at_stage5 / 50. So gate is: (sum_pnl / 50) ≥ -0.10 × (stage_cap / stage_cap) = -10%? No.
    # Let me re-derive: at any stage, sum_pnl_at_that_stage = sum_pnl_at_stage5 * (stage_cap / 50)
    # Gate: sum_pnl_at_that_stage ≥ -X% × stage_cap
    #     ↔ sum_pnl_at_stage5 * (stage_cap/50) ≥ -X% × stage_cap
    #     ↔ sum_pnl_at_stage5 / 50 ≥ -X%
    #     ↔ pnl_pct_of_50 ≥ -X%
    # So "net %" gate is just sum_pnl / 50, regardless of stage. Good — simplifies.

    STAGES = [
        # stage, window_days, min_n, min_wr, min_net_pct
        (1, 7,   6, 0.35, -0.10),
        (2, 7,   9, 0.38, -0.05),
        (3, 14, 15, 0.40,  0.05),
        (4, 21, 29, 0.42,  0.10),
    ]
    # Stage 5 is end-state (achieved when S4 promotes)

    def eval_stage(stage_idx, window_start_ts, trades_sorted):
        stage, win_d, min_n, min_wr, min_net = STAGES[stage_idx]
        win_ms = win_d * 86400000
        win_end = window_start_ts + win_ms
        window_trades = [t for t in trades_sorted if window_start_ts <= t[0] < win_end]
        n = len(window_trades)
        wins = sum(1 for _, p in window_trades if p > 0)
        wr = wins/n if n else 0
        net = sum(p for _, p in window_trades)
        net_pct = net / 50.0  # as fraction-of-Stage5

        gates_pass = {
            "n": n >= min_n,
            "wr": wr >= min_wr,
            "net": net_pct >= min_net,
        }
        n_fail = sum(1 for g in gates_pass.values() if not g)
        return {
            "n": n, "wr": wr*100, "net_pct": net_pct*100, "net_dollars_at_s5": net,
            "gates_pass": gates_pass, "n_fail": n_fail,
            "result": "promote" if n_fail == 0 else ("stay" if n_fail == 1 else "retreat"),
            "window_end": win_end,
        }

    # Run simulation from 4 different start points (WF-style)
    span_ms = ts_max - ts_min
    quarter = span_ms // 4
    starts = [ts_min, ts_min + quarter, ts_min + 2*quarter, ts_min + int(2.5*quarter)]
    start_labels = ["fold1 (start)", "fold2 (Q2)", "fold3 (Q3)", "fold4 (mid Q4)"]

    print(f"\n  Simulating promotion ladder from 4 start dates...\n")
    print(f"  {'start':>15} {'days_to_S5':>11} {'promotions':>11} {'stays':>6} {'retreats':>9} {'final_stage':>12} {'final_t_days':>13}")
    print(f"  {'-'*15} {'-'*11} {'-'*11} {'-'*6} {'-'*9} {'-'*12} {'-'*13}")

    sim_results = []
    for label, start_ts in zip(start_labels, starts):
        cur_stage_idx = 0  # 0..3 (Stage 1..4)
        max_stage_reached = 1
        cur_t = start_ts
        days_to_s5 = None
        n_promotions = 0
        n_stays = 0
        n_retreats = 0
        history = []
        # Cap at 365 days of simulation
        max_t = min(start_ts + 365*86400000, ts_max)
        iterations = 0
        while cur_t + STAGES[cur_stage_idx][1]*86400000 <= max_t and iterations < 1000:
            iterations += 1
            r = eval_stage(cur_stage_idx, cur_t, all_trades)
            history.append({"stage_idx": cur_stage_idx, "t": cur_t, **{k: v for k, v in r.items() if k != "gates_pass"}})
            if r["result"] == "promote":
                n_promotions += 1
                cur_stage_idx += 1
                if cur_stage_idx >= 4:
                    # Reached Stage 5
                    days_to_s5 = (r["window_end"] - start_ts) / 86400000
                    max_stage_reached = 5
                    break
                cur_t = r["window_end"]
                max_stage_reached = max(max_stage_reached, cur_stage_idx + 1)
            elif r["result"] == "stay":
                n_stays += 1
                cur_t = r["window_end"]  # advance window, retry
            else:  # retreat
                n_retreats += 1
                if cur_stage_idx > 0:
                    cur_stage_idx -= 1
                cur_t = r["window_end"]

        final_t_days = (cur_t - start_ts) / 86400000
        final_stage = cur_stage_idx + 1 if days_to_s5 is None else 5
        d2s5_str = f"{days_to_s5:>10.0f}d" if days_to_s5 is not None else "    ----"
        print(f"  {label:>15} {d2s5_str:>11} {n_promotions:>11} {n_stays:>6} {n_retreats:>9} {final_stage:>11} {final_t_days:>12.0f}d")
        sim_results.append({"start_label": label, "days_to_s5": days_to_s5,
                            "promotions": n_promotions, "stays": n_stays,
                            "retreats": n_retreats, "max_stage": max_stage_reached,
                            "final_stage": final_stage, "final_t_days": final_t_days})

    # Aggregate
    n_reached = sum(1 for r in sim_results if r["days_to_s5"] is not None)
    avg_d2s5 = sum(r["days_to_s5"] for r in sim_results if r["days_to_s5"] is not None) / max(n_reached, 1) if n_reached else None
    print(f"\n  Summary: {n_reached}/4 folds reached Stage 5")
    if avg_d2s5:
        print(f"  Avg days to Stage 5 (across reaching folds): {avg_d2s5:.0f}d")
    avg_retreats = sum(r["retreats"] for r in sim_results) / 4
    print(f"  Avg retreats per fold: {avg_retreats:.1f}")

    # Verdict
    if n_reached >= 3 and avg_retreats < 3:
        verdict = f"VIABLE — {n_reached}/4 folds reach Stage 5 in avg {avg_d2s5:.0f}d, retreats {avg_retreats:.1f}/fold."
    elif n_reached >= 2:
        verdict = f"MARGINAL — {n_reached}/4 folds reach Stage 5. Some start-dates may stall in chop regime."
    else:
        verdict = f"FAIL — only {n_reached}/4 folds reach Stage 5. Even amended gates too strict."
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseNNN_promotion_ladder.json")
    with open(out_path, "w") as f:
        json.dump({"folds": sim_results, "n_folds_reaching_s5": n_reached,
                   "avg_days_to_s5": avg_d2s5, "avg_retreats": avg_retreats,
                   "verdict": verdict, "amended_gates": [list(s) for s in STAGES]},
                  f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
