#!/usr/bin/env python3
"""Phase JJJ: Multi-symbol simultaneous correlated crash stress.

Phase JJ tested 5 non-overlapping historical black-swans (single-symbol).
Phase EEE found worst real day -$31.44 (6 simultaneous exits, natural cluster).
This phase tests SYNTHETIC worst-case: all alts drop -20% in 1 hour
while LONGs are simultaneously holding open positions.

Method:
1. Run baseline simulator → get list of (entry_idx, exit_idx) per strategy
2. For each hour i in cache, count open_long_positions at i
3. Pick i_max = bar with max simultaneous open longs
4. Inject -20% low_wick on ALL alt symbols at i_max
5. Re-simulate from scratch with the injection. Compare net + max DD.

Threshold:
  net_after > 0: SURVIVABLE
  net_after - net_before > -$200: ROBUST (impact bounded)
  Else: FRAGILE
"""
from __future__ import annotations
import sys, json
from pathlib import Path
from collections import defaultdict
import copy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def run():
    print("Phase JJJ: Multi-symbol simultaneous correlated crash (synthetic -20% wick)")

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
    WICK_PCT = -0.20  # -20% wick

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

    def sim_track_open(ind, gate, sig_fn, mom, tp, sl, side, margin, return_open_bars=False):
        """Simulate. If return_open_bars=True, return list of bar indices where pos was open."""
        trades = []
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
                    hold = i - entry_idx
                    notional = margin * LEVERAGE
                    fee = notional * COST_RT
                    funding = notional * FUNDING_8H * (hold/8)
                    pnl = -margin-fee if exit_roe<=-100 else margin*(exit_roe/100) - fee - funding
                    trades.append(pnl)
                    in_pos = False; last_exit = i
                    if pnl < 0: last_loss = i
        if return_open_bars:
            return trades, open_bars
        return trades

    # Phase 1: baseline + identify worst correlated bar (max simultaneous LONGS open)
    print("\n  Pass 1: baseline simulation + finding peak open-longs bar...")
    open_count = defaultdict(int)
    baseline_trades_per_strat = {}
    for sid, sig, sym, mom, tp, sl in LONG_SET:
        if sym not in cache_base: continue
        trades, open_bars = sim_track_open(cache_base[sym], btc_long, SIGNALS[sig], mom, tp, sl, "long", LONG_M, return_open_bars=True)
        baseline_trades_per_strat[sid] = trades
        for b in open_bars:
            open_count[b] += 1
    for sid, sig, sym, mom, tp, sl in SHORT_SET:
        if sym not in cache_base: continue
        trades = sim_track_open(cache_base[sym], btc_bear, ALL_SHORT[sig], mom, tp, sl, "short", SHORT_M)
        baseline_trades_per_strat[sid] = trades

    baseline_net = sum(sum(t) for t in baseline_trades_per_strat.values())
    print(f"  Baseline net: ${baseline_net:+.2f}")

    if not open_count:
        print("  No open positions ever — abort"); return

    # Find peak
    sorted_open = sorted(open_count.items(), key=lambda x: -x[1])
    i_peak = sorted_open[0][0]
    n_peak = sorted_open[0][1]
    print(f"  Peak simultaneous open longs: {n_peak} at bar {i_peak}")
    print(f"  Top-5 peak bars:")
    for b, n in sorted_open[:5]:
        print(f"    bar={b}  open_longs={n}")

    # Phase 2: inject -20% wick at i_peak across ALL alts (not BTC, since BTC is regime gate)
    print(f"\n  Pass 2: inject {WICK_PCT*100:+.0f}% wick at bar {i_peak} on all alts...")
    cache_shock = {}
    for sym in universe:
        if sym not in cache_base: continue
        c = cache_base[sym]
        # deep-copy only the arrays we modify
        new_low = c["low"].copy()
        new_close = c["close"].copy()
        new_high = c["high"].copy()
        if i_peak < len(new_low) and sym != "BTCUSDT":
            # inject wick: low drops -20%, close drops -10% (recovery half-way), high unchanged
            new_low[i_peak] = new_low[i_peak] * (1 + WICK_PCT)
            new_close[i_peak] = new_close[i_peak] * (1 + WICK_PCT * 0.5)
        cache_shock[sym] = {**c, "low": new_low, "close": new_close, "high": new_high}

    # Re-run regimes with shocked BTC (BTC unchanged, but BTC regime might shift due to alts irrelevant)
    # BTC regime gate uses BTC indicators only, unchanged. Just re-use.
    btc_long_shock = btc_long
    btc_bear_shock = btc_bear

    shock_trades_per_strat = {}
    for sid, sig, sym, mom, tp, sl in LONG_SET:
        if sym not in cache_shock: continue
        trades = sim_track_open(cache_shock[sym], btc_long_shock, SIGNALS[sig], mom, tp, sl, "long", LONG_M)
        shock_trades_per_strat[sid] = trades
    for sid, sig, sym, mom, tp, sl in SHORT_SET:
        if sym not in cache_shock: continue
        trades = sim_track_open(cache_shock[sym], btc_bear_shock, ALL_SHORT[sig], mom, tp, sl, "short", SHORT_M)
        shock_trades_per_strat[sid] = trades

    shock_net = sum(sum(t) for t in shock_trades_per_strat.values())
    delta = shock_net - baseline_net
    print(f"  Shocked net: ${shock_net:+.2f}  (Δ ${delta:+.2f} vs baseline)")

    # Per-strategy delta
    print(f"\n  Per-strategy impact (top 5 worst):")
    deltas = []
    for sid in baseline_trades_per_strat:
        b = sum(baseline_trades_per_strat[sid])
        s = sum(shock_trades_per_strat.get(sid, []))
        deltas.append((sid, s - b, b, s))
    deltas.sort(key=lambda x: x[1])
    for sid, d, b, s in deltas[:5]:
        print(f"    {sid:<18}  base ${b:+.2f}  shock ${s:+.2f}  Δ ${d:+.2f}")

    if shock_net > 0:
        if delta > -200:
            verdict = f"ROBUST — survives -20% multi-alt wick. shock={shock_net:+.2f} (Δ {delta:+.2f}), still profitable."
        elif delta > -500:
            verdict = f"SURVIVABLE — shock={shock_net:+.2f} but Δ {delta:+.2f} is large. Stage 5 risk noted."
        else:
            verdict = f"WOUNDED — shock={shock_net:+.2f}, Δ {delta:+.2f} severe. Re-evaluate sizing."
    else:
        verdict = f"FRAGILE — shock loses money: {shock_net:+.2f}. Bot needs flash-crash circuit-breaker."

    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseJJJ_correlated_crash.json")
    with open(out_path, "w") as f:
        json.dump({"baseline_net": baseline_net, "shock_net": shock_net,
                   "delta": delta, "wick_pct": WICK_PCT,
                   "i_peak": i_peak, "n_peak_open_longs": n_peak,
                   "per_strat_delta": [{"sid": sid, "delta": d, "base": b, "shock": s}
                                       for sid, d, b, s in deltas],
                   "verdict": verdict}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
