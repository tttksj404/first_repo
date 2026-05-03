#!/usr/bin/env python3
"""WR 80% feasibility search.

Backtests an asymmetric-TP/SL mean-reversion strategy across a parameter grid
on 1-year 5m OHLCV (BTC/ETH/SOL/XRP/DOGE). Reports each variant's win rate,
trade count, average win/loss, profit factor, total PnL, and whether WR>=0.80
is achieved. Designed to honestly answer: can we get to WR 80% on real data?

Strategy intuition:
- z = (close - EMA20) / ATR14
- entry when |z| >= z_thr AND ADX14 <= adx_max (mean-reversion regime only)
- direction: contrarian (z>0 → short, z<0 → long)
- TP at tp_mult * ATR away, SL at sl_mult * ATR away
- timeout exit after hold_bars

PnL model honors the global rule: pnl = margin * (roe_pct/100) - fee - funding
At leverage = 1, margin = notional, so equivalent to notional*roe%.
We use leverage=1 here (search is about WR mechanism, not leverage stacking).

Cost model: 0.12% RT fee, no funding drag (1h max hold << 8h funding window).

Output: quant_runtime/wr80_search_summary.json with full variant table.
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
OUT = ROOT / "quant_runtime" / "wr80_extreme_summary.json"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
COST_RT = 0.0012  # 0.12% RT
NOTIONAL = 100.0  # $100 per trade (fixed; leverage=1)


def load_5m(symbol: str) -> np.ndarray:
    """Return [n, 5] array: open_time, open, high, low, close."""
    path = HIST / symbol / "5m.json"
    raw = json.loads(path.read_text())
    arr = np.array(
        [
            [r["open_time"], r["open_price"], r["high_price"], r["low_price"], r["close_price"]]
            for r in raw
        ],
        dtype=np.float64,
    )
    return arr


def compute_indicators(arr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (ema20, atr14, adx14) aligned to bars."""
    close = arr[:, 4]
    high = arr[:, 2]
    low = arr[:, 3]

    # EMA20
    alpha_ema = 2.0 / (20 + 1)
    ema = np.empty_like(close)
    ema[0] = close[0]
    for i in range(1, len(close)):
        ema[i] = alpha_ema * close[i] + (1 - alpha_ema) * ema[i - 1]

    # ATR14 (Wilder)
    prev_close = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    atr = np.empty_like(tr)
    atr[0] = tr[0]
    alpha_atr = 1.0 / 14
    for i in range(1, len(tr)):
        atr[i] = alpha_atr * tr[i] + (1 - alpha_atr) * atr[i - 1]

    # ADX14 simplified (Wilder)
    up = high[1:] - high[:-1]
    down = low[:-1] - low[1:]
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    plus_dm = np.concatenate(([0.0], plus_dm))
    minus_dm = np.concatenate(([0.0], minus_dm))

    plus_di_smooth = np.empty_like(close)
    minus_di_smooth = np.empty_like(close)
    atr_for_adx = np.copy(atr)
    plus_di_smooth[0] = plus_dm[0]
    minus_di_smooth[0] = minus_dm[0]
    for i in range(1, len(close)):
        plus_di_smooth[i] = (1 - alpha_atr) * plus_di_smooth[i - 1] + alpha_atr * plus_dm[i]
        minus_di_smooth[i] = (1 - alpha_atr) * minus_di_smooth[i - 1] + alpha_atr * minus_dm[i]

    eps = 1e-12
    plus_di = 100.0 * plus_di_smooth / (atr_for_adx + eps)
    minus_di = 100.0 * minus_di_smooth / (atr_for_adx + eps)
    dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di + eps)
    adx = np.empty_like(dx)
    adx[0] = dx[0]
    for i in range(1, len(dx)):
        adx[i] = (1 - alpha_atr) * adx[i - 1] + alpha_atr * dx[i]
    return ema, atr, adx


@dataclass
class Variant:
    z_thr: float
    adx_max: float
    tp_mult: float
    sl_mult: float
    hold_bars: int


