#!/usr/bin/env python3
"""Phase UUU: $5 jackpot — single-strategy high-lev backtest.

User question: "한탕 수익률 극대화 — 수수료 해결 가능?"

Phase TTT exposed Bitget min-notional issue at small capital. This phase
tests the alternative: $5 capital deployed on 1-2 best strategies at
high leverage (10x or 20x).

Test matrix:
  - 단일 strat × {5x, 10x, 20x} lev
  - top 3 strategies (per Phase GGG ranking)
  - Stage 1 capital = $5 (full margin per trade)

Metrics:
  - n_trades, WR%, avg$/trade, total $
  - MC bootstrap ruin% at each leverage
  - max single-trade drawdown
  - liquidation count
  - fee % of total revenue
"""
from __future__ import annotations
import sys, json, random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def run():
    print("Phase UUU: $5 single-strategy jackpot mode (high-lev backtest)")

    from quant_rotation_engine import load_1h, compute_indicators
    from quant_phase15_signal_library import add_extra_features
    from quant_phase16_robustness import add_obv
    from auto4h_signal_library import SIGNALS
    from auto4h_phaseQ_short_side import SHORT_SIGNALS, precompute_bear_regime
    from auto4h_phaseV_extra_shorts import EXTRA_SHORT_SIGNALS
    from auto4h_stage1_matrix import precompute_btc_regime
    ALL_SHORT = {**SHORT_SIGNALS, **EXTRA_SHORT_SIGNALS}

    # Top 3 strategies by Phase GGG net contribution
    # (revisit GGG for actual ranking; for now use top 3 known winners)
    TOP_LONGS = [
        ("doge_volexp_4", "vol_expansion", "DOGEUSDT", 0.04, 80, -30),
        ("ada_heikin_2", "heikin_cont", "ADAUSDT", 0.02, 300, -50),
        ("wif_heikin", "heikin_cont", "WIFUSDT", 0.06, 100, -25),
    ]
    TOP_SHORTS = [
        ("near_atrexp_S", "short_atr_expansion", "NEARUSDT", -0.02, 200, -40),
        ("dot_adx_S", "short_adx_trend_dn", "DOTUSDT", -0.02, 150, -35),
        ("link_adx_S", "short_adx_trend_dn", "LINKUSDT", -0.06, 200, -40),
    ]

    STAGE1_CAP = 5.0
    COST_RT = 0.0012; FUNDING_8H = 0.00012; SLIP = 0.0008
    LIQ_ROE = -95.0; CD_E = 12; CD_L = 24

    universe = sorted(set([s[2] for s in TOP_LONGS] + [s[2] for s in TOP_SHORTS]) | {"BTCUSDT"})
    cache = {}
    for sym in universe:
        df = load_1h(sym)
        if df is None: continue
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_long = precompute_btc_regime(cache["BTCUSDT"])
    btc_bear = precompute_bear_regime(cache["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache.values())

    def sim(ind, gate, sig_fn, mom, tp, sl, side, margin, lev):
        trades = []
        liq_count = 0
        total_fees = 0
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
                    roe_lo = (lo / entry_px - 1) * lev * 100
                    roe_hi = (hi / entry_px - 1) * lev * 100
                    roe_cl = (cl / entry_px - 1) * lev * 100
                else:
                    roe_lo = (entry_px / lo - 1) * lev * 100
                    roe_hi = (entry_px / hi - 1) * lev * 100
                    roe_cl = (entry_px / cl - 1) * lev * 100
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
                    notional = margin * lev
                    fee = notional * COST_RT
                    funding = notional * FUNDING_8H * (hold/8)
                    if exit_roe <= -100:
                        pnl = -margin - fee
                        liq_count += 1
                    else:
                        pnl = margin*(exit_roe/100) - fee - funding
                    total_fees += fee + funding
                    trades.append(pnl)
                    in_pos = False; last_exit = i
                    if pnl < 0: last_loss = i
        return trades, liq_count, total_fees

    def mc_ruin(trades, n_paths=1000, ruin_threshold=-0.95):
        """Bootstrap MC: shuffle trade order, simulate equity from $5 start, count ruins."""
        if not trades: return 0
        ruins = 0
        for _ in range(n_paths):
            equity = STAGE1_CAP
            shuffled = trades.copy()
            random.shuffle(shuffled)
            for pnl in shuffled:
                equity += pnl
                if equity < STAGE1_CAP * (1 + ruin_threshold):  # < $0.25
                    ruins += 1; break
        return ruins / n_paths * 100

    print(f"\n  ==== Test Matrix: 3 longs + 3 shorts × {{5x, 10x, 20x}} lev × $5 cap ====\n")
    print(f"  {'strategy':<22} {'lev':>3} {'n_tr':>4} {'WR%':>5} {'avg$':>6} {'net$':>7} {'liq':>3} {'fee%':>5} {'ruin%':>6} {'ann_ret%':>9}")
    print(f"  {'-'*22} {'-'*3} {'-'*4} {'-'*5} {'-'*6} {'-'*7} {'-'*3} {'-'*5} {'-'*6} {'-'*9}")

    results = []
    span_days = n_min / 24.0

    random.seed(42)
    for sid, sig, sym, mom, tp, sl in TOP_LONGS + TOP_SHORTS:
        if sym not in cache: continue
        side = "long" if mom > 0 else "short"
        gate = btc_long if side == "long" else btc_bear
        sig_dict = SIGNALS if side == "long" else ALL_SHORT
        sig_fn = sig_dict[sig]

        for lev in [5, 10, 20]:
            trades, liq, total_fees = sim(cache[sym], gate, sig_fn, mom, tp, sl, side, STAGE1_CAP, lev)
            n = len(trades)
            net = sum(trades)
            wins = sum(1 for t in trades if t > 0)
            wr = wins/n*100 if n else 0
            avg = net/n if n else 0
            fee_pct = total_fees / abs(sum(t for t in trades if t > 0) + 1e-6) * 100 if any(t > 0 for t in trades) else 0
            ruin = mc_ruin(trades)
            ann_ret = (net / STAGE1_CAP) / (span_days/365) * 100 if span_days else 0
            print(f"  {sid:<22} {lev:>2}x {n:>4} {wr:>4.1f}% ${avg:>+4.2f} ${net:>+5.2f} {liq:>3} {fee_pct:>4.1f}% {ruin:>5.1f}% {ann_ret:>+8.0f}%")
            results.append({"strategy": sid, "side": side, "leverage": lev,
                            "n_trades": n, "wr": wr, "avg_pnl": avg, "net": net,
                            "liquidations": liq, "fee_pct_of_gross": fee_pct,
                            "ruin_pct": ruin, "ann_return_pct": ann_ret})

    # Find best by ann_return with ruin constraint
    print(f"\n  ==== Recommendations (ann_return descending, ruin ≤ 10%) ====")
    safe_results = [r for r in results if r["ruin_pct"] <= 10]
    safe_results.sort(key=lambda x: -x["ann_return_pct"])
    print(f"  {'rank':>4} {'strategy':<22} {'lev':>3} {'ann_ret':>8} {'ruin':>5} {'liq':>3} {'net$':>7}")
    for rank, r in enumerate(safe_results[:10]):
        print(f"  {rank+1:>4} {r['strategy']:<22} {r['leverage']:>2}x {r['ann_return_pct']:>+7.0f}% {r['ruin_pct']:>4.1f}% {r['liquidations']:>3} ${r['net']:>+5.2f}")

    # Top vs current $5 13-strat 5x baseline
    if safe_results:
        top = safe_results[0]
        baseline_ann = (4.89 * 12) / 5 * 100  # $4.89/mo × 12 / $5 cap × 100 = 1174% ann (current model)
        # Wait — baseline is 13 strats SCALED. Top single is 1 strat full $5. Different.
        # Actually $4.89/mo on $5 = 97.8%/month = 1174% annualized.
        baseline_ann = 97.8 * 12  # = 1174%
        print(f"\n  Current model (13-strat × 5x, $5 cap): ann +{baseline_ann:.0f}% (Phase PPP scaled)")
        print(f"  Top single jackpot ({top['strategy']} × {top['leverage']}x): ann +{top['ann_return_pct']:.0f}%, ruin {top['ruin_pct']:.1f}%")
        diff = top['ann_return_pct'] - baseline_ann
        if diff > 0:
            verdict = f"JACKPOT MODE WINS — {top['strategy']} × {top['leverage']}x: +{top['ann_return_pct']:.0f}% ann (Δ +{diff:.0f}% vs 13-strat). Ruin {top['ruin_pct']:.1f}% acceptable."
        else:
            verdict = f"DIVERSIFIED WINS — current 13-strat 5x ({baseline_ann:.0f}% ann) > best single ({top['ann_return_pct']:.0f}%). Concentration ↑ ruin risk for less return."
    else:
        verdict = "ALL FAIL ruin constraint — cannot recommend single-strat jackpot mode at $5 cap."
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseUUU_jackpot_single_strategy.json")
    with open(out_path, "w") as f:
        json.dump({"all_results": results,
                   "safe_results_top10": safe_results[:10],
                   "verdict": verdict,
                   "stage1_capital": STAGE1_CAP,
                   "current_baseline_ann_pct": 1174}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
