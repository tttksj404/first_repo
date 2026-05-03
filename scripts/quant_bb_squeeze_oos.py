#!/usr/bin/env python3
"""Bollinger Band squeeze breakout strategy with OOS validation.

Alpha: low-volatility consolidation (BB width below threshold) followed by
breakout. Enter long on close > upper BB after squeeze, short on close < lower BB.
Exit on TP/SL ATR multiple or hold timeout.

Universe: 20 symbols × 1h.
Train/Test: 70/30.

Output: quant_runtime/bb_squeeze_oos_summary.json
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
OUT = ROOT / "quant_runtime" / "bb_squeeze_oos_summary.json"

NOTIONAL = 100.0
COST_RT = 0.0012

UNIVERSE_20 = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "APTUSDT", "ARBUSDT", "AVAXUSDT", "BNBUSDT",
    "DOTUSDT", "LINKUSDT", "LTCUSDT", "NEARUSDT", "OPUSDT",
    "PEPEUSDT", "SUIUSDT", "UNIUSDT", "WIFUSDT", "MATICUSDT",
]


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


def _rolling_quantile(x: np.ndarray, lookback: int, q: float) -> np.ndarray:
    """Vectorized rolling quantile via stride sliding (slower than full vectorization
    but avoids per-iter np.percentile in the simulate loop)."""
    n = len(x)
    out = np.full(n, np.nan)
    for i in range(lookback - 1, n):
        out[i] = np.percentile(x[i - lookback + 1 : i + 1], q)
    return out


def compute_bb_atr(arr: np.ndarray, bb_period: int = 20, bb_std: float = 2.0):
    close = arr[:, 4]
    high = arr[:, 2]
    low = arr[:, 3]
    n = len(close)
    # Rolling SMA + STD (vectorized via cumsum)
    csum = np.concatenate(([0], np.cumsum(close)))
    csum2 = np.concatenate(([0], np.cumsum(close * close)))
    sma = np.zeros(n)
    std = np.zeros(n)
    for i in range(n):
        s = max(0, i - bb_period + 1)
        ln = i - s + 1
        s_x = csum[i + 1] - csum[s]
        s_x2 = csum2[i + 1] - csum2[s]
        m = s_x / ln
        var = max(0.0, s_x2 / ln - m * m)
        sma[i] = m
        std[i] = math.sqrt(var)
    upper = sma + bb_std * std
    lower = sma - bb_std * std
    width = (upper - lower) / np.where(sma > 0, sma, 1.0)  # normalized BB width
    # ATR(14) via EMA
    prev_close = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    atr = np.zeros(n)
    atr[0] = tr[0]
    a = 2.0 / 15.0
    for i in range(1, n):
        atr[i] = a * tr[i] + (1 - a) * atr[i - 1]
    # Pre-compute rolling percentile of width for {50, 100} lookbacks × {10, 20, 30}%
    width_pcts: dict[tuple[int, int], np.ndarray] = {}
    for lb in (50, 100):
        for q in (10, 20, 30):
            width_pcts[(lb, q)] = _rolling_quantile(width, lb, q)
    return upper, lower, sma, width, atr, width_pcts


@dataclass
class BBV:
    width_pct: float       # squeeze: current width <= width_pct percentile of lookback
    lookback: int
    tp_atr: float
    sl_atr: float
    hold: int
    require_close_through: bool


def variant_label(v: BBV) -> str:
    return f"sq{v.width_pct}|lb{v.lookback}|tp{v.tp_atr}|sl{v.sl_atr}|h{v.hold}|ct{int(v.require_close_through)}"


def simulate(arr, bb, v: BBV, idx_start, idx_end, extra_bps=0.0):
    upper, lower, sma, width, atr, width_pcts = bb
    thr_arr = width_pcts[(v.lookback, v.width_pct)]
    close = arr[:, 4]
    high = arr[:, 2]
    low = arr[:, 3]
    fee = NOTIONAL * (COST_RT + 2 * extra_bps / 10000.0)
    wins = 0
    losses = 0
    pnl_sum = 0.0
    win_sum = 0.0
    loss_abs = 0.0
    cooldown = 0
    end = min(idx_end, len(close) - v.hold - 2)
    i = max(idx_start, max(60, v.lookback))
    while i < end:
        if i < cooldown:
            i += 1
            continue
        thr = thr_arr[i]
        if math.isnan(thr) or atr[i] <= 0:
            i += 1
            continue
        if width[i] > thr:
            i += 1
            continue
        # need a breakout: was recently inside bands, now closes above/below
        if v.require_close_through:
            long_break = close[i] > upper[i] and close[i - 1] <= upper[i - 1]
            short_break = close[i] < lower[i] and close[i - 1] >= lower[i - 1]
        else:
            long_break = close[i] > upper[i]
            short_break = close[i] < lower[i]
        if not long_break and not short_break:
            i += 1
            continue
        side = 1 if long_break else -1
        e = i + 1
        if e >= len(close):
            break
        entry_px = arr[e, 1]
        if entry_px <= 0:
            i += 1
            continue
        tp_px = entry_px + side * v.tp_atr * atr[i]
        sl_px = entry_px - side * v.sl_atr * atr[i]
        exit_px = None
        for k in range(e, min(e + v.hold, len(close))):
            hi = high[k]
            lo = low[k]
            if side == 1:
                hit_sl = lo <= sl_px
                hit_tp = hi >= tp_px
            else:
                hit_sl = hi >= sl_px
                hit_tp = lo <= tp_px
            if hit_sl and hit_tp:
                exit_px = sl_px
                break
            if hit_tp:
                exit_px = tp_px
                break
            if hit_sl:
                exit_px = sl_px
                break
        if exit_px is None:
            exit_idx = min(e + v.hold - 1, len(close) - 1)
            exit_px = close[exit_idx]
        roe = side * (exit_px - entry_px) / entry_px
        pnl = NOTIONAL * roe - fee
        pnl_sum += pnl
        if pnl > 0:
            wins += 1
            win_sum += pnl
        else:
            losses += 1
            loss_abs += abs(pnl)
        i = e + 1
        cooldown = i + 2
    n = wins + losses
    wr = wins / n if n > 0 else 0.0
    pf = win_sum / loss_abs if loss_abs > 0 else (float("inf") if win_sum > 0 else 0.0)
    return n, wins, pnl_sum, wr, pf, win_sum, loss_abs


def main() -> None:
    t0 = time.time()
    data = {}
    for s in UNIVERSE_20:
        a = load_1h(s)
        bb = compute_bb_atr(a)
        data[s] = (a, bb)
    n_bars = len(data[UNIVERSE_20[0]][0])
    split_idx = int(n_bars * 0.7)
    print(f"Loaded {len(UNIVERSE_20)} symbols × 1h × {n_bars} bars, split@{split_idx}")

    grid = []
    for wpct in [10, 20, 30]:
        for lb in [50, 100]:
            for tp in [1.0, 1.5, 2.0, 3.0]:
                for sl in [1.5, 2.0, 3.0]:
                    if tp == sl:
                        continue
                    for h in [12, 24, 48]:
                        for ct in [True, False]:
                            grid.append(BBV(wpct, lb, tp, sl, h, ct))
    print(f"Grid: {len(grid)} variants")

    rows = []
    for idx, v in enumerate(grid):
        # Train
        tr_n = tr_w = 0
        tr_pnl = 0.0
        tr_ws = tr_la = 0.0
        for s in UNIVERSE_20:
            a, bb = data[s]
            n, w, pnl, _, _, ws, la = simulate(a, bb, v, 0, split_idx)
            tr_n += n; tr_w += w; tr_pnl += pnl; tr_ws += ws; tr_la += la
        if tr_n < 30:
            continue
        train_wr = tr_w / tr_n
        train_pf = tr_ws / tr_la if tr_la > 0 else (float("inf") if tr_ws > 0 else 0.0)
        # Test
        te_n = te_w = 0
        te_pnl = 0.0
        te_ws = te_la = 0.0
        for s in UNIVERSE_20:
            a, bb = data[s]
            n, w, pnl, _, _, ws, la = simulate(a, bb, v, split_idx, n_bars)
            te_n += n; te_w += w; te_pnl += pnl; te_ws += ws; te_la += la
        test_wr = te_w / te_n if te_n > 0 else 0.0
        test_pf = te_ws / te_la if te_la > 0 else (float("inf") if te_ws > 0 else 0.0)
        rec = {
            "label": variant_label(v),
            "v": v.__dict__,
            "train": {
                "n": tr_n, "wr": round(train_wr, 4), "pnl": round(tr_pnl, 2),
                "pf": round(train_pf, 3) if math.isfinite(train_pf) else None,
            },
            "test": {
                "n": te_n, "wr": round(test_wr, 4), "pnl": round(te_pnl, 2),
                "pf": round(test_pf, 3) if math.isfinite(test_pf) else None,
            },
            "total_pnl": round(tr_pnl + te_pnl, 2),
        }
        rows.append(rec)
        if idx % 20 == 0:
            print(f"  [{idx + 1:4d}/{len(grid)}] {rec['label']}  trN={tr_n} trWR={train_wr:.3f} trPnL={tr_pnl:+.1f} | teN={te_n} teWR={test_wr:.3f} tePnL={te_pnl:+.1f}  ({time.time()-t0:.0f}s)")

    qualified = [
        r for r in rows
        if r["train"]["wr"] >= 0.55 and r["train"]["pf"] is not None and r["train"]["pf"] >= 1.1
        and r["test"]["pnl"] > 0 and r["test"]["pf"] is not None and r["test"]["pf"] >= 1.0
        and r["test"]["n"] >= 20
    ]
    qualified.sort(key=lambda r: -r["total_pnl"])
    rows.sort(key=lambda r: -r["total_pnl"])

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_symbols": len(UNIVERSE_20),
        "n_bars": n_bars,
        "n_variants": len(rows),
        "qualified_count": len(qualified),
        "elapsed_sec": round(time.time() - t0, 1),
        "top10": rows[:10],
        "qualified": qualified[:30],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))

    print()
    print(f"BB squeeze: {len(rows)} variants, {len(qualified)} OOS-qualified")
    for r in qualified[:10]:
        print(f"  TOTAL=${r['total_pnl']:+.1f} | TR WR={r['train']['wr']:.3f} pnl=${r['train']['pnl']:+.1f} PF={r['train']['pf']} | TE WR={r['test']['wr']:.3f} pnl=${r['test']['pnl']:+.1f} PF={r['test']['pf']} | {r['label']}")
    print(f"\nElapsed: {time.time() - t0:.0f}s, saved: {OUT}")


if __name__ == "__main__":
    main()
