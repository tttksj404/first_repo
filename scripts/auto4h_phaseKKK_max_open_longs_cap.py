#!/usr/bin/env python3
"""Phase KKK: Validate max_open_longs cap (Phase JJJ follow-up).

Phase JJJ found 7-long simultaneous + -20% wick = -$365 impact.
Phase KKK validates: does max_open_longs cap=5 mitigate this without
hurting baseline?

3 scenarios on the same 12.5mo timeline:
  S1: baseline (no cap)             ← reference
  S2: cap=5 longs (no shock)        ← does cap hurt PnL?
  S3: cap=5 longs + JJJ shock       ← does cap reduce shock impact?

Win criteria:
  S2 net ≥ S1 net × 0.95 (cap reduces ≤5% baseline PnL)
  S3 - S2 > S1_shock - S1 (cap reduces shock impact)
  ⇒ cap is a "free win" — implement in v14
"""
from __future__ import annotations
import sys, json
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def run():
    print("Phase KKK: max_open_longs cap validation (JJJ follow-up)")

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
    WICK_PCT = -0.20
    MAX_OPEN_LONGS_CAP = 5

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
    cache_base = {}
    for sym in universe:
        df = load_1h(sym)
        if df is None: continue
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache_base[sym] = ind
    btc_long = precompute_btc_regime(cache_base["BTCUSDT"])
    btc_bear = precompute_bear_regime(cache_base["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache_base.values())

    # Apply -20% wick at i_peak (will determine first via no-cap scan)
    def apply_wick(cache_dict, i_inj):
        new_cache = {}
        for sym in cache_dict:
            c = cache_dict[sym]
            new_low = c["low"].copy()
            new_close = c["close"].copy()
            if i_inj < len(new_low) and sym != "BTCUSDT":
                new_low[i_inj] = new_low[i_inj] * (1 + WICK_PCT)
                new_close[i_inj] = new_close[i_inj] * (1 + WICK_PCT * 0.5)
            new_cache[sym] = {**c, "low": new_low, "close": new_close}
        return new_cache

    # Serialized event simulator with optional cap
    def run_portfolio(cache, longs, shorts, max_longs=None):
        """
        Run all strategies in parallel, bar-by-bar. Apply max_longs cap:
        if a strategy wants to enter long but cap full, skip entry.
        Returns total net + per-strat trades.
        """
        # Per-strat state
        states = {}
        for sid, sig, sym, mom, tp, sl in longs:
            states[sid] = {"side": "long", "sig_fn": SIGNALS[sig], "sym": sym,
                           "mom": mom, "tp": tp, "sl": sl, "margin": LONG_M,
                           "in_pos": False, "entry_px": 0, "entry_idx": 0,
                           "last_exit": -1, "last_loss": -1, "trades": []}
        for sid, sig, sym, mom, tp, sl in shorts:
            states[sid] = {"side": "short", "sig_fn": ALL_SHORT[sig], "sym": sym,
                           "mom": mom, "tp": tp, "sl": sl, "margin": SHORT_M,
                           "in_pos": False, "entry_px": 0, "entry_idx": 0,
                           "last_exit": -1, "last_loss": -1, "trades": []}

        peak_open_longs = 0  # diagnostic

        for i in range(50, n_min):
            # 1. Process exits first (so freed slots can be reused)
            for sid, st in states.items():
                if not st["in_pos"]: continue
                ind = cache.get(st["sym"])
                if ind is None or i >= len(ind["close"]): continue
                hi = ind["high"][i]; lo = ind["low"][i]; cl = ind["close"][i]
                ep = st["entry_px"]
                if st["side"] == "long":
                    roe_lo = (lo / ep - 1) * LEVERAGE * 100
                    roe_hi = (hi / ep - 1) * LEVERAGE * 100
                    roe_cl = (cl / ep - 1) * LEVERAGE * 100
                else:
                    roe_lo = (ep / lo - 1) * LEVERAGE * 100
                    roe_hi = (ep / hi - 1) * LEVERAGE * 100
                    roe_cl = (ep / cl - 1) * LEVERAGE * 100
                exit_roe = None
                if st["side"] == "long":
                    if roe_lo <= LIQ_ROE: exit_roe = -100
                    elif roe_lo <= st["sl"]: exit_roe = st["sl"]
                    elif roe_hi >= st["tp"]: exit_roe = st["tp"]
                    elif (not st["sig_fn"](ind, i)) and roe_cl > 0: exit_roe = roe_cl
                else:
                    if roe_hi <= LIQ_ROE: exit_roe = -100
                    elif roe_hi <= st["sl"]: exit_roe = st["sl"]
                    elif roe_lo >= st["tp"]: exit_roe = st["tp"]
                    elif (not st["sig_fn"](ind, i)) and roe_cl > 0: exit_roe = roe_cl
                if exit_roe is not None:
                    hold = i - st["entry_idx"]
                    notional = st["margin"] * LEVERAGE
                    fee = notional * COST_RT
                    funding = notional * FUNDING_8H * (hold/8)
                    pnl = -st["margin"] - fee if exit_roe<=-100 else st["margin"]*(exit_roe/100) - fee - funding
                    st["trades"].append(pnl)
                    st["in_pos"] = False; st["last_exit"] = i
                    if pnl < 0: st["last_loss"] = i

            # 2. Count current open longs (after exits)
            cur_open_longs = sum(1 for st in states.values() if st["side"] == "long" and st["in_pos"])
            peak_open_longs = max(peak_open_longs, cur_open_longs)

            # 3. Process entries
            for sid, st in states.items():
                if st["in_pos"]: continue
                if st["last_exit"] >= 0 and (i - st["last_exit"]) < CD_E: continue
                if st["last_loss"] >= 0 and (i - st["last_loss"]) < CD_L: continue
                # Cap check
                if st["side"] == "long" and max_longs is not None and cur_open_longs >= max_longs:
                    continue
                ind = cache.get(st["sym"])
                if ind is None or i >= len(ind["close"]): continue
                gate = btc_long if st["side"] == "long" else btc_bear
                if i < len(gate) and not gate[i]: continue
                if st["side"] == "long":
                    if ind["mom24"][i] < st["mom"]: continue
                else:
                    if ind["mom24"][i] > st["mom"]: continue
                if not st["sig_fn"](ind, i): continue
                st["entry_px"] = ind["close"][i] * (1 + SLIP if st["side"]=="long" else 1 - SLIP)
                st["entry_idx"] = i; st["in_pos"] = True
                if st["side"] == "long": cur_open_longs += 1

        net = sum(sum(st["trades"]) for st in states.values())
        per_strat = {sid: sum(st["trades"]) for sid, st in states.items()}
        return net, per_strat, peak_open_longs

    # Find peak via no-cap baseline (for shock injection)
    print("\n  S0: scan for peak open-longs bar (uses Phase JJJ method) ...")
    open_count = defaultdict(int)
    # quick rebuild to find peak
    for sid, sig, sym, mom, tp, sl in LONG_SET:
        if sym not in cache_base: continue
        ind = cache_base[sym]
        in_pos = False; entry_px = 0; entry_idx = 0
        last_exit = -1; last_loss = -1
        for i in range(50, n_min):
            if not in_pos:
                if last_exit >= 0 and (i - last_exit) < CD_E: continue
                if last_loss >= 0 and (i - last_loss) < CD_L: continue
                if i < len(btc_long) and not btc_long[i]: continue
                if ind["mom24"][i] < mom: continue
                if not SIGNALS[sig](ind, i): continue
                entry_px = ind["close"][i] * (1 + SLIP)
                entry_idx = i; in_pos = True
            else:
                open_count[i] += 1
                hi = ind["high"][i]; lo = ind["low"][i]; cl = ind["close"][i]
                roe_lo = (lo / entry_px - 1) * LEVERAGE * 100
                roe_hi = (hi / entry_px - 1) * LEVERAGE * 100
                roe_cl = (cl / entry_px - 1) * LEVERAGE * 100
                exit_roe = None
                if roe_lo <= LIQ_ROE: exit_roe = -100
                elif roe_lo <= sl: exit_roe = sl
                elif roe_hi >= tp: exit_roe = tp
                elif (not SIGNALS[sig](ind, i)) and roe_cl > 0: exit_roe = roe_cl
                if exit_roe is not None:
                    hold = i - entry_idx
                    notional = LONG_M * LEVERAGE
                    fee = notional * COST_RT
                    funding = notional * FUNDING_8H * (hold/8)
                    pnl = -LONG_M-fee if exit_roe<=-100 else LONG_M*(exit_roe/100) - fee - funding
                    in_pos = False; last_exit = i
                    if pnl < 0: last_loss = i
    i_peak = max(open_count.items(), key=lambda x: x[1])[0]
    print(f"  Peak bar: {i_peak} (Phase JJJ found 8091, may differ here due to per-strat indep)")

    # Scenarios
    print("\n  S1: baseline (no cap, no shock) ...")
    s1_net, s1_per, s1_peak = run_portfolio(cache_base, LONG_SET, SHORT_SET, max_longs=None)
    print(f"     net=${s1_net:+.2f}, peak_simul_longs={s1_peak}")

    print("\n  S2: cap=5 longs (no shock) ...")
    s2_net, s2_per, s2_peak = run_portfolio(cache_base, LONG_SET, SHORT_SET, max_longs=MAX_OPEN_LONGS_CAP)
    print(f"     net=${s2_net:+.2f}, peak_simul_longs={s2_peak}")

    print(f"\n  S3: cap=5 longs + -20% wick at bar {i_peak} ...")
    cache_shock = apply_wick(cache_base, i_peak)
    s3_net, s3_per, s3_peak = run_portfolio(cache_shock, LONG_SET, SHORT_SET, max_longs=MAX_OPEN_LONGS_CAP)
    print(f"     net=${s3_net:+.2f}, peak_simul_longs={s3_peak}")

    print(f"\n  S4 (reference): no cap + shock at bar {i_peak} ...")
    s4_net, s4_per, s4_peak = run_portfolio(cache_shock, LONG_SET, SHORT_SET, max_longs=None)
    print(f"     net=${s4_net:+.2f}, peak_simul_longs={s4_peak}")

    print(f"\n=== Phase KKK summary ===")
    print(f"  S1 baseline (no cap, no shock):      ${s1_net:+.2f}")
    print(f"  S2 cap=5 (no shock):                  ${s2_net:+.2f}  (Δ vs S1: ${s2_net-s1_net:+.2f})")
    print(f"  S3 cap=5 + shock:                     ${s3_net:+.2f}  (Δ vs S2: ${s3_net-s2_net:+.2f}; vs S1: ${s3_net-s1_net:+.2f})")
    print(f"  S4 no-cap + shock:                    ${s4_net:+.2f}  (Δ vs S1: ${s4_net-s1_net:+.2f})")

    cap_baseline_cost = s1_net - s2_net
    cap_shock_savings = s3_net - s4_net
    pct_baseline = cap_baseline_cost / s1_net * 100 if s1_net else 0

    print(f"\n  Cost of cap on baseline:    ${cap_baseline_cost:+.2f} ({pct_baseline:+.1f}% of S1)")
    print(f"  Savings from cap in shock:  ${cap_shock_savings:+.2f}")

    if pct_baseline <= 5 and cap_shock_savings > 100:
        verdict = f"WIN — cap=5 reduces baseline only {pct_baseline:.1f}% but saves ${cap_shock_savings:.0f} in worst-case shock. Implement in v14."
    elif pct_baseline <= 5 and cap_shock_savings > 0:
        verdict = f"MARGINAL_WIN — cap=5 cheap (-{pct_baseline:.1f}%) but small shock benefit (${cap_shock_savings:+.0f})."
    elif cap_shock_savings > cap_baseline_cost * 5:
        verdict = f"WIN — cap=5 costs ${cap_baseline_cost:.0f} but saves ${cap_shock_savings:.0f} (5×+ leverage)."
    else:
        verdict = f"LOSS — cap=5 hurts baseline ${cap_baseline_cost:.0f}, only saves ${cap_shock_savings:.0f}."

    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseKKK_max_open_longs_cap.json")
    with open(out_path, "w") as f:
        json.dump({"S1_baseline": s1_net, "S2_cap_only": s2_net,
                   "S3_cap_shock": s3_net, "S4_shock_only": s4_net,
                   "cap_baseline_cost": cap_baseline_cost,
                   "cap_shock_savings": cap_shock_savings,
                   "i_peak": i_peak, "cap": MAX_OPEN_LONGS_CAP,
                   "verdict": verdict}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
