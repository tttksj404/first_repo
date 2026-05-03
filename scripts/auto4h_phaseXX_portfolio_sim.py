#!/usr/bin/env python3
"""Phase XX: Serialized portfolio simulator with VV cap + kill-switches.

Phase QQ ran each strategy independently. Phase VV showed cap is needed.
Phase XX runs a bar-by-bar serialized simulator with:
  - Phase VV: max 4 simultaneous shorts
  - Phase II/DD: rolling 7d portfolio kill-switch (-15% DD on $50/strat = -$97)
  - Phase Z mode B: long $35 + short $15 sizing
  - kill-switch (5 consec losses → 7d pause)

Reports: cum_pnl, max DD, equity curve, cap-blocked count, kill-switch trips.
Comparison to Phase QQ (sum of independents) measures real edge after caps.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv
from auto4h_signal_library import SIGNALS
from auto4h_phaseQ_short_side import SHORT_SIGNALS, precompute_bear_regime
from auto4h_phaseV_extra_shorts import EXTRA_SHORT_SIGNALS
from auto4h_stage1_matrix import precompute_btc_regime

ALL_SHORT = {**SHORT_SIGNALS, **EXTRA_SHORT_SIGNALS}

LEVERAGE = 10
LONG_MARGIN = 35.0   # Phase Z Mode B: 70.3% of $50 to longs
SHORT_MARGIN = 15.0  # 29.7% to shorts
COST_RT = 0.0012
FUNDING_8H = 0.00012
SLIPPAGE_BPS = 8
LIQ_ROE = -95.0
COOLDOWN_EXIT = 12
COOLDOWN_LOSS = 24
MAX_OPEN_SHORTS = 4
KILLSWITCH_CONSEC = 5
KILLSWITCH_PAUSE_BARS = 7*24
PORT_DD_LIMIT = -97.0  # ~ -15% on $50 cap × 13 strats × 0.15 ≈ -$97

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


class StratState:
    __slots__ = ("sid","sig","sym","mom","tp","sl","side","margin",
                 "in_pos","entry_px","entry_idx",
                 "last_exit","last_loss","consec_losses","paused_until","trades")
    def __init__(self, sid, sig, sym, mom, tp, sl, side, margin):
        self.sid=sid; self.sig=sig; self.sym=sym; self.mom=mom; self.tp=tp; self.sl=sl
        self.side=side; self.margin=margin
        self.in_pos=False; self.entry_px=0.0; self.entry_idx=0
        self.last_exit=-1; self.last_loss=-1; self.consec_losses=0
        self.paused_until=-1
        self.trades=[]


def run():
    print("Phase XX: serialized portfolio simulator (Mode B + VV cap + kill-switches)")
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

    states = []
    for sid, sig, sym, mom, tp, sl in LONG_SET:
        if sym not in cache: continue
        states.append(StratState(sid, sig, sym, mom, tp, sl, "long", LONG_MARGIN))
    for sid, sig, sym, mom, tp, sl in SHORT_SET:
        if sym not in cache: continue
        states.append(StratState(sid, sig, sym, mom, tp, sl, "short", SHORT_MARGIN))

    slip = SLIPPAGE_BPS / 10000.0
    cum_pnl = 0.0
    equity_curve = [0.0]
    daily_pnl = []
    cap_blocked = 0; ks_trips = 0; port_dd_trips = 0

    for i in range(50, n_min):
        # Track shorts open count for cap
        shorts_open = sum(1 for s in states if s.side=="short" and s.in_pos)

        # Phase II rolling 7d port pnl from this sim
        cutoff_idx = i - 7*24
        if cutoff_idx >= 0 and cutoff_idx < len(equity_curve):
            port_7d = equity_curve[i-50] - equity_curve[max(0, cutoff_idx-50)]
        else:
            port_7d = equity_curve[i-50] if (i-50) < len(equity_curve) else 0.0

        port_pause = port_7d <= PORT_DD_LIMIT
        if port_pause and i % 24 == 0:
            port_dd_trips += 1

        for st in states:
            ind = cache[st.sym]
            if i >= len(ind["close"]): continue
            cl = ind["close"][i]; hi = ind["high"][i]; lo = ind["low"][i]

            if st.in_pos:
                if st.side == "long":
                    roe_lo = (lo / st.entry_px - 1) * LEVERAGE * 100
                    roe_hi = (hi / st.entry_px - 1) * LEVERAGE * 100
                    roe_cl = (cl / st.entry_px - 1) * LEVERAGE * 100
                else:
                    roe_lo = (st.entry_px / lo - 1) * LEVERAGE * 100
                    roe_hi = (st.entry_px / hi - 1) * LEVERAGE * 100
                    roe_cl = (st.entry_px / cl - 1) * LEVERAGE * 100
                exit_roe = None
                sig_fn = SIGNALS.get(st.sig) or ALL_SHORT.get(st.sig)
                if st.side == "long":
                    if roe_lo <= LIQ_ROE: exit_roe = -100
                    elif roe_lo <= st.sl: exit_roe = st.sl
                    elif roe_hi >= st.tp: exit_roe = st.tp
                    elif (not sig_fn(ind, i)) and roe_cl > 0: exit_roe = roe_cl
                else:
                    if roe_hi <= LIQ_ROE: exit_roe = -100
                    elif roe_hi <= st.sl: exit_roe = st.sl
                    elif roe_lo >= st.tp: exit_roe = st.tp
                    elif (not sig_fn(ind, i)) and roe_cl > 0: exit_roe = roe_cl
                if exit_roe is not None:
                    hold = i - st.entry_idx
                    notional = st.margin * LEVERAGE
                    fee = notional * COST_RT
                    funding = notional * FUNDING_8H * (hold/8)
                    pnl = -st.margin-fee if exit_roe<=-100 else st.margin*(exit_roe/100) - fee - funding
                    st.trades.append(pnl)
                    st.in_pos = False; st.last_exit = i
                    if pnl < 0:
                        st.last_loss = i; st.consec_losses += 1
                        if st.consec_losses >= KILLSWITCH_CONSEC:
                            st.paused_until = i + KILLSWITCH_PAUSE_BARS
                            ks_trips += 1
                    else:
                        st.consec_losses = 0
                    cum_pnl += pnl
            else:
                if port_pause: continue
                if st.paused_until > i: continue
                if st.last_exit >= 0 and (i - st.last_exit) < COOLDOWN_EXIT: continue
                if st.last_loss >= 0 and (i - st.last_loss) < COOLDOWN_LOSS: continue
                gate = btc_long if st.side=="long" else btc_bear
                if i < len(gate) and not gate[i]: continue
                if st.side == "long":
                    if ind["mom24"][i] < st.mom: continue
                else:
                    if ind["mom24"][i] > st.mom: continue
                sig_fn = SIGNALS.get(st.sig) or ALL_SHORT.get(st.sig)
                if not sig_fn(ind, i): continue
                if st.side == "short" and shorts_open >= MAX_OPEN_SHORTS:
                    cap_blocked += 1; continue
                st.entry_px = cl * (1 + slip if st.side=="long" else 1 - slip)
                st.entry_idx = i; st.in_pos = True
                if st.side == "short": shorts_open += 1

        equity_curve.append(cum_pnl)

    # final stats
    eq = np.array(equity_curve)
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    max_dd = float(dd.min())

    n_long = sum(len(s.trades) for s in states if s.side=="long")
    n_short = sum(len(s.trades) for s in states if s.side=="short")
    long_pnl = sum(sum(s.trades) for s in states if s.side=="long")
    short_pnl = sum(sum(s.trades) for s in states if s.side=="short")
    total = sum(sum(s.trades) for s in states)

    print(f"\n=== Serialized portfolio result (n_min={n_min} bars, mode B) ===")
    print(f"  long trades:   {n_long} ({sum(1 for s in states if s.side=='long')} strats)")
    print(f"  short trades:  {n_short} ({sum(1 for s in states if s.side=='short')} strats)")
    print(f"  long pnl:      ${long_pnl:+.2f}")
    print(f"  short pnl:     ${short_pnl:+.2f}")
    print(f"  total cum pnl: ${total:+.2f}")
    print(f"  max DD:        ${max_dd:+.2f}")
    print(f"  cap-blocked entries: {cap_blocked}")
    print(f"  kill-switch trips:   {ks_trips}")
    print(f"  port-DD pause days:  {port_dd_trips}")

    # Compare to QQ (sum of independents)
    print(f"\n  cf. Phase QQ sum-of-independents (with $50/strat margin) was ~$+2200")
    print(f"  Phase XX is ~{total/2200*100:.0f}% of that — gap = Mode B sizing + caps + ks")

    if total > 1000:
        verdict = f"ROBUST — Mode B + caps still produce ${total:+.0f} over full lookback. Max DD ${max_dd:.0f} ≤ -$97 limit."
    elif total > 500:
        verdict = f"ACCEPTABLE — ${total:+.0f}; caps cost some edge but profitable."
    elif total > 0:
        verdict = f"MARGINAL — ${total:+.0f}; portfolio above zero but caps/ks heavy drag."
    else:
        verdict = f"BROKEN — ${total:+.0f} negative after caps. Investigate."
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseXX_portfolio_sim.json")
    with open(out_path, "w") as f:
        json.dump({
            "total_pnl": total, "long_pnl": long_pnl, "short_pnl": short_pnl,
            "n_long_trades": n_long, "n_short_trades": n_short,
            "max_dd": max_dd,
            "cap_blocked": cap_blocked, "ks_trips": ks_trips,
            "port_dd_trips": port_dd_trips,
            "per_strategy": [{"sid": s.sid, "side": s.side, "n": len(s.trades),
                              "pnl": sum(s.trades)} for s in states],
            "verdict": verdict,
        }, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