def simulate(
    arr: np.ndarray,
    ema: np.ndarray,
    atr: np.ndarray,
    adx: np.ndarray,
    v: Variant,
) -> tuple[int, int, float, float, float, float]:
    """Return (n_trades, n_wins, total_pnl, avg_win, avg_loss, profit_factor)."""
    n = len(arr)
    wins = 0
    losses = 0
    pnl_sum = 0.0
    win_sum = 0.0
    loss_sum = 0.0
    profit_sum = 0.0
    loss_abs_sum = 0.0
    fee = NOTIONAL * COST_RT

    in_position = False
    cooldown_until = -1
    i = 30  # warmup
    while i < n - v.hold_bars - 2:
        if in_position or i < cooldown_until:
            i += 1
            continue
        if atr[i] <= 0 or ema[i] <= 0:
            i += 1
            continue
        z = (arr[i, 4] - ema[i]) / atr[i]
        if abs(z) < v.z_thr:
            i += 1
            continue
        # adx_max field is reused as adx_min for momentum (require trending)
        if adx[i] < v.adx_max:
            i += 1
            continue
        # Entry next bar open
        entry_idx = i + 1
        entry_px = arr[entry_idx, 1]
        if entry_px <= 0:
            i += 1
            continue
        side = 1 if z > 0 else -1  # MOMENTUM (trend follow)
        atr_at_entry = atr[i]
        tp_dist = v.tp_mult * atr_at_entry
        sl_dist = v.sl_mult * atr_at_entry
        if tp_dist <= 0 or sl_dist <= 0:
            i += 1
            continue
        tp_px = entry_px + side * tp_dist
        sl_px = entry_px - side * sl_dist
        # Walk forward checking each bar's high/low
        exit_px = None
        outcome = None  # 'tp', 'sl', 'timeout'
        for k in range(entry_idx, min(entry_idx + v.hold_bars, n)):
            hi = arr[k, 2]
            lo = arr[k, 3]
            if side == 1:
                # long: SL hit if low <= sl_px, TP hit if high >= tp_px
                hit_sl = lo <= sl_px
                hit_tp = hi >= tp_px
            else:
                hit_sl = hi >= sl_px
                hit_tp = lo <= tp_px
            if hit_sl and hit_tp:
                # ambiguous: assume SL fills first (worst case, conservative)
                exit_px = sl_px
                outcome = "sl"
                break
            if hit_tp:
                exit_px = tp_px
                outcome = "tp"
                break
            if hit_sl:
                exit_px = sl_px
                outcome = "sl"
                break
        if exit_px is None:
            exit_idx = min(entry_idx + v.hold_bars - 1, n - 1)
            exit_px = arr[exit_idx, 4]
            outcome = "timeout"

        roe_pct = side * (exit_px - entry_px) / entry_px * 100.0
        pnl = NOTIONAL * (roe_pct / 100.0) - fee
        pnl_sum += pnl
        if pnl > 0:
            wins += 1
            win_sum += pnl
            profit_sum += pnl
        else:
            losses += 1
            loss_sum += pnl
            loss_abs_sum += abs(pnl)

        # advance and cooldown 3 bars
        i = entry_idx + 1
        cooldown_until = i + 3
        in_position = False  # we don't carry positions

    n_trades = wins + losses
    avg_win = win_sum / wins if wins > 0 else 0.0
    avg_loss = loss_sum / losses if losses > 0 else 0.0
    pf = profit_sum / loss_abs_sum if loss_abs_sum > 0 else float("inf") if profit_sum > 0 else 0.0
    return n_trades, wins, pnl_sum, avg_win, avg_loss, pf


