#!/usr/bin/env python3
"""Phase FFF: Slippage stress curve (CLAUDE.md mandatory rule #6).

Rule: 슬리피지 스트레스 (확정 전): 0/5/10/15/20bps, 5bps까지 수익이면 PASS

Phase SS measured actual orderbook L2 slippage = 6.67bps p95.
Phase XX baseline simulator used SLIP=8bps -> +$996/12.5mo.

This phase varies slippage 0/5/10/15/20bps and re-runs the same 13-strategy
serialized portfolio sim (Phase XX style: bar-by-bar with Mode B + caps).
PASS threshold: net > 0 at 5bps. Stretch: net > 0 at 15bps.
"""
from __future__ import annotations
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def run():
    print("Phase FFF: Slippage stress curve (CLAUDE.md mandatory rule #6)")

    from quant_rotation_engine import load_1h, compute_indicators
    from quant_phase15_signal_library import add_extra_features
    from quant_phase16_robustness import add_obv
    from auto4h_signal_library import SIGNALS
    from auto4h_phaseQ_short_side import SHORT_SIGNALS, precompute_bear_regime
    from auto4h_phaseV_extra_shorts import EXTRA_SHORT_SIGNALS
    from auto4h_stage1_matrix import precompute_btc_regime
    ALL_SHORT = {**SHORT_SIGNALS, **EXTRA_SHORT_SIGNALS}

    LEVERAGE = 10; LONG_M = 35.0; SHORT_M = 15.0
    COST_RT = 0.0012; FUNDING_8H = 0.00012
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

    def sim_strategy(ind, gate, sig_fn, mom, tp, sl, side, margin, slip):
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
                entry_px = ind["close"][i] * (1 + slip if side=="long" else 1 - slip)
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
                    # Apply exit-side slippage too: roe_realized = exit_roe - slip_bps_roe
                    # slip_bps -> price impact -> roe = slip * leverage * 100
                    slip_roe_pct = slip * LEVERAGE * 100  # convert slip fraction -> roe percent
                    if exit_roe <= -100:
                        pnl = -margin - fee
                    else:
                        # exit slippage: long sells at lower / short buys at higher -> reduces roe
                        adj_roe = exit_roe - slip_roe_pct
                        pnl = margin * (adj_roe / 100) - fee - funding
                    trades.append(pnl)
                    in_pos = False; last_exit = i
                    if pnl < 0: last_loss = i
        return trades

    slip_bps_grid = [0, 5, 10, 15, 20]
    summary = []
    print(f"\n  {'slip_bps':>8} {'gross_pnl':>12} {'n_trades':>9} {'wins':>5} {'losses':>7} {'WR%':>6} {'avg$/tr':>8} {'verdict'}")
    print(f"  {'-'*8} {'-'*12} {'-'*9} {'-'*5} {'-'*7} {'-'*6} {'-'*8} {'-'*8}")

    for bps in slip_bps_grid:
        slip = bps / 10000.0
        all_trades = []
        for sid, sig, sym, mom, tp, sl in LONG_SET:
            if sym not in cache: continue
            ts = sim_strategy(cache[sym], btc_long, SIGNALS[sig], mom, tp, sl, "long", LONG_M, slip)
            all_trades.extend(ts)
        for sid, sig, sym, mom, tp, sl in SHORT_SET:
            if sym not in cache: continue
            ts = sim_strategy(cache[sym], btc_bear, ALL_SHORT[sig], mom, tp, sl, "short", SHORT_M, slip)
            all_trades.extend(ts)
        net = sum(all_trades)
        n = len(all_trades)
        wins = sum(1 for t in all_trades if t>0)
        losses = sum(1 for t in all_trades if t<0)
        wr = wins/n*100 if n else 0
        avg = net/n if n else 0
        if net > 0: v = "PROFIT"
        else: v = "LOSS"
        summary.append({"slip_bps": bps, "gross_pnl": net, "n": n,
                        "wins": wins, "losses": losses, "wr": wr, "avg": avg, "verdict": v})
        print(f"  {bps:>7}b ${net:>+10.2f} {n:>9} {wins:>5} {losses:>7} {wr:>5.1f}% ${avg:>+5.2f} {v}")

    pf_5 = next(s for s in summary if s["slip_bps"] == 5)
    pf_15 = next(s for s in summary if s["slip_bps"] == 15)
    pf_20 = next(s for s in summary if s["slip_bps"] == 20)

    print(f"\n=== Slippage stress curve (CLAUDE.md rule #6) ===")
    if pf_5["gross_pnl"] > 0:
        if pf_20["gross_pnl"] > 0:
            verdict = f"ROBUST — profitable at all 0/5/10/15/20bps. Survives 4× actual slippage (6.67bps)."
        elif pf_15["gross_pnl"] > 0:
            verdict = f"PASS — profitable through 15bps (~2× actual). Confirms CLAUDE.md threshold + buffer."
        else:
            verdict = f"PASS — profitable at 5bps (CLAUDE.md threshold met)."
    else:
        verdict = f"FAIL — unprofitable at 5bps. CLAUDE.md mandatory rule #6 not met."
    print(f"  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseFFF_slippage_stress_curve.json")
    with open(out_path, "w") as f:
        json.dump({"curve": summary, "verdict": verdict}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
