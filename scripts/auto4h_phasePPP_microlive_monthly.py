#!/usr/bin/env python3
"""Phase PPP: Stage-1 micro-live monthly P&L distribution.

Operator-facing question: "If I put $5 in at Stage 1 for one month,
what's the realistic P&L distribution? Worst case? Best case?"

Method:
  1. Collect all (entry_ts, pnl_at_stage5) trades from production portfolio.
  2. Slide a 30-day rolling window across 12.5mo.
  3. For each window, scale pnl × (5/50) = 0.10 (Stage 1 capital factor).
  4. Compute distribution: mean, median, p5/p25/p75/p95, worst, best.
  5. Compute % of windows with positive return, % with > +10%, % with < -10%.

Stage 1 gate context:
  - capital = $5
  - lev = 5x (vs production sim's 10x → returns ÷ 2)
  - 7d gate ≥ -10% net = -$0.50 abs minimum
  - But operator runs for ~30d before evaluating, so we report 30d windows.

Caveat: production sim used LEVERAGE=10. Stage 1 uses 5x → halve pnl
(since pnl = margin * roe% / 100, roe = price_chg × lev × 100, so pnl
∝ leverage at fixed margin). Apply 0.5 multiplier.
"""
from __future__ import annotations
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def run():
    print("Phase PPP: Stage-1 micro-live monthly P&L distribution")

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

    if not all_trades:
        print("  No trades — abort"); return

    # Stage 1 conversion: capital $5 (vs $50), lev 5x (vs 10x)
    # pnl_s1 = pnl_s5 × (5/50) × (5/10) = pnl_s5 × 0.05
    # Wait: pnl_s5 = margin_s5 × roe_s5 / 100, roe_s5 = price_chg × 10
    # pnl_s1 = margin_s1 × roe_s1 / 100, roe_s1 = price_chg × 5
    # pnl_s1 / pnl_s5 = (margin_s1 / margin_s5) × (roe_s1 / roe_s5) = (5/50) × (5/10) = 0.05
    # Hmm but that ignores TP/SL not getting hit at low lev (price needs to move 2x further).
    # Conservative approximation: assume same trades fire (small hit-rate change), scale pnl × 0.05
    # The leverage-curve Phase LLL showed at 5x: 81.3% WR, 493 trades, $+548
    # vs 10x: 76.5% WR, 506 trades, $+1017
    # So 5x gets 0.54x of 10x net (vs naive 0.5). Use 0.54 as conservative scale.
    # capital scale: 5/50 = 0.10
    # pnl_s1 = pnl_s5 × 0.10 × (548/1017) = pnl_s5 × 0.0539
    S1_PNL_FACTOR = 0.0539
    STAGE1_CAPITAL = 5.0

    # Rolling 30-day window
    WINDOW_DAYS = 30
    WINDOW_MS = WINDOW_DAYS * 86400000

    ts_min = all_trades[0][0]
    ts_max = all_trades[-1][0]
    span_days = (ts_max - ts_min) / 86400000
    print(f"  Span: {span_days:.0f} days")

    pnls_per_window = []
    cur = ts_min
    step_ms = 86400000  # 1d steps
    while cur + WINDOW_MS <= ts_max:
        win_pnls = [p for ts, p in all_trades if cur <= ts < cur + WINDOW_MS]
        win_pnl_s1 = sum(win_pnls) * S1_PNL_FACTOR
        pnls_per_window.append(win_pnl_s1)
        cur += step_ms

    n_w = len(pnls_per_window)
    print(f"  Rolling 30d windows: {n_w}")

    def percentile(arr, p):
        s = sorted(arr); k = (len(s)-1)*p/100
        lo = int(k); hi = min(lo+1, len(s)-1)
        return s[lo] + (s[hi]-s[lo])*(k-lo)

    avg = sum(pnls_per_window) / n_w
    med = percentile(pnls_per_window, 50)
    p5 = percentile(pnls_per_window, 5)
    p25 = percentile(pnls_per_window, 25)
    p75 = percentile(pnls_per_window, 75)
    p95 = percentile(pnls_per_window, 95)
    mn = min(pnls_per_window); mx = max(pnls_per_window)
    n_pos = sum(1 for p in pnls_per_window if p > 0)
    n_neg = sum(1 for p in pnls_per_window if p < 0)
    n_strong_pos = sum(1 for p in pnls_per_window if p > STAGE1_CAPITAL * 0.10)  # > +$0.50 (10%)
    n_strong_neg = sum(1 for p in pnls_per_window if p < -STAGE1_CAPITAL * 0.10) # < -$0.50

    print(f"\n  ==== Stage 1 ($5 capital, 5x lev) — 30-day P&L distribution ====")
    print(f"  windows analyzed: {n_w}")
    print(f"  avg PnL/30d:      ${avg:+.3f} ({avg/STAGE1_CAPITAL*100:+.1f}% of capital)")
    print(f"  median:           ${med:+.3f} ({med/STAGE1_CAPITAL*100:+.1f}%)")
    print(f"  p5  (worst 5%):   ${p5:+.3f} ({p5/STAGE1_CAPITAL*100:+.1f}%)")
    print(f"  p25:              ${p25:+.3f} ({p25/STAGE1_CAPITAL*100:+.1f}%)")
    print(f"  p75:              ${p75:+.3f} ({p75/STAGE1_CAPITAL*100:+.1f}%)")
    print(f"  p95 (best 5%):    ${p95:+.3f} ({p95/STAGE1_CAPITAL*100:+.1f}%)")
    print(f"  min (worst):      ${mn:+.3f} ({mn/STAGE1_CAPITAL*100:+.1f}%)")
    print(f"  max (best):       ${mx:+.3f} ({mx/STAGE1_CAPITAL*100:+.1f}%)")
    print(f"\n  positive months: {n_pos}/{n_w} ({n_pos/n_w*100:.1f}%)")
    print(f"  negative months: {n_neg}/{n_w} ({n_neg/n_w*100:.1f}%)")
    print(f"  strong positive (>+10%): {n_strong_pos}/{n_w} ({n_strong_pos/n_w*100:.1f}%)")
    print(f"  strong negative (<-10%): {n_strong_neg}/{n_w} ({n_strong_neg/n_w*100:.1f}%)")

    # Verdict
    monthly_pct = avg / STAGE1_CAPITAL * 100
    worst_pct = mn / STAGE1_CAPITAL * 100
    if monthly_pct > 5 and worst_pct > -20:
        verdict = f"VIABLE — avg +{monthly_pct:.1f}%/mo, worst {worst_pct:.1f}%. Stage 1 micro-live recommended."
    elif monthly_pct > 0:
        verdict = f"MARGINAL — avg +{monthly_pct:.1f}%/mo but worst {worst_pct:.1f}% painful. Operator must be willing to lose $1+."
    else:
        verdict = f"FAIL — avg {monthly_pct:.1f}%/mo. Don't deploy."
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phasePPP_microlive_monthly.json")
    with open(out_path, "w") as f:
        json.dump({"n_windows": n_w, "window_days": WINDOW_DAYS,
                   "stage1_capital": STAGE1_CAPITAL,
                   "s1_pnl_factor": S1_PNL_FACTOR,
                   "stats": {"avg": avg, "median": med, "p5": p5, "p25": p25,
                             "p75": p75, "p95": p95, "min": mn, "max": mx,
                             "n_positive": n_pos, "n_negative": n_neg,
                             "n_strong_pos": n_strong_pos, "n_strong_neg": n_strong_neg,
                             "avg_pct": avg/STAGE1_CAPITAL*100,
                             "worst_pct": worst_pct},
                   "verdict": verdict}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
