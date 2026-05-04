#!/usr/bin/env python3
"""Phase MMM: Rolling trade-rate distribution over time.

Phase LLL found stage gates infeasible (avg 9.2 trades/week, far below
≥20 required for Stage 1). But avg can mask variance — a 7d window in
high-vol bull regime might fire 18 trades, while a 7d window in chop
might fire 2.

This phase slides a rolling window (7d, 14d, 21d) across the entire
12.5mo history and computes the distribution of trade counts per window.

Output:
  - p10, p25, p50, p75, p90 of trade count per window
  - % of windows that would PASS each proposed gate
  - Concrete data-driven gate recommendation

Method: gather all (entry_ts) across all 13 strategies, sort by ts,
slide window, count entries falling in each window position.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import datetime as dt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def run():
    print("Phase MMM: Rolling trade-rate distribution (7d/14d/21d windows)")

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

    def collect_entry_ts(ind, ts_arr, gate, sig_fn, mom, tp, sl, side, margin):
        entries = []
        in_pos = False; entry_px = 0; entry_idx = 0
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
                entry_idx = i; in_pos = True
                entries.append(int(ts_arr[i]))
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
                    pnl_neg = exit_roe < 0
                    in_pos = False; last_exit = i
                    if pnl_neg: last_loss = i
        return entries

    print("\n  Collecting entry timestamps across 13 strategies...")
    all_ts = []
    for sid, sig, sym, mom, tp, sl in LONG_SET:
        if sym not in cache: continue
        ts_list = collect_entry_ts(cache[sym], raw_ts[sym], btc_long, SIGNALS[sig], mom, tp, sl, "long", LONG_M)
        all_ts.extend(ts_list)
    for sid, sig, sym, mom, tp, sl in SHORT_SET:
        if sym not in cache: continue
        ts_list = collect_entry_ts(cache[sym], raw_ts[sym], btc_bear, ALL_SHORT[sig], mom, tp, sl, "short", SHORT_M)
        all_ts.extend(ts_list)

    all_ts.sort()
    print(f"  Total entries: {len(all_ts)}")
    if not all_ts:
        print("  No entries — abort"); return

    ts_min = all_ts[0]
    ts_max = all_ts[-1]
    span_days = (ts_max - ts_min) / 86400000.0
    print(f"  Span: {span_days:.0f} days")

    def rolling_counts(ts_list, window_days, step_days=1):
        """Return list of trade counts per rolling window."""
        window_ms = window_days * 86400000
        step_ms = step_days * 86400000
        counts = []
        t_start = ts_list[0]
        t_end = ts_list[-1]
        cur = t_start
        i = 0
        while cur + window_ms <= t_end:
            window_end = cur + window_ms
            # advance i past start, count until window_end
            while i < len(ts_list) and ts_list[i] < cur:
                i += 1
            j = i
            cnt = 0
            while j < len(ts_list) and ts_list[j] < window_end:
                cnt += 1; j += 1
            counts.append(cnt)
            cur += step_ms
        return counts

    def percentile(arr, p):
        if not arr: return 0
        s = sorted(arr)
        k = (len(s) - 1) * p / 100
        lo = int(k); hi = min(lo + 1, len(s) - 1)
        return s[lo] + (s[hi] - s[lo]) * (k - lo)

    rows = []
    for win_d in [7, 14, 21]:
        cnts = rolling_counts(all_ts, win_d)
        if not cnts: continue
        p10 = percentile(cnts, 10)
        p25 = percentile(cnts, 25)
        p50 = percentile(cnts, 50)
        p75 = percentile(cnts, 75)
        p90 = percentile(cnts, 90)
        avg = sum(cnts) / len(cnts)
        mn = min(cnts); mx = max(cnts)
        rows.append({"window_days": win_d, "n_windows": len(cnts),
                     "p10": p10, "p25": p25, "p50": p50, "p75": p75, "p90": p90,
                     "avg": avg, "min": mn, "max": mx, "counts": cnts})

    print(f"\n  Rolling-window trade-count distribution:")
    print(f"  {'win':>4} {'n_w':>4} {'min':>4} {'p10':>5} {'p25':>5} {'p50':>5} {'avg':>6} {'p75':>5} {'p90':>5} {'max':>4}")
    print(f"  {'-'*4} {'-'*4} {'-'*4} {'-'*5} {'-'*5} {'-'*5} {'-'*6} {'-'*5} {'-'*5} {'-'*4}")
    for r in rows:
        print(f"  {r['window_days']:>3}d {r['n_windows']:>4} {r['min']:>4} {r['p10']:>5.1f} {r['p25']:>5.1f} {r['p50']:>5.1f} {r['avg']:>6.2f} {r['p75']:>5.1f} {r['p90']:>5.1f} {r['max']:>4}")

    # OWNER_MANUAL gates vs reality
    OM_GATES = [
        (1, 7, 20),
        (2, 7, 40),
        (3, 14, 80),
        (4, 21, 120),
        (5, 21, 120),
    ]
    print(f"\n  OWNER_MANUAL gate vs % windows hitting:")
    print(f"  {'stage':>5} {'win':>4} {'gate':>5} {'%hit':>6} {'verdict'}")
    om_results = []
    for stage, win, gate in OM_GATES:
        r = next(rr for rr in rows if rr["window_days"] == win)
        n_pass = sum(1 for c in r["counts"] if c >= gate)
        pct = n_pass / len(r["counts"]) * 100
        v = "PASS" if pct >= 50 else ("WEAK" if pct >= 20 else "FAIL")
        print(f"  S{stage:>3}  {win:>3}d  ≥{gate:>3} {pct:>5.1f}%  {v}")
        om_results.append({"stage": stage, "window_days": win, "gate": gate,
                           "pct_windows_pass": pct, "verdict": v})

    # Recommended gates: p25 (gate fires in 75% of windows -> realistic but not trivial)
    print(f"\n  Recommended gates (p25 = bot hits gate 75% of windows):")
    print(f"  {'stage':>5} {'win':>4} {'p25_gate':>9} {'old':>5}")
    rec_gates = []
    stage_to_win = {1: 7, 2: 7, 3: 14, 4: 21, 5: 21}
    for stage, win, old_gate in OM_GATES:
        r = next(rr for rr in rows if rr["window_days"] == win)
        new_gate = max(1, int(r["p25"]))
        # stage 2/4 should be > stage 1/3 — adjust
        if stage == 2: new_gate = max(new_gate, int(r["p50"]))
        if stage == 4 or stage == 5: new_gate = max(new_gate, int(r["p50"]))
        print(f"  S{stage:>3}  {win:>3}d  ≥{new_gate:>3}  (was ≥{old_gate})")
        rec_gates.append({"stage": stage, "window_days": win,
                          "recommended_gate": new_gate, "original_gate": old_gate})

    # Verdict
    n_om_pass = sum(1 for r in om_results if r["verdict"] == "PASS")
    n_om_fail = sum(1 for r in om_results if r["verdict"] == "FAIL")
    if n_om_pass >= 3:
        verdict = f"OWNER_MANUAL gates partially viable ({n_om_pass}/5 PASS) — selective amendment ok"
    elif n_om_fail == 5:
        verdict = f"OWNER_MANUAL gates UNIFORMLY UNREACHABLE ({n_om_fail}/5 FAIL) — full amendment required"
    else:
        verdict = f"OWNER_MANUAL gates marginal ({n_om_pass} PASS / {n_om_fail} FAIL) — amendment recommended"
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseMMM_rolling_trade_rate.json")
    # strip raw counts to keep file small
    rows_save = [{k: v for k, v in r.items() if k != "counts"} for r in rows]
    with open(out_path, "w") as f:
        json.dump({"window_distributions": rows_save,
                   "owner_manual_gate_results": om_results,
                   "recommended_gates": rec_gates,
                   "verdict": verdict,
                   "n_total_entries": len(all_ts),
                   "span_days": span_days}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
