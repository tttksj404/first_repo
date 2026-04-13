"""Backtest: Hurst + HAR-RV regime filter on top of existing signals.

Compares:
  A) BASELINE — current reversal strategy, no regime filter
  B) HURST-only — add Hurst regime filter
  C) HAR-RV only — add volatility regime filter
  D) HURST + HAR-RV — full regime filter

Uses 358d ETH+SOL 5m data. Reports WR, PF, PnL, walk-forward 4-fold.
"""
from __future__ import annotations

import bisect
import json
import os
import pickle
import sys
from pathlib import Path
from statistics import median

sys.path.insert(0, "/home/user/first_repo")
os.environ.setdefault("STRATEGY_OVERRIDE_PATH", "quant_runtime/artifacts/strategy_override.approved.json")
os.environ.setdefault("STRATEGY_PROFILE", "live-ultra-aggressive")
os.environ.setdefault("EXCHANGE", "bitget")

from quant_binance.features.regime_filter import (
    hurst_rs,
    har_rv_forecast,
    classify_regime,
    vol_regime,
)
from quant_binance.data.historical_download import load_historical_klines
from quant_binance.data.rest_seed import _parse_kline


def load_5m(sym: str):
    data_dir = Path("quant_runtime/historical")
    k5m = load_historical_klines(data_dir=data_dir, symbol=sym, interval="5m")
    return sorted([_parse_kline(sym, "5m", r) for r in k5m if r], key=lambda b: b.close_time)


def sim_trade(side, entry_price, bars_5m, tp_pct, sl_pct, max_hold_bars, leverage, cost_bps=42):
    """ROE-based sim."""
    if not bars_5m or entry_price <= 0:
        return -cost_bps / 10000
    for bar in bars_5m[:max_hold_bars]:
        if side == "long":
            best = (bar.high_price / entry_price - 1) * 100 * leverage
            worst = (bar.low_price / entry_price - 1) * 100 * leverage
            cr = (bar.close_price / entry_price - 1) * 100 * leverage
        else:
            best = -(bar.low_price / entry_price - 1) * 100 * leverage
            worst = -(bar.high_price / entry_price - 1) * 100 * leverage
            cr = -(bar.close_price / entry_price - 1) * 100 * leverage
        if worst <= -sl_pct:
            return (-sl_pct / 100) - cost_bps / 10000
        if best >= tp_pct:
            return (tp_pct / 100) - cost_bps / 10000
    return (cr / 100) - cost_bps / 10000


