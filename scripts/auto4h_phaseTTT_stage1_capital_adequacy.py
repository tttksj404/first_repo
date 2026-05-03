#!/usr/bin/env python3
"""Phase TTT: Stage 1 capital adequacy check.

At Stage 1 with $5 capital total:
  - Per-strategy long margin = $3.5 / 7 longs = $0.50 per long
  - Per-strategy short margin = $1.5 / 6 shorts = $0.25 per short

But Bitget perpetual minimum order:
  - Most pairs: ~$5 notional minimum
  - At 5x lev, $0.50 margin = $2.50 notional → REJECTED
  - At 5x lev, $0.25 margin = $1.25 notional → REJECTED

Two interpretations of OWNER_MANUAL:
  (A) $5 = TOTAL capital (split across strategies) → most positions REJECTED
  (B) $5 = PER-STRATEGY budget × 13 strategies = $65 total → works fine

Phase TTT verifies which interpretation is operationally viable:
  1. Compute simultaneous open margin requirement (peak across 12.5mo)
  2. Compare to Bitget min notional per pair
  3. Recommend Stage 1 capital model

Method:
  - Run portfolio sim
  - Track simultaneous open positions per bar
  - For each open position: compute margin (Stage 1 scale) and notional
  - Check Bitget min notional ($5 typical)
  - Report % of bars where ALL positions valid vs. some rejected
"""
from __future__ import annotations
import sys, json
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def run():
    print("Phase TTT: Stage 1 capital adequacy + min-notional check")

    from quant_rotation_engine import load_1h, compute_indicators
    from quant_phase15_signal_library import add_extra_features
    from quant_phase16_robustness import add_obv
    from auto4h_signal_library import SIGNALS
    from auto4h_phaseQ_short_side import SHORT_SIGNALS, precompute_bear_regime
    from auto4h_phaseV_extra_shorts import EXTRA_SHORT_SIGNALS
    from auto4h_stage1_matrix import precompute_btc_regime
    ALL_SHORT = {**SHORT_SIGNALS, **EXTRA_SHORT_SIGNALS}

    # Stage 1 config (5x lev, $5 total capital)
    STAGE1_CAP = 5.0
    STAGE1_LEV = 5
    LONG_PCT = 0.70  # 70% to longs
    SHORT_PCT = 0.30
    N_LONGS = 7
    N_SHORTS = 6

    # Bitget perpetual min notional (typical, conservative)
    # PEPE/WIF often $5+, others ~$1-5. Use $5 as worst case.
    MIN_NOTIONAL_USD = 5.0

    # Interpretation A: $5 total split across all strategies
    long_margin_A = STAGE1_CAP * LONG_PCT / N_LONGS  # $0.50
    short_margin_A = STAGE1_CAP * SHORT_PCT / N_SHORTS  # $0.25
    long_notional_A = long_margin_A * STAGE1_LEV  # $2.50
    short_notional_A = short_margin_A * STAGE1_LEV  # $1.25

    # Interpretation B: $5 per strategy (×13 = $65 total)
    long_margin_B = STAGE1_CAP * LONG_PCT  # $3.50
    short_margin_B = STAGE1_CAP * SHORT_PCT  # $1.50
    long_notional_B = long_margin_B * STAGE1_LEV  # $17.50
    short_notional_B = short_margin_B * STAGE1_LEV  # $7.50

    print(f"\n  Interpretation A: $5 = TOTAL capital")
    print(f"    long  margin/strat = ${long_margin_A:.3f}, notional = ${long_notional_A:.2f}  {'OK' if long_notional_A >= MIN_NOTIONAL_USD else 'REJECTED <$5'}")
    print(f"    short margin/strat = ${short_margin_A:.3f}, notional = ${short_notional_A:.2f}  {'OK' if short_notional_A >= MIN_NOTIONAL_USD else 'REJECTED <$5'}")
    print(f"\n  Interpretation B: $5 per strategy ($65 total)")
    print(f"    long  margin/strat = ${long_margin_B:.3f}, notional = ${long_notional_B:.2f}  {'OK' if long_notional_B >= MIN_NOTIONAL_USD else 'REJECTED <$5'}")
    print(f"    short margin/strat = ${short_margin_B:.3f}, notional = ${short_notional_B:.2f}  {'OK' if short_notional_B >= MIN_NOTIONAL_USD else 'REJECTED <$5'}")

    # Simulate portfolio + track simultaneous open positions
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
    for sym in universe:
        df = load_1h(sym)
        if df is None: continue
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_long = precompute_btc_regime(cache["BTCUSDT"])
    btc_bear = precompute_bear_regime(cache["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache.values())

    def sim_track(ind, gate, sig_fn, mom, tp, sl, side, margin):
        open_bars = []
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
            else:
                open_bars.append(i)
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
                    in_pos = False; last_exit = i
                    if exit_roe < 0: last_loss = i
        return open_bars

    print("\n  Tracking simultaneous open positions across portfolio...")
    open_count_long = defaultdict(int)
    open_count_short = defaultdict(int)
    for sid, sig, sym, mom, tp, sl in LONG_SET:
        if sym not in cache: continue
        bars = sim_track(cache[sym], btc_long, SIGNALS[sig], mom, tp, sl, "long", LONG_M)
        for b in bars: open_count_long[b] += 1
    for sid, sig, sym, mom, tp, sl in SHORT_SET:
        if sym not in cache: continue
        bars = sim_track(cache[sym], btc_bear, ALL_SHORT[sig], mom, tp, sl, "short", SHORT_M)
        for b in bars: open_count_short[b] += 1

    # Histograms
    long_dist = defaultdict(int)
    short_dist = defaultdict(int)
    total_dist = defaultdict(int)
    for b in range(n_min):
        l = open_count_long.get(b, 0)
        s = open_count_short.get(b, 0)
        long_dist[l] += 1
        short_dist[s] += 1
        total_dist[l + s] += 1

    print(f"\n  Simultaneous OPEN LONGS distribution (across all bars):")
    for n in sorted(long_dist.keys()):
        pct = long_dist[n] / n_min * 100
        print(f"    {n} longs open: {long_dist[n]:>5} bars ({pct:>5.1f}%)")
    max_longs = max(long_dist.keys())

    print(f"\n  Simultaneous OPEN SHORTS distribution:")
    for n in sorted(short_dist.keys()):
        pct = short_dist[n] / n_min * 100
        print(f"    {n} shorts open: {short_dist[n]:>5} bars ({pct:>5.1f}%)")
    max_shorts = max(short_dist.keys())

    print(f"\n  Simultaneous TOTAL OPEN distribution:")
    for n in sorted(total_dist.keys()):
        pct = total_dist[n] / n_min * 100
        print(f"    {n} total open: {total_dist[n]:>5} bars ({pct:>5.1f}%)")
    max_total = max(total_dist.keys())

    # Capital requirement at peak (Interpretation B: $5 per strategy)
    # Peak long margin = max_longs × long_margin_B = max_longs × $3.5
    # Peak short margin = max_shorts × short_margin_B = max_shorts × $1.5
    peak_long_margin_B = max_longs * long_margin_B
    peak_short_margin_B = max_shorts * short_margin_B
    peak_total_margin_B = peak_long_margin_B + peak_short_margin_B

    print(f"\n  ==== Interpretation B ($5 per strategy = $65 total) ====")
    print(f"    Peak simultaneous longs:  {max_longs} → margin needed ${peak_long_margin_B:.2f}")
    print(f"    Peak simultaneous shorts: {max_shorts} → margin needed ${peak_short_margin_B:.2f}")
    print(f"    Peak TOTAL margin:        ${peak_total_margin_B:.2f}")
    print(f"    Stage 1 budget if interpretation B: $65 total ($35 long + $15 short × {N_LONGS} long $35 + ... = no, $5×7 + $5×6 = $65)")
    # Actually interpretation B: each strategy gets $5, but only WHEN it fires.
    # The pool can be $65 OR a smaller "active pool" of e.g. $25 if max 5 strategies open.
    # In practice: operator allocates $25 (peak) → enough for max 5 longs + 4 shorts simultaneous.

    # Compute "minimum operating capital" = peak_total_margin
    print(f"\n  Recommended Stage 1 minimum operating capital:")
    print(f"    Peak required: ${peak_total_margin_B:.2f}")
    print(f"    Conservative (1.5× buffer): ${peak_total_margin_B * 1.5:.2f}")

    # Compare interpretation A
    print(f"\n  ==== Interpretation A ($5 TOTAL across strategies) ====")
    print(f"    Per-strategy long notional ${long_notional_A:.2f} < ${MIN_NOTIONAL_USD} min → INFEASIBLE")
    print(f"    Per-strategy short notional ${short_notional_A:.2f} < ${MIN_NOTIONAL_USD} min → INFEASIBLE")

    # Verdict
    if long_notional_A < MIN_NOTIONAL_USD:
        verdict_A = f"INFEASIBLE — Stage 1 longs notional ${long_notional_A:.2f} < ${MIN_NOTIONAL_USD} Bitget min."
    else:
        verdict_A = f"VIABLE"

    rec_capital = round(peak_total_margin_B * 1.5)
    verdict = (f"Interpretation A ($5 total) {verdict_A}.\n"
               f"   Interpretation B viable but requires ${peak_total_margin_B:.0f} peak (${rec_capital} recommended). "
               f"OWNER_MANUAL §0 'Stage 1: $5 capital' must be clarified — likely means $5 PER strategy, "
               f"so total operating budget = ~${rec_capital}.")
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseTTT_stage1_capital_adequacy.json")
    with open(out_path, "w") as f:
        json.dump({"interpretation_A": {
                       "total_capital": STAGE1_CAP,
                       "long_margin_per_strat": long_margin_A,
                       "long_notional": long_notional_A,
                       "short_margin_per_strat": short_margin_A,
                       "short_notional": short_notional_A,
                       "viable": long_notional_A >= MIN_NOTIONAL_USD,
                   },
                   "interpretation_B": {
                       "per_strat_capital": STAGE1_CAP,
                       "long_margin": long_margin_B,
                       "long_notional": long_notional_B,
                       "short_margin": short_margin_B,
                       "short_notional": short_notional_B,
                       "n_longs": N_LONGS, "n_shorts": N_SHORTS,
                       "max_total_pool": (LONG_M + SHORT_M) * STAGE1_CAP / 50,  # scaled
                       "viable": long_notional_B >= MIN_NOTIONAL_USD,
                   },
                   "open_position_distribution": {
                       "max_longs_simultaneous": max_longs,
                       "max_shorts_simultaneous": max_shorts,
                       "max_total_simultaneous": max_total,
                   },
                   "stage1_recommended_operating_capital": rec_capital,
                   "peak_required_capital": peak_total_margin_B,
                   "verdict": verdict}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
