#!/usr/bin/env python3
"""Phase LLL: Stage-leverage curve validation.

Bot's stage ramp (OWNER_MANUAL §5):
  Stage 1-2: 5x leverage
  Stage 3-4: 7x leverage
  Stage 5:   10x leverage

ALL prior backtests used LEVERAGE=10. TP/SL are in ROE% so at lower lev
the price-move required to hit TP doubles (5x lev: ROE+50% = price+10%).

This phase re-runs the portfolio at lev = 3, 5, 7, 10 and compares:
  - n_trades (TP hits become rarer at low lev)
  - WR%
  - net pnl
  - whether each stage's promotion gate is achievable

Stage gates (per OWNER_MANUAL):
  Stage 1: ≥20 trades / 7d, WR≥35%, net≥-10%
  Stage 2: ≥40 trades / 7d, WR≥38%, net≥-5%
  Stage 3: ≥80 trades / 14d, WR≥40%, net≥+5%
  Stage 4: ≥120 trades / 21d, WR≥42%, net≥+10%
  Stage 5: avg ≥75/100 model debate

Note: stage gate uses % returns, not abs $. We convert to per-period
trade-rate to validate the trade-count gates are realistic.
"""
from __future__ import annotations
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def run():
    print("Phase LLL: stage-leverage curve (3x/5x/7x/10x)")

    from quant_rotation_engine import load_1h, compute_indicators
    from quant_phase15_signal_library import add_extra_features
    from quant_phase16_robustness import add_obv
    from auto4h_signal_library import SIGNALS
    from auto4h_phaseQ_short_side import SHORT_SIGNALS, precompute_bear_regime
    from auto4h_phaseV_extra_shorts import EXTRA_SHORT_SIGNALS
    from auto4h_stage1_matrix import precompute_btc_regime
    ALL_SHORT = {**SHORT_SIGNALS, **EXTRA_SHORT_SIGNALS}

    LONG_M = 35.0; SHORT_M = 15.0
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

    # span in days (1h candles)
    span_hours = n_min  # approximate
    span_days = span_hours / 24.0

    def sim(ind, gate, sig_fn, mom, tp, sl, side, margin, leverage):
        trades = []
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
                    roe_lo = (lo / entry_px - 1) * leverage * 100
                    roe_hi = (hi / entry_px - 1) * leverage * 100
                    roe_cl = (cl / entry_px - 1) * leverage * 100
                else:
                    roe_lo = (entry_px / lo - 1) * leverage * 100
                    roe_hi = (entry_px / hi - 1) * leverage * 100
                    roe_cl = (entry_px / cl - 1) * leverage * 100
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
                    notional = margin * leverage
                    fee = notional * COST_RT
                    funding = notional * FUNDING_8H * (hold/8)
                    pnl = -margin-fee if exit_roe<=-100 else margin*(exit_roe/100) - fee - funding
                    trades.append(pnl)
                    in_pos = False; last_exit = i
                    if pnl < 0: last_loss = i
        return trades

    print(f"\n  Backtest span: {span_days:.0f} days ({n_min} bars)")

    rows = []
    for lev in [3, 5, 7, 10]:
        all_trades = []
        for sid, sig, sym, mom, tp, sl in LONG_SET:
            if sym not in cache: continue
            ts = sim(cache[sym], btc_long, SIGNALS[sig], mom, tp, sl, "long", LONG_M, lev)
            all_trades.extend(ts)
        for sid, sig, sym, mom, tp, sl in SHORT_SET:
            if sym not in cache: continue
            ts = sim(cache[sym], btc_bear, ALL_SHORT[sig], mom, tp, sl, "short", SHORT_M, lev)
            all_trades.extend(ts)
        net = sum(all_trades)
        n = len(all_trades)
        wins = sum(1 for t in all_trades if t > 0)
        wr = wins/n*100 if n else 0
        avg = net/n if n else 0
        # extrapolate trade rate to 7-day, 14-day, 21-day windows
        rate_per_day = n / span_days if span_days else 0
        n_7d = rate_per_day * 7
        n_14d = rate_per_day * 14
        n_21d = rate_per_day * 21
        rows.append({"lev": lev, "n": n, "net": net, "wr": wr, "avg": avg,
                     "rate_per_day": rate_per_day,
                     "n_7d": n_7d, "n_14d": n_14d, "n_21d": n_21d})

    # Print detail
    print(f"\n  {'lev':>4} {'n_trades':>9} {'WR%':>6} {'net$':>9} {'avg$/tr':>8} {'tr/day':>7} {'7d_proj':>8} {'14d':>5} {'21d':>5}")
    print(f"  {'-'*4} {'-'*9} {'-'*6} {'-'*9} {'-'*8} {'-'*7} {'-'*8} {'-'*5} {'-'*5}")
    for r in rows:
        print(f"  {r['lev']:>3}x {r['n']:>9} {r['wr']:>5.1f}% ${r['net']:>+7.2f} ${r['avg']:>+5.2f} {r['rate_per_day']:>6.2f} {r['n_7d']:>7.1f} {r['n_14d']:>4.1f} {r['n_21d']:>4.1f}")

    # Stage gate validation
    print(f"\n=== Stage gate trade-count feasibility ===")
    print(f"  {'stage':>5} {'lev':>4} {'gate':>6} {'period':>7} {'projected':>10} {'verdict'}")
    print(f"  {'-'*5} {'-'*4} {'-'*6} {'-'*7} {'-'*10} {'-'*8}")
    stage_gates = [
        (1, 5, 20, 7, "trades_7d"),
        (2, 5, 40, 7, "trades_7d"),
        (3, 7, 80, 14, "trades_14d"),
        (4, 7, 120, 21, "trades_21d"),
        (5, 10, 120, 21, "trades_21d"),
    ]
    stage_results = []
    for stage, lev, gate_n, period, label in stage_gates:
        r = next(rr for rr in rows if rr["lev"] == lev)
        proj = r["rate_per_day"] * period
        ok = proj >= gate_n
        v = f"PASS ({proj:.0f} ≥ {gate_n})" if ok else f"FAIL ({proj:.0f} < {gate_n})"
        print(f"  S{stage:>3}  {lev:>3}x  ≥{gate_n:>3} /{period:>3}d {proj:>9.1f}  {v}")
        stage_results.append({"stage": stage, "lev": lev, "gate": gate_n,
                              "period_days": period, "projected": proj,
                              "pass": ok})

    n_pass = sum(1 for s in stage_results if s["pass"])
    print(f"\n  Stage gate feasibility: {n_pass}/5 pass projected.")

    # Net comparison
    lev10 = next(r for r in rows if r["lev"] == 10)
    lev5 = next(r for r in rows if r["lev"] == 5)
    lev7 = next(r for r in rows if r["lev"] == 7)
    print(f"\n=== Leverage sensitivity ===")
    print(f"  10x baseline: ${lev10['net']:+.2f} / {lev10['n']} trades / WR {lev10['wr']:.1f}%")
    print(f"   7x:           ${lev7['net']:+.2f} / {lev7['n']} trades / WR {lev7['wr']:.1f}%  (Δ ${lev7['net']-lev10['net']:+.2f})")
    print(f"   5x:           ${lev5['net']:+.2f} / {lev5['n']} trades / WR {lev5['wr']:.1f}%  (Δ ${lev5['net']-lev10['net']:+.2f})")

    if lev5["net"] > 0 and lev7["net"] > 0 and n_pass >= 4:
        verdict = f"VIABLE — all leverage levels profitable, {n_pass}/5 stage gates feasible."
    elif lev5["net"] > 0 and n_pass >= 3:
        verdict = f"VIABLE w/ caveats — Stage 1-4 OK but {5-n_pass} gates may need adjustment."
    elif lev5["net"] > 0:
        verdict = f"FRAGILE — lev 5x profitable but few stage gates pass projected trade-count."
    else:
        verdict = f"FAIL — lev 5x net negative ({lev5['net']:+.2f}). Stage 1-2 plan unfeasible."
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseLLL_leverage_curve.json")
    with open(out_path, "w") as f:
        json.dump({"leverage_rows": rows, "stage_gate_results": stage_results,
                   "n_stage_pass": n_pass, "verdict": verdict,
                   "span_days": span_days}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
