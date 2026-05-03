#!/usr/bin/env python3
"""Phase III: Hour-filter walk-forward verification.

Phase HHH found UTC 4/5/11 hours net-negative in-sample. This phase
splits the trade history into 4 equal time-folds and checks whether
those losing hours stay losing in EVERY fold.

If 3-4 folds consistently negative for h=4,5,11 → real edge, filter recommended.
If <3 folds → in-sample noise, no filter.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
from collections import defaultdict
import datetime as dt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def run():
    print("Phase III: Hour-filter 4-fold walk-forward verification (Phase HHH 후속)")

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

    def sim_with_entry_ts(ind, ts_arr, gate, sig_fn, mom, tp, sl, side, margin):
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
                    trades.append((pnl, entry_ts))
                    in_pos = False; last_exit = i
                    if pnl < 0: last_loss = i
        return trades

    all_trades = []
    for sid, sig, sym, mom, tp, sl in LONG_SET:
        if sym not in cache: continue
        ts = sim_with_entry_ts(cache[sym], raw_ts[sym], btc_long, SIGNALS[sig], mom, tp, sl, "long", LONG_M)
        all_trades.extend(ts)
    for sid, sig, sym, mom, tp, sl in SHORT_SET:
        if sym not in cache: continue
        ts = sim_with_entry_ts(cache[sym], raw_ts[sym], btc_bear, ALL_SHORT[sig], mom, tp, sl, "short", SHORT_M)
        all_trades.extend(ts)

    # 4-fold by entry_ts: split timeline into 4 equal time slices
    if not all_trades:
        print("  No trades — abort"); return
    ts_min = min(t[1] for t in all_trades)
    ts_max = max(t[1] for t in all_trades)
    span = ts_max - ts_min
    fold_span = span / 4

    folds = [[] for _ in range(4)]
    for pnl, ts in all_trades:
        k = min(3, int((ts - ts_min) // fold_span))
        folds[k].append((pnl, ts))

    print(f"\n  Total trades: {len(all_trades)}, fold-spans = {fold_span/86400000:.0f} days each")
    print(f"\n  Per-fold hour breakdown for h=4,5,11 (LOSING in full sample):")
    print(f"\n  {'fold':>4} {'h':>3} {'n':>4} {'net$':>9} {'avg$':>8} {'sign'}")
    print(f"  {'-'*4} {'-'*3} {'-'*4} {'-'*9} {'-'*8} {'-'*4}")

    target_hours = [4, 5, 11]
    losing_count = defaultdict(int)  # hour -> #folds with negative net
    fold_summary = []

    for k in range(4):
        for h in target_hours:
            pnls = [p for p, ts in folds[k] if dt.datetime.fromtimestamp(ts/1000.0, tz=dt.timezone.utc).hour == h]
            n = len(pnls)
            net = sum(pnls)
            avg = net/n if n else 0
            sign = "+" if net >= 0 else "-"
            print(f"  {k+1:>3}  {h:>3} {n:>4} ${net:>+7.2f} ${avg:>+6.2f}  {sign}")
            if net < 0: losing_count[h] += 1
            fold_summary.append({"fold": k+1, "hour": h, "n": n, "net": net, "avg": avg})

    print(f"\n  Per-hour fold-consistency:")
    print(f"  {'h':>3} {'#folds_negative':>16} {'verdict'}")
    for h in target_hours:
        nf = losing_count[h]
        if nf >= 3: v = f"REAL BIAS — {nf}/4 folds negative"
        elif nf == 2: v = f"WEAK — {nf}/4 folds negative (mixed)"
        else: v = f"NOISE — only {nf}/4 folds negative (in-sample artifact)"
        print(f"  {h:>3}  {nf:>15}  {v}")

    real_bias_hrs = [h for h in target_hours if losing_count[h] >= 3]
    weak_hrs = [h for h in target_hours if losing_count[h] == 2]
    noise_hrs = [h for h in target_hours if losing_count[h] <= 1]

    print(f"\n=== Hour-filter WF verdict ===")
    if real_bias_hrs:
        verdict = f"FILTER RECOMMENDED — hours {real_bias_hrs} consistently lose across folds. Block in v14."
    elif weak_hrs:
        verdict = f"INCONCLUSIVE — hours {weak_hrs} weak signal (2/4 folds). Continue paper monitoring."
    else:
        verdict = f"NO REAL BIAS — Phase HHH finding was IN-SAMPLE NOISE. No filter needed."
    print(f"  {verdict}")

    # Also compute portfolio impact if we DID filter all 3 hours
    blocked_pnl = sum(p for p, ts in all_trades
                      if dt.datetime.fromtimestamp(ts/1000.0, tz=dt.timezone.utc).hour in target_hours)
    total_pnl = sum(p for p, _ in all_trades)
    print(f"\n  Sanity: blocking h=4/5/11 = filter ${-blocked_pnl:+.2f} (would change portfolio from ${total_pnl:+.2f} to ${total_pnl - blocked_pnl:+.2f})")

    out_path = Path("quant_runtime/output/auto4h/phaseIII_hour_filter_wf.json")
    with open(out_path, "w") as f:
        json.dump({"folds": fold_summary, "losing_count": dict(losing_count),
                   "real_bias_hours": real_bias_hrs, "weak_hours": weak_hrs,
                   "noise_hours": noise_hrs, "verdict": verdict,
                   "blocked_pnl_in_sample": blocked_pnl},
                  f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
