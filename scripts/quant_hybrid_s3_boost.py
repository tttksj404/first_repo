#!/usr/bin/env python3
"""Hybrid S3 + boosted-long mode.

Logic:
  - Default mode: X1 signals (rsi30/70 + macd) → lev 1.0x ($50 notional)
  - Boost mode: X4-tight signals (rsi25 long, vol≥1.3, macd) → lev 3.0x ($150 notional)
    * Only on LONG side (per user request "강한 롱 신호 시 부스트")
  - Both signals on top-5 alts (OP/NEAR/SUI/ETH/UNI)

Compare:
  - Baseline S3: X1 lev 1.5x always
  - Hybrid: X1 lev 1x + X4-long lev 3x
  - Symmetric boost: X1 lev 1x + X4 (long+short) lev 3x

Funding cost included: 0.01%/8h × hold_hours/8 × notional
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "quant_runtime" / "historical"
OUT = ROOT / "quant_runtime" / "hybrid_s3_boost.json"

NOTIONAL_BASE = 50.0   # base notional (lev 1x on $50 equity)
COST_RT = 0.0012
FUNDING_8H = 0.0001
EQUITY = 50.0


def load_1h(symbol: str) -> np.ndarray:
    path = HIST / symbol / "1h.json"
    raw = json.loads(path.read_text())
    return np.array(
        [
            [r["open_time"], r["open_price"], r["high_price"], r["low_price"], r["close_price"], r.get("base_volume", 0.0)]
            for r in raw
        ],
        dtype=np.float64,
    )


def compute_indicators(arr: np.ndarray):
    close = arr[:, 4]
    high = arr[:, 2]
    low = arr[:, 3]
    vol = arr[:, 5]
    delta = np.diff(close, prepend=close[0])
    up = np.maximum(delta, 0)
    dn = np.maximum(-delta, 0)
    rsi = np.zeros_like(close)
    avg_up = avg_dn = 0.0
    for i in range(1, len(close)):
        if i <= 14:
            avg_up = np.mean(up[1 : i + 1])
            avg_dn = np.mean(dn[1 : i + 1])
        else:
            avg_up = (avg_up * 13 + up[i]) / 14
            avg_dn = (avg_dn * 13 + dn[i]) / 14
        rsi[i] = 100 if avg_dn == 0 else 100 - 100 / (1 + avg_up / avg_dn)

    def ema(x, period):
        a = 2.0 / (period + 1)
        out = np.empty_like(x)
        out[0] = x[0]
        for i in range(1, len(x)):
            out[i] = a * x[i] + (1 - a) * out[i - 1]
        return out

    ema12 = ema(close, 12)
    ema26 = ema(close, 26)
    macd = ema12 - ema26
    macd_sig = ema(macd, 9)
    prev_close = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    atr = ema(tr, 14)
    vol_ma = np.zeros_like(vol)
    for i in range(len(vol)):
        s = max(0, i - 20)
        vol_ma[i] = np.mean(vol[s : i + 1]) if i > 0 else vol[i]
    vol_r = np.where(vol_ma > 0, vol / vol_ma, 1.0)
    return rsi, macd, macd_sig, atr, vol_r


@dataclass
class Trade:
    symbol: str
    side: int          # 1=long, -1=short
    pnl_usd: float     # realized PnL on NOTIONAL_BASE notional with cost+funding
    boost: bool        # whether this trade qualifies for boost mode
    boost_long: bool   # whether boost-long applies (long side only)
    hold_hours: int
    bar_idx: int


def collect_trades(arr, ind, symbol: str, idx_start: int = 0, idx_end: int | None = None,
                   extra_bps: float = 0.0) -> list[Trade]:
    """Collect all X1-signal trades, tagging which ones also qualify as X4-tight."""
    rsi, macd, macd_sig, atr, vol_r = ind
    close = arr[:, 4]
    high = arr[:, 2]
    low = arr[:, 3]
    if idx_end is None:
        idx_end = len(close)
    trades: list[Trade] = []
    cooldown = 0
    HOLD = 24
    TP_ATR = 0.5
    SL_ATR = 3.0
    end = min(idx_end, len(close) - HOLD - 2)
    i = max(idx_start, 60)
    while i < end:
        if i < cooldown:
            i += 1
            continue
        # X1: rsi 30/70 + macd
        x1_long = rsi[i] <= 30 and macd[i] > macd_sig[i]
        x1_short = rsi[i] >= 70 and macd[i] < macd_sig[i]
        if not x1_long and not x1_short:
            i += 1
            continue
        side = 1 if x1_long else -1
        # X4-tight: rsi 25 + macd + vol ≥ 1.3 (subset of X1)
        x4_long = rsi[i] <= 25 and macd[i] > macd_sig[i] and vol_r[i] >= 1.3
        x4_short = rsi[i] >= 70 and macd[i] < macd_sig[i] and vol_r[i] >= 1.3
        is_boost = (side == 1 and x4_long) or (side == -1 and x4_short)
        is_boost_long = side == 1 and x4_long
        e = i + 1
        if e >= len(close):
            break
        entry_px = arr[e, 1]
        if entry_px <= 0 or atr[i] <= 0:
            i += 1
            continue
        tp_px = entry_px + side * TP_ATR * atr[i]
        sl_px = entry_px - side * SL_ATR * atr[i]
        exit_px = None
        exit_k = None
        for k in range(e, min(e + HOLD, len(close))):
            hi, lo = high[k], low[k]
            hit_sl = (lo <= sl_px) if side == 1 else (hi >= sl_px)
            hit_tp = (hi >= tp_px) if side == 1 else (lo <= tp_px)
            if hit_sl and hit_tp:
                exit_px = sl_px
                exit_k = k
                break
            if hit_tp:
                exit_px = tp_px
                exit_k = k
                break
            if hit_sl:
                exit_px = sl_px
                exit_k = k
                break
        if exit_px is None:
            exit_k = min(e + HOLD - 1, len(close) - 1)
            exit_px = close[exit_k]
        hold_hours = (exit_k - e) + 1
        roe = side * (exit_px - entry_px) / entry_px
        # Costs: fee + slippage + funding
        fee = NOTIONAL_BASE * (COST_RT + 2 * extra_bps / 10000.0)
        funding = NOTIONAL_BASE * FUNDING_8H * (hold_hours // 8)
        pnl = NOTIONAL_BASE * roe - fee - funding
        trades.append(Trade(symbol, side, pnl, is_boost, is_boost_long, hold_hours, e))
        i = e + 1
        cooldown = i + 2
    return trades


def evaluate_mode(trades: list[Trade], lev_normal: float, lev_boost: float, boost_filter: str) -> dict:
    """Apply leverage by mode and return aggregated stats.

    boost_filter: 'long_only' | 'symmetric' | 'none'
    """
    pnls: list[float] = []
    for t in trades:
        if boost_filter == "none" or not t.boost:
            lev = lev_normal
        elif boost_filter == "long_only":
            lev = lev_boost if t.boost_long else lev_normal
        elif boost_filter == "symmetric":
            lev = lev_boost if t.boost else lev_normal
        else:
            lev = lev_normal
        pnls.append(t.pnl_usd * lev)
    n = len(pnls)
    wins = sum(1 for x in pnls if x > 0)
    wr = wins / n if n else 0
    total = sum(pnls)
    win_sum = sum(x for x in pnls if x > 0)
    loss_abs = sum(abs(x) for x in pnls if x <= 0)
    pf = win_sum / loss_abs if loss_abs > 0 else float("inf")
    # Equity curve drawdown
    eq = np.cumsum(pnls)
    peak = np.maximum.accumulate(eq) if len(eq) else np.array([0])
    dd = (peak - eq).max() if len(eq) else 0
    # MC ruin
    arr = np.array(pnls, dtype=np.float64)
    rng = np.random.default_rng(42)
    ruin = 0
    final_eqs = []
    for _ in range(5000):
        order = rng.permutation(len(arr))
        e = EQUITY
        m = e
        for j in order:
            e += arr[j]
            if e < m:
                m = e
        final_eqs.append(e)
        if m <= EQUITY * 0.5:
            ruin += 1
    return {
        "n": n,
        "wr": round(wr, 3),
        "pf": round(pf, 3) if math.isfinite(pf) else None,
        "total_pnl_usd": round(total, 2),
        "annual_return_pct_50equity": round(total / EQUITY * 100, 1),
        "max_dd_usd": round(float(dd), 2),
        "mc_ruin_pct": round(ruin / 5000 * 100, 2),
        "median_final_eq": round(float(np.median(final_eqs)), 2),
        "p5_min_eq": round(float(np.percentile(final_eqs, 5)), 2),
    }


def main():
    t0 = time.time()
    universe = ["OPUSDT", "NEARUSDT", "SUIUSDT", "ETHUSDT", "UNIUSDT"]
    data = {}
    for s in universe:
        a = load_1h(s)
        ind = compute_indicators(a)
        data[s] = (a, ind)
    n_bars = len(data[universe[0]][0])
    split_idx = int(n_bars * 0.7)
    print(f"Loaded {len(universe)} symbols × 1h × {n_bars} bars")
    print(f"Universe: {universe}")
    print()

    # Collect trades full-year and OOS test, with 0bps and 5bps
    all_trades_full: list[Trade] = []
    all_trades_test_0: list[Trade] = []
    all_trades_test_5: list[Trade] = []
    for s in universe:
        a, ind = data[s]
        all_trades_full.extend(collect_trades(a, ind, s, 0, n_bars, extra_bps=0))
        all_trades_test_0.extend(collect_trades(a, ind, s, split_idx, n_bars, extra_bps=0))
        all_trades_test_5.extend(collect_trades(a, ind, s, split_idx, n_bars, extra_bps=5))

    n_total = len(all_trades_full)
    n_boost = sum(1 for t in all_trades_full if t.boost)
    n_boost_long = sum(1 for t in all_trades_full if t.boost_long)
    n_long = sum(1 for t in all_trades_full if t.side == 1)
    n_short = sum(1 for t in all_trades_full if t.side == -1)
    print(f"Total X1 trades (1yr): {n_total}  long={n_long} short={n_short}")
    print(f"  X4-tight (boost): {n_boost} ({n_boost/n_total*100:.1f}%)")
    print(f"  X4-tight LONG only: {n_boost_long}")
    print()

    modes = [
        ("M1_baseline_lev1x", "Baseline X1 lev 1x always (no boost)", 1.0, 1.0, "none"),
        ("M2_baseline_lev1.5x", "Baseline X1 lev 1.5x always (current S3)", 1.5, 1.5, "none"),
        ("M3_hybrid_long_only", "X1 lev 1x + X4-LONG boost lev 3x", 1.0, 3.0, "long_only"),
        ("M4_hybrid_long_lev2x", "X1 lev 1x + X4-LONG boost lev 2x (conservative boost)", 1.0, 2.0, "long_only"),
        ("M5_hybrid_symmetric", "X1 lev 1x + X4 (long+short) lev 3x", 1.0, 3.0, "symmetric"),
        ("M6_hybrid_aggressive", "X1 lev 1.5x + X4-LONG boost lev 4x", 1.5, 4.0, "long_only"),
        ("M7_hybrid_X1_15x_X4_25x", "X1 lev 1.5x + X4-LONG boost lev 2.5x", 1.5, 2.5, "long_only"),
    ]

    results = []
    print("=" * 100)
    print(f"{'Mode':30s} {'N':>4s} {'WR':>5s} {'PF':>5s} {'Total$':>8s} {'%/yr':>7s} {'maxDD':>7s} {'ruin%':>6s}")
    print("=" * 100)
    for mid, mlabel, ln, lb, bf in modes:
        full = evaluate_mode(all_trades_full, ln, lb, bf)
        test_0 = evaluate_mode(all_trades_test_0, ln, lb, bf)
        test_5 = evaluate_mode(all_trades_test_5, ln, lb, bf)
        rec = {
            "id": mid,
            "label": mlabel,
            "lev_normal": ln,
            "lev_boost": lb,
            "boost_filter": bf,
            "full_year": full,
            "test_0bps": test_0,
            "test_5bps": test_5,
        }
        results.append(rec)
        print(f"{mid:30s} {full['n']:>4d} {full['wr']:>5.3f} {full['pf']!s:>5s} ${full['total_pnl_usd']:>7.2f} {full['annual_return_pct_50equity']:>6.1f}% ${full['max_dd_usd']:>6.2f} {full['mc_ruin_pct']:>5.1f}% | TEST 5bps ${test_5['total_pnl_usd']:>+6.2f}")

    # Save
    OUT.write_text(
        json.dumps(
            {
                "universe": universe,
                "n_total_trades": n_total,
                "n_boost_long": n_boost_long,
                "n_boost_total": n_boost,
                "modes": results,
            },
            indent=2,
            default=str,
        )
    )
    print()
    print(f"\nElapsed: {time.time()-t0:.1f}s, saved: {OUT}")


if __name__ == "__main__":
    main()
