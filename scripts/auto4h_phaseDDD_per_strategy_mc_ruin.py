#!/usr/bin/env python3
"""Phase DDD: Per-strategy Monte Carlo ruin probability.

Phase CCC tested portfolio-level ruin (all 13 strategies pooled). This phase
tests *each strategy independently* — bootstrap 1000 random orderings on
its own pnl sequence with $10 starting capital (single-strat budget at $50 stage).

Why: portfolio diversification can hide a "lottery" strategy with 30%+ standalone
ruin. If we ever run a single strategy in isolation (e.g. early ramp $5 stage
where only 1-2 strats fire), per-strat ruin matters.

Threshold per strat (single-strat budget):
  - SAFE: ruin <= 10%
  - AGGRESSIVE_OK: ruin <= 25%
  - FRAGILE: ruin > 25%
"""
from __future__ import annotations
import sys, json, random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def run():
    print("Phase DDD: Per-strategy MC ruin probability (1000 paths each)")

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
    # Per-strategy MC starting capital = strategy's own margin slot
    # Long strats start $35, shorts start $15

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

    def mc_ruin(trades, start_cap, n_paths=1000, seed=42):
        if not trades:
            return {"n": 0, "ruin_pct": 0.0, "final_p5": start_cap,
                    "final_p50": start_cap, "min_p5": start_cap}
        rng = random.Random(seed)
        ruin_count = 0
        finals = []; mins = []
        for _ in range(n_paths):
            order = list(trades); rng.shuffle(order)
            cap = start_cap; min_cap = cap
            ruined = False
            for p in order:
                cap += p
                if cap < min_cap: min_cap = cap
                if cap <= 0:
                    ruin_count += 1; ruined = True; break
            finals.append(cap if not ruined else 0); mins.append(min_cap)
        finals.sort(); mins.sort()
        return {
            "n": len(trades),
            "ruin_pct": ruin_count / n_paths * 100,
            "final_p5": finals[int(n_paths * 0.05)],
            "final_p50": finals[n_paths // 2],
            "final_p95": finals[int(n_paths * 0.95)],
            "min_p5": mins[int(n_paths * 0.05)],
        }

    results = []
    print(f"\n  {'sid':<18} {'side':<6} {'n':>4} {'avg$':>8} {'ruin%':>7} {'min_p5':>9} {'final_p50':>10} {'verdict'}")
    print(f"  {'-'*18} {'-'*6} {'-'*4} {'-'*8} {'-'*7} {'-'*9} {'-'*10} {'-'*12}")

    for sid, sig, sym, mom, tp, sl in LONG_SET:
        if sym not in cache: continue
        trades = sim(cache[sym], btc_long, SIGNALS[sig], mom, tp, sl, "long", LONG_M)
        r = mc_ruin(trades, LONG_M)
        avg = (sum(trades)/len(trades)) if trades else 0
        if r["ruin_pct"] <= 10: v = "SAFE"
        elif r["ruin_pct"] <= 25: v = "AGGRESSIVE_OK"
        else: v = "FRAGILE"
        results.append({"sid": sid, "side": "long", "start_cap": LONG_M,
                        "avg_pnl": avg, **r, "verdict": v})
        print(f"  {sid:<18} {'long':<6} {r['n']:>4} ${avg:>+6.2f} {r['ruin_pct']:>6.1f}% ${r['min_p5']:>+7.1f} ${r['final_p50']:>+8.1f} {v}")

    for sid, sig, sym, mom, tp, sl in SHORT_SET:
        if sym not in cache: continue
        trades = sim(cache[sym], btc_bear, ALL_SHORT[sig], mom, tp, sl, "short", SHORT_M)
        r = mc_ruin(trades, SHORT_M)
        avg = (sum(trades)/len(trades)) if trades else 0
        if r["ruin_pct"] <= 10: v = "SAFE"
        elif r["ruin_pct"] <= 25: v = "AGGRESSIVE_OK"
        else: v = "FRAGILE"
        results.append({"sid": sid, "side": "short", "start_cap": SHORT_M,
                        "avg_pnl": avg, **r, "verdict": v})
        print(f"  {sid:<18} {'short':<6} {r['n']:>4} ${avg:>+6.2f} {r['ruin_pct']:>6.1f}% ${r['min_p5']:>+7.1f} ${r['final_p50']:>+8.1f} {v}")

    n_safe = sum(1 for r in results if r["verdict"] == "SAFE")
    n_agg = sum(1 for r in results if r["verdict"] == "AGGRESSIVE_OK")
    n_frag = sum(1 for r in results if r["verdict"] == "FRAGILE")
    print(f"\n=== Per-strategy MC ruin summary ===")
    print(f"  SAFE (ruin ≤10%):          {n_safe}/{len(results)}")
    print(f"  AGGRESSIVE_OK (10-25%):    {n_agg}/{len(results)}")
    print(f"  FRAGILE (>25%):            {n_frag}/{len(results)}")

    if n_frag == 0:
        verdict = f"OVERALL SAFE — 0/{len(results)} fragile per-strategy. Even isolated, no strategy ruins >25%."
    elif n_frag <= 2:
        verdict = f"OVERALL ACCEPTABLE — {n_frag}/{len(results)} fragile. Watch in production or pair only."
    else:
        verdict = f"OVERALL FRAGILE — {n_frag}/{len(results)} need pairing or sizing down."
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseDDD_per_strategy_mc_ruin.json")
    with open(out_path, "w") as f:
        json.dump({"strategies": results, "n_safe": n_safe,
                   "n_aggressive_ok": n_agg, "n_fragile": n_frag,
                   "verdict": verdict}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
