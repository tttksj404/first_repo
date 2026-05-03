#!/usr/bin/env python3
"""Phase RRR: Consecutive loss-month dependency analysis.

Phase PPP found 5.6% (19/341) of 30-day windows are negative.
Question: Are negative months random or clustered?

If RANDOM (independent): P(2 consecutive negatives) = 0.056^2 = 0.31%
If CLUSTERED (autocorrelated): could be much higher

This phase tests:
  1. Compute month-on-month autocorrelation of P&L sign
  2. Find longest consecutive negative-month streak
  3. Compute observed P(neg | prev=neg) and compare to baseline P(neg)
  4. Worst rolling 2-month and 3-month combined P&L
  5. Critical case: at Stage 1 ($5 cap), what's worst 60-day drawdown?
"""
from __future__ import annotations
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def run():
    print("Phase RRR: Consecutive loss-month dependency analysis (PPP 후속)")

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

    if not all_trades: return

    S1_FACTOR = 0.0539
    STAGE1_CAP = 5.0

    # NON-OVERLAPPING calendar months (12 months span = 12 windows)
    ts_min = all_trades[0][0]
    ts_max = all_trades[-1][0]
    MONTH_MS = 30 * 86400000
    monthly_pnls = []
    cur = ts_min
    while cur + MONTH_MS <= ts_max:
        m_pnl = sum(p for ts, p in all_trades if cur <= ts < cur + MONTH_MS) * S1_FACTOR
        monthly_pnls.append(m_pnl)
        cur += MONTH_MS
    n_months = len(monthly_pnls)
    print(f"\n  Non-overlapping months: {n_months}")

    # Sign analysis
    signs = [1 if p > 0 else (-1 if p < 0 else 0) for p in monthly_pnls]
    n_neg = sum(1 for s in signs if s < 0)
    n_pos = sum(1 for s in signs if s > 0)
    n_zero = sum(1 for s in signs if s == 0)
    print(f"  Months: {n_pos} positive / {n_neg} negative / {n_zero} zero")
    for i, p in enumerate(monthly_pnls):
        sign = "+" if p > 0 else ("-" if p < 0 else "0")
        print(f"    M{i+1:>2}: ${p:+.3f}  [{sign}]")

    # Longest consecutive negative streak
    longest_neg = 0
    cur_neg = 0
    for s in signs:
        if s < 0:
            cur_neg += 1
            longest_neg = max(longest_neg, cur_neg)
        else:
            cur_neg = 0
    print(f"\n  Longest consecutive negative-month streak: {longest_neg}")

    # P(neg | prev_neg) vs P(neg) — autocorrelation proxy
    p_neg = n_neg / n_months
    pairs_neg_neg = sum(1 for i in range(n_months-1) if signs[i] < 0 and signs[i+1] < 0)
    pairs_neg_anything = sum(1 for i in range(n_months-1) if signs[i] < 0)
    p_neg_given_neg = pairs_neg_neg / pairs_neg_anything if pairs_neg_anything else 0
    print(f"  P(neg)         = {p_neg:.3f}")
    print(f"  P(neg|prev=neg)= {p_neg_given_neg:.3f}  (={pairs_neg_neg}/{pairs_neg_anything})")
    if pairs_neg_anything == 0:
        autocorr_verdict = "INSUFFICIENT DATA — too few negative months for autocorrelation"
    elif p_neg_given_neg > p_neg * 1.5:
        autocorr_verdict = "POSITIVE AUTOCORRELATION — losses cluster, expect drawdown bursts"
    else:
        autocorr_verdict = "NO AUTOCORRELATION — losses are random, single-month -32% bound holds"

    # Worst 30/60/90 day rolling P&L (overlapping)
    def worst_rolling(days):
        ms = days * 86400000
        cur = ts_min
        worst = 0
        worst_start = None
        while cur + ms <= ts_max:
            p = sum(pp for ts, pp in all_trades if cur <= ts < cur + ms) * S1_FACTOR
            if p < worst:
                worst = p; worst_start = cur
            cur += 86400000
        return worst, worst_start

    w30, w30_start = worst_rolling(30)
    w60, w60_start = worst_rolling(60)
    w90, w90_start = worst_rolling(90)
    print(f"\n  Worst rolling P&L (Stage 1 $5 capital):")
    print(f"   30d: ${w30:+.3f} ({w30/STAGE1_CAP*100:+.1f}% of capital)")
    print(f"   60d: ${w60:+.3f} ({w60/STAGE1_CAP*100:+.1f}%)")
    print(f"   90d: ${w90:+.3f} ({w90/STAGE1_CAP*100:+.1f}%)")

    # 2-month and 3-month consecutive worst
    worst_2mo = min(monthly_pnls[i] + monthly_pnls[i+1] for i in range(n_months-1)) if n_months >= 2 else 0
    worst_3mo = min(monthly_pnls[i] + monthly_pnls[i+1] + monthly_pnls[i+2] for i in range(n_months-2)) if n_months >= 3 else 0
    print(f"\n  Non-overlapping consecutive worst:")
    print(f"   2 months: ${worst_2mo:+.3f} ({worst_2mo/STAGE1_CAP*100:+.1f}% of capital)")
    print(f"   3 months: ${worst_3mo:+.3f} ({worst_3mo/STAGE1_CAP*100:+.1f}%)")

    # Verdict
    if longest_neg <= 1 and w60 > -STAGE1_CAP * 0.30:
        verdict = f"LOW DOWNSIDE RISK — max 1 consecutive neg month, worst 60d ${w60:+.2f}. Stage 1 micro-live SAFE."
    elif longest_neg == 2 and w60 > -STAGE1_CAP * 0.50:
        verdict = f"MODERATE risk — 2 neg months observed, but worst 60d ${w60:+.2f} bounded. Acceptable."
    else:
        verdict = f"HIGH risk — {longest_neg} consec neg months, worst 60d ${w60:+.2f}. Operator must commit to 60d window."
    print(f"\n  Autocorr verdict: {autocorr_verdict}")
    print(f"  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseRRR_consecutive_loss_months.json")
    with open(out_path, "w") as f:
        json.dump({"n_months": n_months,
                   "monthly_pnls_s1": monthly_pnls,
                   "n_pos": n_pos, "n_neg": n_neg,
                   "longest_neg_streak": longest_neg,
                   "p_neg": p_neg, "p_neg_given_neg": p_neg_given_neg,
                   "worst_30d": w30, "worst_60d": w60, "worst_90d": w90,
                   "worst_2mo_consec": worst_2mo, "worst_3mo_consec": worst_3mo,
                   "autocorr_verdict": autocorr_verdict,
                   "verdict": verdict}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
