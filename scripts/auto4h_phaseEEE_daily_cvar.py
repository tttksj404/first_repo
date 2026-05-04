#!/usr/bin/env python3
"""Phase EEE: Daily PnL distribution + CVaR / max-consecutive-loss-days.

Bins all trades by exit-day across the portfolio simulation, then derives:
  - Daily PnL histogram
  - Worst day (max single-day loss)
  - 99% CVaR (avg loss in worst 1% of days)
  - Max consecutive loss days streak

Why: Phase XX gave portfolio +$996/12.5mo with -$64 max DD,
but DD was measured equity-curve trough-to-peak. Daily PnL distribution
gives a different lens — what's the worst single day, and how many bad days
in a row? Useful for daily $ stop-loss circuit-breaker tuning.

Threshold:
  worst single day ≥ -2 × max DD: SAFE
  99% CVaR magnitude ≤ portfolio gross weekly: SAFE
"""
from __future__ import annotations
import sys, json
from pathlib import Path
from collections import defaultdict
import datetime as dt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def run():
    print("Phase EEE: Daily PnL CVaR / consecutive-loss-day analysis")

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
    raw_ts = {}  # symbol -> ts array
    for sym in universe:
        df = load_1h(sym)
        if df is None: continue
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
        raw_ts[sym] = df[:, 0]  # column 0 = timestamp ms
    btc_long = precompute_btc_regime(cache["BTCUSDT"])
    btc_bear = precompute_bear_regime(cache["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache.values())

    def sim_with_ts(ind, ts_arr, gate, sig_fn, mom, tp, sl, side, margin):
        trades = []  # (pnl, exit_ts_ms)
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
                    trades.append((pnl, int(ts_arr[i])))
                    in_pos = False; last_exit = i
                    if pnl < 0: last_loss = i
        return trades

    daily = defaultdict(float)  # date_str -> total_pnl
    daily_count = defaultdict(int)
    all_trades = []
    for sid, sig, sym, mom, tp, sl in LONG_SET:
        if sym not in cache: continue
        ts_arr = raw_ts[sym]
        ts = sim_with_ts(cache[sym], ts_arr, btc_long, SIGNALS[sig], mom, tp, sl, "long", LONG_M)
        all_trades.extend(ts)
    for sid, sig, sym, mom, tp, sl in SHORT_SET:
        if sym not in cache: continue
        ts_arr = raw_ts[sym]
        ts = sim_with_ts(cache[sym], ts_arr, btc_bear, ALL_SHORT[sig], mom, tp, sl, "short", SHORT_M)
        all_trades.extend(ts)

    for pnl, ts_ms in all_trades:
        d = dt.datetime.utcfromtimestamp(ts_ms / 1000.0).strftime("%Y-%m-%d")
        daily[d] += pnl
        daily_count[d] += 1

    n_trades = len(all_trades)
    print(f"\n  Total trades: {n_trades}")
    print(f"  Active days:  {len(daily)} (days with ≥1 exit)")

    # Continuous date axis: from first to last day, fill 0 for non-active
    if not daily:
        print("  No trades — abort"); return
    sorted_days = sorted(daily.keys())
    start = dt.datetime.strptime(sorted_days[0], "%Y-%m-%d").date()
    end = dt.datetime.strptime(sorted_days[-1], "%Y-%m-%d").date()
    span_days = (end - start).days + 1

    daily_pnls = []
    cur = start
    while cur <= end:
        ds = cur.strftime("%Y-%m-%d")
        daily_pnls.append(daily.get(ds, 0.0))
        cur += dt.timedelta(days=1)

    sorted_pnls = sorted(daily_pnls)
    n_days = len(daily_pnls)
    p1 = sorted_pnls[max(0, int(n_days * 0.01))]
    p5 = sorted_pnls[max(0, int(n_days * 0.05))]
    p50 = sorted_pnls[n_days // 2]
    p95 = sorted_pnls[min(n_days - 1, int(n_days * 0.95))]
    p99 = sorted_pnls[min(n_days - 1, int(n_days * 0.99))]
    worst = sorted_pnls[0]
    best = sorted_pnls[-1]
    avg = sum(daily_pnls) / n_days

    # CVaR 99% = mean of worst 1% days
    worst_1pct = sorted_pnls[: max(1, n_days // 100)]
    cvar99 = sum(worst_1pct) / len(worst_1pct)

    # Max consecutive losing days
    cur_streak = 0; max_streak = 0
    cur_loss_streak = 0; max_loss_streak = 0
    for p in daily_pnls:
        if p < 0:
            cur_loss_streak += 1
            max_loss_streak = max(max_loss_streak, cur_loss_streak)
        else:
            cur_loss_streak = 0

    n_pos = sum(1 for p in daily_pnls if p > 0)
    n_neg = sum(1 for p in daily_pnls if p < 0)
    n_zero = sum(1 for p in daily_pnls if p == 0)

    print(f"\n=== Daily PnL distribution ({span_days} days) ===")
    print(f"  span:           {start} → {end}")
    print(f"  positive days:  {n_pos}/{n_days} ({n_pos/n_days*100:.1f}%)")
    print(f"  negative days:  {n_neg}/{n_days} ({n_neg/n_days*100:.1f}%)")
    print(f"  zero days:      {n_zero}/{n_days} ({n_zero/n_days*100:.1f}%) (no exits)")
    print(f"  avg / day:      ${avg:+.2f}")
    print(f"  p1  (worst 1%): ${p1:+.2f}")
    print(f"  p5  (worst 5%): ${p5:+.2f}")
    print(f"  p50 (median):   ${p50:+.2f}")
    print(f"  p95:            ${p95:+.2f}")
    print(f"  p99:            ${p99:+.2f}")
    print(f"  worst day:      ${worst:+.2f}")
    print(f"  best day:       ${best:+.2f}")
    print(f"  CVaR 99%:       ${cvar99:+.2f} (avg of worst 1% days)")
    print(f"  max consec losing days: {max_loss_streak}")

    # Verdict: bot stage-5 capital is $50, so worst-day -50 = full ruin.
    # Daily $ stop-loss at -20% × stage cap = -$10 (per OWNER_MANUAL section 4).
    # SAFE if worst single day > -$10 (within daily abort threshold).
    if worst >= -10:
        verdict = f"SAFE — worst day ${worst:+.2f} stays inside -$10 daily abort threshold"
    elif worst >= -20:
        verdict = f"ACCEPTABLE — worst day ${worst:+.2f} would trip daily abort but recoverable"
    else:
        verdict = f"FRAGILE — worst day ${worst:+.2f} exceeds -$20 (40% of stage 5 cap)"
    print(f"\n  Verdict: {verdict}")

    # Top 5 worst days for inspection
    print(f"\n  Top 5 worst days:")
    pairs = sorted([(p, d) for d, p in daily.items()])
    for p, d in pairs[:5]:
        print(f"    {d}  ${p:+.2f}  ({daily_count[d]} exits)")

    out_path = Path("quant_runtime/output/auto4h/phaseEEE_daily_cvar.json")
    with open(out_path, "w") as f:
        json.dump({
            "n_trades": n_trades, "span_days": span_days,
            "n_pos_days": n_pos, "n_neg_days": n_neg, "n_zero_days": n_zero,
            "avg_per_day": avg, "worst_day": worst, "best_day": best,
            "p1": p1, "p5": p5, "p50": p50, "p95": p95, "p99": p99,
            "cvar99": cvar99, "max_consecutive_loss_days": max_loss_streak,
            "verdict": verdict
        }, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
