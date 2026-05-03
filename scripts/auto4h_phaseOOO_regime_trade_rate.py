#!/usr/bin/env python3
"""Phase OOO: Regime-stratified trade-rate analysis.

Phase NNN found fold4 (recent Q4) stalls at Stage 3 — 6 stays + 1 retreat,
never reaches Stage 5. Hypothesis: fold4 falls in a regime period
(prolonged chop or bear) where bot's trade rate drops below amended
S3/S4 gates.

This phase:
  1. Tag each trade with BTC regime at entry (bull/chop/bear)
  2. Compute trade rate per regime
  3. Map fold4 timeline to regime mix
  4. Recommend whether amended gates need regime-conditional logic
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import datetime as dt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def run():
    print("Phase OOO: Regime-stratified trade-rate analysis (NNN fold4 stall 추적)")

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

    # Build per-bar regime label
    # bull = btc_long[i] true (BTC bullish gate active for longs)
    # bear = btc_bear[i] true (BTC bearish gate active for shorts)
    # chop = neither
    btc_ts = raw_ts["BTCUSDT"]
    regime_at_bar = []
    for i in range(n_min):
        bull = btc_long[i] if i < len(btc_long) else False
        bear = btc_bear[i] if i < len(btc_bear) else False
        if bull and not bear: regime = "bull"
        elif bear and not bull: regime = "bear"
        elif bull and bear: regime = "both"  # rare
        else: regime = "chop"
        regime_at_bar.append(regime)

    def sim_collect(ind, ts_arr, gate, sig_fn, mom, tp, sl, side, margin):
        trades = []
        in_pos = False; entry_px = 0; entry_idx = 0; entry_ts = 0; entry_bar = 0
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
                entry_idx = i; entry_ts = int(ts_arr[i]); entry_bar = i; in_pos = True
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
                    trades.append((entry_ts, entry_bar, pnl, side))
                    in_pos = False; last_exit = i
                    if pnl < 0: last_loss = i
        return trades

    print("\n  Collecting trades + tagging regime...")
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

    # Trade rate per regime
    from collections import defaultdict
    trades_by_regime = defaultdict(list)
    for ts_e, bar, pnl, side in all_trades:
        reg = regime_at_bar[bar] if bar < len(regime_at_bar) else "chop"
        trades_by_regime[reg].append((ts_e, pnl, side))

    # Bar-count per regime
    bar_count_by_regime = defaultdict(int)
    for r in regime_at_bar:
        bar_count_by_regime[r] += 1

    print(f"\n  Regime → bar count + trade count:")
    print(f"  {'regime':>6} {'bars':>6} {'%bars':>6} {'trades':>7} {'trades/day':>11} {'WR%':>5} {'net$':>9}")
    print(f"  {'-'*6} {'-'*6} {'-'*6} {'-'*7} {'-'*11} {'-'*5} {'-'*9}")
    regime_summary = []
    total_bars = sum(bar_count_by_regime.values())
    for reg in ["bull", "chop", "bear", "both"]:
        if reg not in bar_count_by_regime and reg not in trades_by_regime: continue
        bars = bar_count_by_regime[reg]
        bar_pct = bars/total_bars*100
        trs = trades_by_regime[reg]
        n = len(trs)
        days = bars/24.0
        rate = n/days if days else 0
        wins = sum(1 for _, p, _ in trs if p > 0)
        wr = wins/n*100 if n else 0
        net = sum(p for _, p, _ in trs)
        print(f"  {reg:>6} {bars:>6} {bar_pct:>5.1f}% {n:>7} {rate:>10.2f} {wr:>4.1f}% ${net:>+7.2f}")
        regime_summary.append({"regime": reg, "bars": bars, "bar_pct": bar_pct,
                               "n_trades": n, "trades_per_day": rate, "wr": wr, "net": net})

    # Map fold4 timeline to regime mix
    if not all_trades:
        print("  No trades — abort"); return
    ts_min = all_trades[0][0]; ts_max = all_trades[-1][0]
    span_ms = ts_max - ts_min
    quarter = span_ms // 4
    fold_starts = [ts_min, ts_min + quarter, ts_min + 2*quarter, ts_min + int(2.5*quarter)]
    fold_ends = [s + 365*86400000 for s in fold_starts]  # cap 365d
    fold_ends = [min(e, ts_max) for e in fold_ends]
    fold_labels = ["fold1", "fold2", "fold3", "fold4"]

    print(f"\n  Per-fold regime mix + trade rate:")
    print(f"  {'fold':>5} {'span':>6} {'bull%':>6} {'chop%':>6} {'bear%':>6} {'tr':>4} {'tr/day':>7} {'WR%':>5} {'net$':>9}")
    print(f"  {'-'*5} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*4} {'-'*7} {'-'*5} {'-'*9}")

    fold_summaries = []
    # Map ts → bar index for regime lookup
    ts_to_bar = {int(btc_ts[i]): i for i in range(min(len(btc_ts), n_min))}

    for label, fs, fe in zip(fold_labels, fold_starts, fold_ends):
        # Count bars in fold by regime
        bars_in_fold = defaultdict(int)
        for i in range(n_min):
            t = int(btc_ts[i])
            if fs <= t < fe:
                bars_in_fold[regime_at_bar[i]] += 1
        total_b = sum(bars_in_fold.values()) or 1
        # Count trades in fold
        trs = [t for t in all_trades if fs <= t[0] < fe]
        n = len(trs)
        days = total_b/24.0
        rate = n/days if days else 0
        wins = sum(1 for ts_e, b, p, s in trs if p > 0)
        wr = wins/n*100 if n else 0
        net = sum(p for ts_e, b, p, s in trs)
        bull_pct = bars_in_fold["bull"]/total_b*100
        chop_pct = bars_in_fold["chop"]/total_b*100
        bear_pct = bars_in_fold["bear"]/total_b*100
        print(f"  {label:>5} {days:>5.0f}d {bull_pct:>5.1f}% {chop_pct:>5.1f}% {bear_pct:>5.1f}% {n:>4} {rate:>6.2f} {wr:>4.1f}% ${net:>+7.2f}")
        fold_summaries.append({"fold": label, "span_days": days,
                               "bull_pct": bull_pct, "chop_pct": chop_pct, "bear_pct": bear_pct,
                               "n_trades": n, "trades_per_day": rate, "wr": wr, "net": net})

    # Diagnose fold4 stall
    f4 = fold_summaries[3]
    f1_3_avg_rate = sum(f["trades_per_day"] for f in fold_summaries[:3]) / 3

    print(f"\n=== Fold 4 stall diagnosis ===")
    print(f"  Fold 4 trade rate: {f4['trades_per_day']:.2f}/day")
    print(f"  Fold 1-3 avg rate: {f1_3_avg_rate:.2f}/day")
    print(f"  Fold 4 chop%: {f4['chop_pct']:.1f}%")
    print(f"  Fold 4 bull%: {f4['bull_pct']:.1f}%")

    if f4["trades_per_day"] < f1_3_avg_rate * 0.7:
        diag = f"Trade rate DROP — fold4 {f4['trades_per_day']:.2f}/day vs fold1-3 avg {f1_3_avg_rate:.2f}/day. {f4['chop_pct']:.0f}% chop bars likely cause."
    elif f4["wr"] < 70:
        diag = f"WR DROP — fold4 WR {f4['wr']:.1f}% lower than usual. Quality, not quantity, is issue."
    else:
        diag = f"Trade rate normal ({f4['trades_per_day']:.2f}/day). Stall likely random window placement — re-running with shifted start would resolve."
    print(f"  Diagnosis: {diag}")

    # Verdict
    chop_pct_overall = next((r["bar_pct"] for r in regime_summary if r["regime"] == "chop"), 0)
    bull_rate = next((r["trades_per_day"] for r in regime_summary if r["regime"] == "bull"), 0)
    chop_rate = next((r["trades_per_day"] for r in regime_summary if r["regime"] == "chop"), 0)
    bear_rate = next((r["trades_per_day"] for r in regime_summary if r["regime"] == "bear"), 0)

    if chop_rate < bull_rate * 0.3:
        verdict = f"REGIME SENSITIVE — chop rate {chop_rate:.2f}/day << bull rate {bull_rate:.2f}/day. Stage gates should be regime-conditional or based on trailing-trade-window not calendar-window."
    elif chop_rate < bull_rate * 0.6:
        verdict = f"MODERATE regime sensitivity — chop {chop_rate:.2f} vs bull {bull_rate:.2f}/day. amended gates ok but expect occasional stalls in chop."
    else:
        verdict = f"REGIME ROBUST — rates similar across regimes. Stalls are random, not regime-driven."
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseOOO_regime_trade_rate.json")
    with open(out_path, "w") as f:
        json.dump({"regime_summary": regime_summary,
                   "fold_summary": fold_summaries,
                   "fold4_diagnosis": diag,
                   "verdict": verdict}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
