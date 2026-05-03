#!/usr/bin/env python3
"""Phase GGG: Per-symbol/strategy PnL contribution breakdown.

Purpose: Phase XX gave portfolio +$996/12.5mo. But which strategies carry it?
If 2 strategies make $700 and 11 make $296, we have concentration risk
(those 2 strats break -> portfolio breaks). If load is even, robust.

Reports:
  - Per-strategy net + n_trades + WR%
  - Top-3 vs bottom-3 contribution
  - Herfindahl index of PnL share (concentration measure)
  - Verdict: BALANCED (top3 < 60%) / CONCENTRATED (top3 60-80%) / DOMINATED (>80%)
"""
from __future__ import annotations
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def run():
    print("Phase GGG: per-symbol/strategy PnL contribution")

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

    contributions = []
    for sid, sig, sym, mom, tp, sl in LONG_SET:
        if sym not in cache: continue
        trades = sim(cache[sym], btc_long, SIGNALS[sig], mom, tp, sl, "long", LONG_M)
        net = sum(trades)
        n = len(trades)
        wins = sum(1 for t in trades if t>0)
        wr = wins/n*100 if n else 0
        contributions.append({"sid": sid, "side": "long", "symbol": sym,
                              "n": n, "net": net, "wr": wr,
                              "avg": net/n if n else 0})
    for sid, sig, sym, mom, tp, sl in SHORT_SET:
        if sym not in cache: continue
        trades = sim(cache[sym], btc_bear, ALL_SHORT[sig], mom, tp, sl, "short", SHORT_M)
        net = sum(trades)
        n = len(trades)
        wins = sum(1 for t in trades if t>0)
        wr = wins/n*100 if n else 0
        contributions.append({"sid": sid, "side": "short", "symbol": sym,
                              "n": n, "net": net, "wr": wr,
                              "avg": net/n if n else 0})

    contributions.sort(key=lambda x: -x["net"])
    total_net = sum(c["net"] for c in contributions)
    total_n = sum(c["n"] for c in contributions)

    print(f"\n  Total portfolio net: ${total_net:+.2f}  ({total_n} trades)")
    print(f"\n  {'rank':>4} {'sid':<18} {'side':<6} {'n':>4} {'net$':>9} {'%share':>7} {'WR%':>6} {'avg$':>7}")
    print(f"  {'-'*4} {'-'*18} {'-'*6} {'-'*4} {'-'*9} {'-'*7} {'-'*6} {'-'*7}")

    for rank, c in enumerate(contributions, 1):
        share = c["net"] / total_net * 100 if total_net else 0
        print(f"  #{rank:>2}  {c['sid']:<18} {c['side']:<6} {c['n']:>4} ${c['net']:>+7.2f} {share:>+6.1f}% {c['wr']:>5.1f}% ${c['avg']:>+5.2f}")

    # Concentration
    top3 = sum(c["net"] for c in contributions[:3])
    top5 = sum(c["net"] for c in contributions[:5])
    bot3 = sum(c["net"] for c in contributions[-3:])
    top3_pct = top3 / total_net * 100 if total_net else 0
    top5_pct = top5 / total_net * 100 if total_net else 0

    # Herfindahl (positive contributions only, normalize)
    pos_total = sum(c["net"] for c in contributions if c["net"] > 0)
    if pos_total > 0:
        herf = sum((c["net"] / pos_total) ** 2 for c in contributions if c["net"] > 0)
    else:
        herf = 1.0
    eff_strats = 1 / herf if herf > 0 else 0

    print(f"\n=== Concentration analysis ===")
    print(f"  Top-3 share: {top3_pct:.1f}% (${top3:+.2f})")
    print(f"  Top-5 share: {top5_pct:.1f}% (${top5:+.2f})")
    print(f"  Bottom-3 net: ${bot3:+.2f}")
    print(f"  Herfindahl index: {herf:.3f}  ⇒ effective strategies: {eff_strats:.1f}")

    if top3_pct < 60:
        verdict = f"BALANCED — top-3 only {top3_pct:.0f}%, even load across {eff_strats:.1f} effective strats."
    elif top3_pct < 80:
        verdict = f"MODERATE CONCENTRATION — top-3 = {top3_pct:.0f}%. Single-strat fail = -$200~-$300 hit."
    else:
        verdict = f"CONCENTRATED — top-3 = {top3_pct:.0f}%. Bot relies on a few strats."
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseGGG_per_symbol_contribution.json")
    with open(out_path, "w") as f:
        json.dump({"strategies": contributions, "total_net": total_net,
                   "top3_share_pct": top3_pct, "top5_share_pct": top5_pct,
                   "herfindahl": herf, "effective_strats": eff_strats,
                   "verdict": verdict}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