def main() -> None:
    t_start = time.time()
    print("Loading historical 5m bars...")
    data = {}
    for sym in SYMBOLS:
        a = load_5m(sym)
        ema, atr, adx = compute_indicators(a)
        data[sym] = (a, ema, atr, adx)
        print(f"  {sym}: n={len(a)} bars, span={(a[-1,0]-a[0,0])/86400000:.1f} days")

    grid = []
    # Extreme asymmetric ratio sweep — does WR 80% appear anywhere?
    for z_thr in [1.0, 1.5, 2.0, 2.5]:
        for adx_max in [15.0, 25.0]:  # used as adx_MIN
            for tp_mult in [0.05, 0.08, 0.10, 0.15, 0.20]:
                for sl_mult in [3.0, 5.0, 7.0, 10.0, 15.0]:
                    for hold_bars in [12, 24, 48]:
                        if tp_mult >= sl_mult:
                            continue
                        grid.append(Variant(z_thr, adx_max, tp_mult, sl_mult, hold_bars))

    print(f"Grid size: {len(grid)} variants × {len(SYMBOLS)} symbols")
    print()

    rows = []
    for idx, v in enumerate(grid):
        agg_trades = 0
        agg_wins = 0
        agg_pnl = 0.0
        agg_win_sum = 0.0
        agg_loss_sum = 0.0
        agg_profit = 0.0
        agg_loss_abs = 0.0
        for sym in SYMBOLS:
            a, ema, atr, adx = data[sym]
            n, w, pnl, avg_w, avg_l, pf = simulate(a, ema, atr, adx, v)
            agg_trades += n
            agg_wins += w
            agg_pnl += pnl
            agg_win_sum += avg_w * w
            agg_loss_sum += avg_l * (n - w)
            agg_profit += avg_w * w
            agg_loss_abs += abs(avg_l) * (n - w)
        wr = agg_wins / agg_trades if agg_trades > 0 else 0.0
        avg_win = agg_win_sum / agg_wins if agg_wins > 0 else 0.0
        avg_loss = agg_loss_sum / max(agg_trades - agg_wins, 1) if agg_trades > agg_wins else 0.0
        pf = agg_profit / agg_loss_abs if agg_loss_abs > 0 else float("inf") if agg_profit > 0 else 0.0
        rows.append(
            {
                "z_thr": v.z_thr,
                "adx_max": v.adx_max,
                "tp_mult": v.tp_mult,
                "sl_mult": v.sl_mult,
                "hold_bars": v.hold_bars,
                "n_trades": agg_trades,
                "wins": agg_wins,
                "win_rate": round(wr, 4),
                "total_pnl_usd": round(agg_pnl, 2),
                "avg_win_usd": round(avg_win, 4),
                "avg_loss_usd": round(avg_loss, 4),
                "profit_factor": round(pf, 3) if math.isfinite(pf) else None,
                "label": f"z{v.z_thr}|adx{v.adx_max}|tp{v.tp_mult}|sl{v.sl_mult}|h{v.hold_bars}",
            }
        )
        if idx % 25 == 0:
            elapsed = time.time() - t_start
            print(
                f"  [{idx + 1:3d}/{len(grid)}] WR={wr:.3f} N={agg_trades:>6d} pnl={agg_pnl:+9.2f} pf={pf:.2f}  ({elapsed:.0f}s)"
            )

    # Rank
    rows.sort(key=lambda r: -r["win_rate"])
    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "symbols": SYMBOLS,
        "notional_usd": NOTIONAL,
        "cost_rt": COST_RT,
        "n_variants": len(rows),
        "wr80_count": sum(1 for r in rows if r["win_rate"] >= 0.80),
        "wr75_count": sum(1 for r in rows if r["win_rate"] >= 0.75),
        "wr70_count": sum(1 for r in rows if r["win_rate"] >= 0.70),
        "wr60_count": sum(1 for r in rows if r["win_rate"] >= 0.60),
        "best_pnl": max(rows, key=lambda r: r["total_pnl_usd"]),
        "best_wr": rows[0],
        "variants": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2, default=str))
    print()
    print("=== SUMMARY ===")
    print(f"variants: {len(rows)}, WR>=80%: {summary['wr80_count']}, WR>=75%: {summary['wr75_count']}, WR>=70%: {summary['wr70_count']}, WR>=60%: {summary['wr60_count']}")
    print()
    print("Top 10 by WR:")
    for r in rows[:10]:
        print(
            f"  WR={r['win_rate']:.3f} N={r['n_trades']:>5d} pnl={r['total_pnl_usd']:+9.2f} pf={r['profit_factor']}  {r['label']}"
        )
    print()
    print("Top 5 by total PnL:")
    by_pnl = sorted(rows, key=lambda r: -r["total_pnl_usd"])[:5]
    for r in by_pnl:
        print(
            f"  pnl={r['total_pnl_usd']:+9.2f} WR={r['win_rate']:.3f} N={r['n_trades']:>5d} pf={r['profit_factor']}  {r['label']}"
        )
    print(f"\nElapsed: {time.time() - t_start:.1f}s")
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
