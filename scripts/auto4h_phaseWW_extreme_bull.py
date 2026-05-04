#!/usr/bin/env python3
"""Phase WW: Extreme bull stress (+50% BTC over 90 days).

Phase UU showed dataset only spans +21.4% as max bull fold.
Question: do shorts survive a 2017/2020-style +50% in 90d melt-up?

Synthesis approach (preserves vol structure):
  amplified_log_ret[i] = bull_log_ret[i] × bull_amp_factor
  amplified_close[i+1] = amplified_close[i] * exp(amplified_log_ret[i])
  amplified_high/low scaled proportionally

We run the 6 shorts (Phase VV cap=4 applied) over Fold 1 bull amplified to
target +50%. Outcome: total loss, # SL hits, worst day, # bars short was open.

If portfolio loss > -$300 → kill-switch triggers (-15% DD on $50 cap).
If portfolio loss > -$150 → ACCEPTABLE (cap survives).
If portfolio loss < -$50 → ROBUST (shorts pause naturally via bear_regime gate).
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import load_1h, compute_indicators
from quant_phase15_signal_library import add_extra_features
from quant_phase16_robustness import add_obv
from auto4h_phaseQ_short_side import SHORT_SIGNALS, precompute_bear_regime
from auto4h_phaseV_extra_shorts import EXTRA_SHORT_SIGNALS

ALL_SHORT = {**SHORT_SIGNALS, **EXTRA_SHORT_SIGNALS}

LEVERAGE = 10
MARGIN = 50.0
COST_RT = 0.0012
FUNDING_8H = 0.00012
SLIPPAGE_BPS = 8
LIQ_ROE = -95.0
COOLDOWN_EXIT = 12
COOLDOWN_LOSS = 24
MAX_OPEN_SHORTS = 4  # Phase VV cap

SHORTS = [
    ("eth_heikin_S", "short_heikin_cont", "ETHUSDT", -0.04, 80, -30),
    ("near_atrexp_S", "short_atr_expansion", "NEARUSDT", -0.02, 200, -40),
    ("sui_momobv_S", "short_momentum_obv", "SUIUSDT", -0.06, 200, -40),
    ("arb_rsi_S", "short_rsi_breakdown", "ARBUSDT", -0.02, 200, -40),
    ("dot_adx_S", "short_adx_trend_dn", "DOTUSDT", -0.02, 150, -35),
    ("link_adx_S", "short_adx_trend_dn", "LINKUSDT", -0.06, 200, -40),
]


def amplify_bull(df: np.ndarray, amp: float) -> np.ndarray:
    """Multiply log-returns by `amp`. df cols: ts, o, h, l, c, v."""
    df2 = df.copy()
    cl = df[:, 4].astype(float)
    op = df[:, 1].astype(float)
    hi = df[:, 2].astype(float)
    lo = df[:, 3].astype(float)
    log_ret = np.diff(np.log(cl))
    amp_log = log_ret * amp
    new_cl = np.empty_like(cl)
    new_cl[0] = cl[0]
    for i in range(len(amp_log)):
        new_cl[i+1] = new_cl[i] * np.exp(amp_log[i])
    # scale o/h/l proportionally to close shift
    scale = new_cl / cl
    df2[:, 1] = op * scale
    df2[:, 2] = hi * scale
    df2[:, 3] = lo * scale
    df2[:, 4] = new_cl
    return df2


def sim_short(ind, gate, sig_fn, start, end, mom, tp, sl, max_open_tracker):
    """Returns (trades, open_indicator_array)."""
    trades = []
    in_pos = False; entry_px = 0; entry_idx = 0
    last_exit = -1; last_loss = -1
    slip = SLIPPAGE_BPS / 10000.0
    occupancy = np.zeros(end-start+1, dtype=np.int8)
    for i in range(max(start, 50), end):
        rel = i - start
        if not in_pos:
            if last_exit >= 0 and (i - last_exit) < COOLDOWN_EXIT: continue
            if last_loss >= 0 and (i - last_loss) < COOLDOWN_LOSS: continue
            if i < len(gate) and not gate[i]: continue
            if ind["mom24"][i] > mom: continue
            if not sig_fn(ind, i): continue
            # Phase VV portfolio cap (passed via tracker)
            if max_open_tracker[rel] >= MAX_OPEN_SHORTS: continue
            entry_px = ind["close"][i] * (1 - slip)
            entry_idx = i; in_pos = True
        else:
            occupancy[rel] = 1
            hi = ind["high"][i]; lo = ind["low"][i]; cl = ind["close"][i]
            roe_lo = (entry_px / lo - 1) * LEVERAGE * 100
            roe_hi = (entry_px / hi - 1) * LEVERAGE * 100
            roe_cl = (entry_px / cl - 1) * LEVERAGE * 100
            exit_roe = None; reason = None
            if roe_hi <= LIQ_ROE: exit_roe = -100; reason = "LIQ"
            elif roe_hi <= sl: exit_roe = sl; reason = "SL"
            elif roe_lo >= tp: exit_roe = tp; reason = "TP"
            elif (not sig_fn(ind, i)) and roe_cl > 0: exit_roe = roe_cl; reason = "SIG_OFF"
            if exit_roe is not None:
                hold = i - entry_idx
                notional = MARGIN * LEVERAGE
                fee = notional * COST_RT
                funding = notional * FUNDING_8H * (hold / 8)
                pnl = -MARGIN-fee if exit_roe<=-100 else MARGIN*(exit_roe/100) - fee - funding
                trades.append({"pnl": pnl, "reason": reason, "hold": hold})
                in_pos = False; last_exit = i
                if pnl < 0: last_loss = i
    return trades, occupancy


def run():
    print("Phase WW: extreme bull (+50% target)")
    universe = sorted(set([s[2] for s in SHORTS]) | {"BTCUSDT"})
    raw = {}
    for sym in universe:
        df = load_1h(sym)
        if df is None: continue
        raw[sym] = df

    # Use Fold 1 (bull +21.4%) as base. Amplify each symbol to target +50% BTC.
    # Fold 1 indices: 0 .. 9000//4 = 2250
    n_min = min(len(d) for d in raw.values())
    fold_n = n_min // 4
    s, e = 0, fold_n

    # Compute amp factor for BTC: log(1+0.50) / log(1+0.214)
    btc_cl = raw["BTCUSDT"][:, 4].astype(float)[s:e]
    base_ret = btc_cl[-1]/btc_cl[0] - 1
    target_ret = 0.50
    amp = np.log(1+target_ret) / np.log(1+base_ret)
    print(f"  base BTC fold ret = {base_ret*100:+.1f}%, target = +{target_ret*100:.0f}%, amp = {amp:.2f}x")

    # Amplify all symbols by same factor (assume cross-asset beta ~1 for the stress)
    amplified = {sym: amplify_bull(df, amp) for sym, df in raw.items()}
    cache = {}
    for sym, df in amplified.items():
        ind = compute_indicators(df); ind = add_extra_features(ind); ind = add_obv(ind)
        cache[sym] = ind
    btc_bear = precompute_bear_regime(cache["BTCUSDT"])
    n_min = min(len(c["close"]) for c in cache.values())
    e = min(e, n_min)

    # Confirm new BTC fold return
    new_btc_ret = cache["BTCUSDT"]["close"][e-1]/cache["BTCUSDT"]["close"][s] - 1
    print(f"  amplified BTC fold ret: {new_btc_ret*100:+.1f}%")

    # Track simultaneous open count across shorts
    max_open_tracker = np.zeros(e-s+1, dtype=np.int8)
    all_trades = {}; all_occ = {}
    # iterate strats; tracker accumulates as we go (approximation — not perfectly serialized)
    for sid, sig, sym, mom, tp, sl in SHORTS:
        if sym not in cache: continue
        trades, occ = sim_short(cache[sym], btc_bear, ALL_SHORT[sig],
                                 s, e, mom, tp, sl, max_open_tracker)
        all_trades[sid] = trades
        all_occ[sid] = occ
        max_open_tracker += occ
        net = sum(t["pnl"] for t in trades)
        n_sl = sum(1 for t in trades if t["reason"]=="SL")
        n_liq = sum(1 for t in trades if t["reason"]=="LIQ")
        print(f"  {sid}: n={len(trades)} net=${net:+.0f}  SL={n_sl} LIQ={n_liq}")

    total_net = sum(sum(t["pnl"] for t in trades) for trades in all_trades.values())
    total_n = sum(len(t) for t in all_trades.values())
    total_sl = sum(sum(1 for t in trades if t["reason"]=="SL") for trades in all_trades.values())
    total_liq = sum(sum(1 for t in trades if t["reason"]=="LIQ") for trades in all_trades.values())
    max_concurrent = int(max_open_tracker.max())
    cap_blocked_pct = float((max_open_tracker >= MAX_OPEN_SHORTS).mean() * 100)

    print(f"\n=== Extreme bull (+{target_ret*100:.0f}% BTC / 94d) summary ===")
    print(f"  total trades: {total_n}")
    print(f"  total net:    ${total_net:+.2f}")
    print(f"  SL hits:      {total_sl}")
    print(f"  LIQ hits:     {total_liq}")
    print(f"  max concurrent opens: {max_concurrent}")
    print(f"  cap-blocked bars: {cap_blocked_pct:.1f}%")

    if total_net >= -50:
        verdict = f"ROBUST — extreme +50% bull only ${total_net:+.0f}; bear_regime gate + cap effective"
    elif total_net >= -150:
        verdict = f"ACCEPTABLE — ${total_net:+.0f} loss; within $50-cap kill-switch budget"
    elif total_net >= -300:
        verdict = f"FRAGILE — ${total_net:+.0f}; kill-switch triggers but no portfolio wipe"
    else:
        verdict = f"BREAKING — ${total_net:+.0f} > $300 loss; full halt + manual restart needed"
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseWW_extreme_bull.json")
    with open(out_path, "w") as f:
        json.dump({"target_btc_ret_pct": target_ret*100, "amp_factor": amp,
                   "actual_btc_ret_pct": new_btc_ret*100,
                   "total_trades": total_n, "total_net": total_net,
                   "total_sl": total_sl, "total_liq": total_liq,
                   "max_concurrent": max_concurrent,
                   "cap_blocked_pct": cap_blocked_pct,
                   "per_strategy": {sid: {"n": len(t), "net": sum(x["pnl"] for x in t)}
                                    for sid, t in all_trades.items()},
                   "verdict": verdict}, f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
