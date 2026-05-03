#!/usr/bin/env python3
"""Phase CCC: Monte Carlo ruin probability check (CLAUDE.md mandatory).

Rule: 1000+ MC simulations, ruin <= 5% (safe) or <= 10% (aggressive).

Approach: take observed trade pnls from Phase XX serialized portfolio (493 trades).
Bootstrap 1000 random orderings of the trade sequence, applying each to
$50 starting capital. Track equity curves. Count % of paths that touch
0 (ruin) before reaching the end.

If ruin% <= 5: SAFE
If ruin% <= 10: AGGRESSIVE_OK
Else: BREAKING
"""
from __future__ import annotations
import sys, json, random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def run():
    print("Phase CCC: Monte Carlo ruin probability (1000 paths)")
    xx_path = Path("quant_runtime/output/auto4h/phaseXX_portfolio_sim.json")
    if not xx_path.exists():
        print("  Phase XX output not found — run phaseXX first."); return
    with open(xx_path) as f:
        xx = json.load(f)

    # Reconstruct trade pnl sequence (we have per-strategy summed PnL but not individual trades).
    # Approximate: pnl_per_trade = total_pnl / total_trades for each strategy
    # Better: re-simulate to get individual trades. Since XX gives per-strategy total,
    # use Long set: $710/225 ≈ $3.16/trade and Short: $286/268 ≈ $1.07/trade.
    # We need actual trade-level pnls — let's resimulate quickly here.

    # Actually, approximate using per-strategy trade list — re-run strategies independently
    # and collect raw trade pnls, then bootstrap.
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
    for sym in universe:
        df = load_1h(sym)
        if df is None: continue
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_long = precompute_btc_regime(cache["BTCUSDT"])
    btc_bear = precompute_bear_regime(cache["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache.values())

    def sim(ind, gate, sig_fn, mom, tp, sl, side, margin):
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
        return trades

    all_trades = []
    for sid, sig, sym, mom, tp, sl in LONG_SET:
        if sym not in cache: continue
        ts = sim(cache[sym], btc_long, SIGNALS[sig], mom, tp, sl, "long", LONG_M)
        all_trades.extend(ts)
    for sid, sig, sym, mom, tp, sl in SHORT_SET:
        if sym not in cache: continue
        ts = sim(cache[sym], btc_bear, ALL_SHORT[sig], mom, tp, sl, "short", SHORT_M)
        all_trades.extend(ts)

    print(f"  Collected {len(all_trades)} individual trade pnls")
    if not all_trades:
        print("  No trades — abort"); return

    avg_pnl = sum(all_trades)/len(all_trades)
    pos = [p for p in all_trades if p>0]; neg = [p for p in all_trades if p<0]
    print(f"  avg pnl/trade: ${avg_pnl:+.2f}  wins={len(pos)}  losses={len(neg)}")

    # MC bootstrap: 1000 random orderings, $50 starting capital
    N_PATHS = 1000
    START_CAP = 50.0
    ruin_count = 0
    final_caps = []
    min_caps = []
    rng = random.Random(42)
    for _ in range(N_PATHS):
        order = list(all_trades)
        rng.shuffle(order)
        cap = START_CAP
        min_cap = cap
        for p in order:
            cap += p
            if cap < min_cap: min_cap = cap
            if cap <= 0:
                ruin_count += 1
                break
        final_caps.append(cap)
        min_caps.append(min_cap)

    final_caps.sort(); min_caps.sort()
    p5 = final_caps[int(N_PATHS*0.05)]
    p50 = final_caps[N_PATHS//2]
    p95 = final_caps[int(N_PATHS*0.95)]
    min_p5 = min_caps[int(N_PATHS*0.05)]
    ruin_pct = ruin_count / N_PATHS * 100

    print(f"\n=== MC ruin (N={N_PATHS}, start=${START_CAP}) ===")
    print(f"  ruin %:        {ruin_pct:.1f}%")
    print(f"  final p5:      ${p5:+.2f}")
    print(f"  final p50:     ${p50:+.2f}")
    print(f"  final p95:     ${p95:+.2f}")
    print(f"  min p5:        ${min_p5:+.2f} (worst dip)")

    if ruin_pct <= 5:
        verdict = f"SAFE — ruin {ruin_pct:.1f}% ≤ 5% (CLAUDE.md safe threshold)"
    elif ruin_pct <= 10:
        verdict = f"AGGRESSIVE_OK — ruin {ruin_pct:.1f}% ≤ 10%"
    else:
        verdict = f"BREAKING — ruin {ruin_pct:.1f}% > 10%, need to size down"
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseCCC_mc_ruin.json")
    with open(out_path, "w") as f:
        json.dump({"n_trades": len(all_trades), "n_paths": N_PATHS,
                   "start_capital": START_CAP, "ruin_pct": ruin_pct,
                   "final_p5": p5, "final_p50": p50, "final_p95": p95,
                   "min_p5": min_p5, "verdict": verdict}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
