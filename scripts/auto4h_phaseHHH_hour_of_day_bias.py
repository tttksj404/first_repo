#!/usr/bin/env python3
"""Phase HHH: Trading hour-of-day bias analysis.

Group all trades (entry timestamps) into UTC hour buckets 0-23.
For each hour:
  - n_entries (how often bot fires)
  - net pnl
  - WR%
  - avg_pnl/trade

Look for "dead hours" (zero edge) or "death hours" (negative EV).
If a hour has materially negative EV, recommend an entry-hour filter.

The bot trades 1h candles but the BTC regime gate evaluates hourly close,
so theoretically all 24 hours are eligible. Real markets have liquidity
patterns (Asia open / EU open / NY open) that may produce hour bias.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
from collections import defaultdict
import datetime as dt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def run():
    print("Phase HHH: Trading hour-of-day bias analysis")

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
        trades = []  # (pnl, entry_ts_ms)
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
        ts_arr = raw_ts[sym]
        ts = sim_with_entry_ts(cache[sym], ts_arr, btc_long, SIGNALS[sig], mom, tp, sl, "long", LONG_M)
        all_trades.extend(ts)
    for sid, sig, sym, mom, tp, sl in SHORT_SET:
        if sym not in cache: continue
        ts_arr = raw_ts[sym]
        ts = sim_with_entry_ts(cache[sym], ts_arr, btc_bear, ALL_SHORT[sig], mom, tp, sl, "short", SHORT_M)
        all_trades.extend(ts)

    by_hour = defaultdict(list)  # hour -> [pnls]
    for pnl, ts_ms in all_trades:
        h = dt.datetime.fromtimestamp(ts_ms / 1000.0, tz=dt.timezone.utc).hour
        by_hour[h].append(pnl)

    n_total = len(all_trades)
    print(f"\n  Total trades: {n_total}")
    print(f"\n  {'hour_UTC':>4} {'n':>4} {'%share':>7} {'wins':>4} {'WR%':>6} {'net$':>8} {'avg$/tr':>8} {'verdict'}")
    print(f"  {'-'*4} {'-'*4} {'-'*7} {'-'*4} {'-'*6} {'-'*8} {'-'*8} {'-'*7}")

    rows = []
    for h in range(24):
        pnls = by_hour.get(h, [])
        n = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        net = sum(pnls)
        wr = wins / n * 100 if n else 0
        avg = net / n if n else 0
        share = n / n_total * 100 if n_total else 0
        if n == 0: v = "DEAD"
        elif net < 0: v = "LOSING"
        elif n < 5: v = "THIN"
        elif avg > 1.5: v = "STRONG"
        else: v = "OK"
        rows.append({"hour": h, "n": n, "share": share, "wins": wins,
                     "wr": wr, "net": net, "avg": avg, "verdict": v})
        print(f"  {h:>3}  {n:>4} {share:>5.1f}% {wins:>4} {wr:>5.1f}% ${net:>+6.2f} ${avg:>+6.2f} {v}")

    # Identify worst hours
    losing_hrs = [r for r in rows if r["verdict"] == "LOSING"]
    strong_hrs = [r for r in rows if r["verdict"] == "STRONG"]
    dead_hrs = [r for r in rows if r["verdict"] == "DEAD"]

    print(f"\n=== Hour-of-day bias summary ===")
    print(f"  STRONG hours (avg ≥ $1.5): {len(strong_hrs)}/24  → {[r['hour'] for r in strong_hrs]}")
    print(f"  LOSING hours (net < 0):    {len(losing_hrs)}/24  → {[r['hour'] for r in losing_hrs]}")
    print(f"  DEAD hours (n=0):          {len(dead_hrs)}/24")

    # Entry concentration
    sorted_by_share = sorted(rows, key=lambda r: -r["share"])
    top6 = sorted_by_share[:6]
    top6_share = sum(r["share"] for r in top6)
    print(f"  Top-6 entry hours capture: {top6_share:.1f}% of all trades  → hours {[r['hour'] for r in top6]}")

    # Verdict: filter recommendation
    if len(losing_hrs) == 0:
        verdict = "NO BIAS — all 24 hours profitable. No entry-hour filter needed."
    elif len(losing_hrs) <= 2:
        worst = min(rows, key=lambda r: r["net"])
        verdict = f"WEAK BIAS — {len(losing_hrs)} hours net-negative (worst h={worst['hour']} ${worst['net']:+.2f}). Filter optional."
    else:
        verdict = f"BIAS DETECTED — {len(losing_hrs)} losing hours. Consider entry-hour blocklist."
    print(f"\n  Verdict: {verdict}")

    out_path = Path("quant_runtime/output/auto4h/phaseHHH_hour_of_day_bias.json")
    with open(out_path, "w") as f:
        json.dump({"rows": rows, "n_strong": len(strong_hrs),
                   "n_losing": len(losing_hrs), "n_dead": len(dead_hrs),
                   "top6_share_pct": top6_share, "verdict": verdict},
                  f, indent=2, default=str)
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    run()