def main():
    print("[regime] Loading 5m bars...")
    bars = {sym: load_5m(sym) for sym in ["ETHUSDT", "SOLUSDT"]}
    for sym, b in bars.items():
        print(f"  {sym}: {len(b)} bars")

    # Precompute Hurst + HAR-RV at each decision point (every 12 bars = 1h)
    print("\n[regime] Computing Hurst + HAR-RV signals (every 1h)...")
    signals = {}  # sym → list of (ts, hurst, rv_forecast, rv_median)
    for sym, b5 in bars.items():
        print(f"  {sym}...", flush=True)
        closes = [b.close_price for b in b5]
        # Compute returns
        returns = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0:
                returns.append((closes[i] / closes[i - 1]) - 1)
            else:
                returns.append(0)

        sig_list = []
        # Evaluate every 12 bars (1h interval)
        step = 12
        for i in range(10000, len(b5), step):  # skip first 10000 bars (warmup)
            prices_window = closes[i - 500:i]  # last 500 bars for Hurst
            returns_window = returns[i - 8640:i] if i >= 8640 else returns[:i]
            hurst = hurst_rs(prices_window, min_lag=10, max_lag=100)
            rv_fc, rv_d, rv_w, rv_m = har_rv_forecast(returns_window)
            sig_list.append({
                "ts": int(b5[i].close_time.timestamp() * 1000),
                "hurst": hurst,
                "rv": rv_fc,
                "price": closes[i],
            })
        # Compute rolling median of rv for each signal
        rv_values = [s["rv"] for s in sig_list]
        median_rv = median(rv_values) if rv_values else 0
        for s in sig_list:
            s["rv_median"] = median_rv
            s["regime"] = classify_regime(s["hurst"])
            s["vol"] = vol_regime(s["rv"], median_rv)
        signals[sym] = sig_list
        print(f"    {len(sig_list)} signals, Hurst range {min(s['hurst'] for s in sig_list):.3f}-{max(s['hurst'] for s in sig_list):.3f}")

    # Distribution of regimes
    print("\n[regime] Distribution:")
    for sym, sigs in signals.items():
        r_count = {"trending": 0, "reverting": 0, "random": 0}
        v_count = {"high": 0, "normal": 0, "low": 0}
        for s in sigs:
            r_count[s["regime"]] += 1
            v_count[s["vol"]] += 1
        total = len(sigs)
        print(f"  {sym}: trending={r_count['trending']/total*100:.0f}% reverting={r_count['reverting']/total*100:.0f}% random={r_count['random']/total*100:.0f}% | vol high={v_count['high']/total*100:.0f}% low={v_count['low']/total*100:.0f}%")

    # Simulate reversal entry at each signal point
    # Reversal entry: after N bars of strong move in one direction, bet on reversal
    print("\n[regime] Running reversal backtest...")

    def reversal_signal(bars_5m, idx, lookback=24):
        """Detect reversal candidate: price moved >2% in lookback period."""
        if idx < lookback:
            return None
        past = bars_5m[idx - lookback].close_price
        now = bars_5m[idx].close_price
        if past <= 0:
            return None
        move_pct = (now / past - 1) * 100
        if move_pct > 2.0:
            return "short"  # overbought → fade
        elif move_pct < -2.0:
            return "long"  # oversold → buy dip
        return None

    strategies = {
        "A_BASELINE": lambda sig: True,
        "B_HURST_ONLY": lambda sig: sig["regime"] == "reverting",
        "C_VOL_ONLY": lambda sig: sig["vol"] in ("high", "normal"),
        "D_FULL": lambda sig: sig["regime"] == "reverting" and sig["vol"] in ("high", "normal"),
        "E_STRICT": lambda sig: sig["regime"] == "reverting" and sig["vol"] == "high",
    }

    results = {}
    for strat_name, filter_fn in strategies.items():
        all_pnls = []
        for sym, b5 in bars.items():
            sig_list = signals[sym]
            # Index signals by ts for fast lookup
            sig_ts = [s["ts"] for s in sig_list]

            # Scan for entry opportunities
            lookback = 24
            tp_pct = 20.0
            sl_pct = 15.0
            max_hold = 48 * 12  # 48h in 5m bars
            leverage = 15

            for i in range(lookback, len(b5), 12):  # hourly check
                rev = reversal_signal(b5, i, lookback)
                if rev is None:
                    continue

                # Find most recent signal
                ts = int(b5[i].close_time.timestamp() * 1000)
                idx = bisect.bisect_right(sig_ts, ts) - 1
                if idx < 0:
                    continue
                sig = sig_list[idx]
                if not filter_fn(sig):
                    continue

                # Simulate trade
                entry_price = b5[i].close_price
                future = b5[i + 1:i + 1 + max_hold]
                pnl_frac = sim_trade(rev, entry_price, future, tp_pct, sl_pct, max_hold, leverage)
                notional = 66 * 0.3 * leverage
                net_usd = pnl_frac * notional
                all_pnls.append({"sym": sym, "ts": ts, "pnl": net_usd, "side": rev})

        results[strat_name] = all_pnls

    # Report
    print(f"\n{'=' * 110}")
    print(f"  REVERSAL STRATEGY + REGIME FILTERS — comparison")
    print(f"{'=' * 110}")
    print(f"\n  {'Strategy':<15} {'Trades':>7} {'WR':>6} {'PF':>5} {'AvgPnL':>8} {'TotalPnL':>10} {'BestLong/Short':>18}")
    print(f"  {'-' * 90}")

    for name, pnls in results.items():
        if not pnls:
            print(f"  {name:<15} 0 trades")
            continue
        w = sum(1 for p in pnls if p["pnl"] > 0)
        tot = sum(p["pnl"] for p in pnls)
        gw = sum(p["pnl"] for p in pnls if p["pnl"] > 0)
        gl = abs(sum(p["pnl"] for p in pnls if p["pnl"] <= 0)) or 0.01
        longs = [p for p in pnls if p["side"] == "long"]
        shorts = [p for p in pnls if p["side"] == "short"]
        long_wr = sum(1 for p in longs if p["pnl"] > 0) / max(len(longs), 1)
        short_wr = sum(1 for p in shorts if p["pnl"] > 0) / max(len(shorts), 1)
        wr = w / len(pnls)
        pf = gw / gl
        avg = tot / len(pnls)

        # Walk-forward 4-fold
        n = len(pnls)
        q = [0, n // 4, n // 2, n * 3 // 4, n]
        wf = sum(1 for qi in range(4) if sum(p["pnl"] for p in pnls[q[qi]:q[qi + 1]]) > 0)

        tag = "★" if wf == 4 and wr >= 0.4 else ""
        print(f"  {name:<15} {len(pnls):>7} {wr * 100:>5.1f}% {pf:>5.2f} {avg:>+7.2f} {tot:>+9.2f} L{long_wr*100:>4.0f}%/{len(longs)} S{short_wr*100:>4.0f}%/{len(shorts)} WF={wf}/4 {tag}")

    # Save
    out = Path("/home/user/first_repo/quant_runtime/artifacts/regime_filter_results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = {}
    for name, pnls in results.items():
        if not pnls:
            continue
        w = sum(1 for p in pnls if p["pnl"] > 0)
        tot = sum(p["pnl"] for p in pnls)
        gw = sum(p["pnl"] for p in pnls if p["pnl"] > 0)
        gl = abs(sum(p["pnl"] for p in pnls if p["pnl"] <= 0)) or 0.01
        n = len(pnls)
        q = [0, n // 4, n // 2, n * 3 // 4, n]
        wf_folds = [round(sum(p["pnl"] for p in pnls[q[qi]:q[qi + 1]]), 2) for qi in range(4)]
        summary[name] = {
            "trades": n,
            "wr": round(w / n, 4),
            "pf": round(gw / gl, 2),
            "total_pnl": round(tot, 2),
            "wf_folds": wf_folds,
        }
    with open(out, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n[regime] Saved to {out}")


if __name__ == "__main__":
    main()
