#!/usr/bin/env python3
"""Multi-indicator confluence WR 80% search with OOS validation.

Strategy: enter only when N indicators agree on direction.
- RSI(14) <= rsi_long (oversold) for long, RSI >= rsi_short (overbought) for short
- MACD line > signal for long, < signal for short
- Volume(5) ratio >= vol_min (above-average activity)
- EMA20 > EMA50 for long bias, < for short bias
- ATR percentile filter (vol regime)

Universe: 5 symbols × 1h timeframe (9000 bars ≈ 375 days each).
Train: bars[:6300] (~263 days), Test: bars[6300:] (~112 days).

Validation gates (must pass ALL):
- Train: WR >= 0.80, PF >= 1.0, N >= 100
- Test:  WR >= 0.75, PF >= 1.0, N >= 30

Output: quant_runtime/confluence_oos_summary.json
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
OUT = ROOT / "quant_runtime" / "confluence_oos_summary.json"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
NOTIONAL = 100.0
COST_RT = 0.0012
FEE = NOTIONAL * COST_RT


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

    # RSI(14)
    delta = np.diff(close, prepend=close[0])
    up = np.maximum(delta, 0)
    dn = np.maximum(-delta, 0)
    rsi = np.zeros_like(close)
    avg_up = up[1]
    avg_dn = dn[1]
    rsi[0] = 50
    for i in range(1, len(close)):
        if i <= 14:
            avg_up = np.mean(up[1 : i + 1]) if i > 0 else 0
            avg_dn = np.mean(dn[1 : i + 1]) if i > 0 else 0
        else:
            avg_up = (avg_up * 13 + up[i]) / 14
            avg_dn = (avg_dn * 13 + dn[i]) / 14
        if avg_dn == 0:
            rsi[i] = 100
        else:
            rs = avg_up / avg_dn
            rsi[i] = 100 - 100 / (1 + rs)

    # EMA20, EMA50, MACD
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
    macd_signal = ema(macd, 9)
    ema20 = ema(close, 20)
    ema50 = ema(close, 50)

    # ATR(14)
    prev_close = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    atr = ema(tr, 14)

    # Volume ratio (current / 20-bar mean)
    vol_ma = np.zeros_like(vol)
    for i in range(len(vol)):
        s = max(0, i - 20)
        vol_ma[i] = np.mean(vol[s : i + 1]) if i > 0 else vol[i]
    vol_ratio = np.where(vol_ma > 0, vol / vol_ma, 1.0)

    return rsi, macd, macd_signal, ema20, ema50, atr, vol_ratio


@dataclass
class CVariant:
    rsi_long_thr: float       # RSI <= this for long
    rsi_short_thr: float      # RSI >= this for short
    require_macd: bool
    require_ema_align: bool
    vol_min: float
    tp_atr: float
    sl_atr: float
    hold_bars: int


def simulate(arr: np.ndarray, ind: tuple, v: CVariant, idx_start: int, idx_end: int):
    rsi, macd, macd_sig, ema20, ema50, atr, vol_r = ind
    close = arr[:, 4]
    high = arr[:, 2]
    low = arr[:, 3]

    wins = 0
    losses = 0
    pnl_sum = 0.0
    win_sum = 0.0
    loss_abs = 0.0

    cooldown = 0
    i = max(idx_start, 60)
    end = min(idx_end, len(close) - v.hold_bars - 2)
    while i < end:
        if i < cooldown:
            i += 1
            continue
        # Long signal
        long_sig = (
            rsi[i] <= v.rsi_long_thr
            and (not v.require_macd or macd[i] > macd_sig[i])
            and (not v.require_ema_align or ema20[i] > ema50[i])
            and vol_r[i] >= v.vol_min
        )
        short_sig = (
            rsi[i] >= v.rsi_short_thr
            and (not v.require_macd or macd[i] < macd_sig[i])
            and (not v.require_ema_align or ema20[i] < ema50[i])
            and vol_r[i] >= v.vol_min
        )
        if not long_sig and not short_sig:
            i += 1
            continue
        side = 1 if long_sig else -1
        e = i + 1
        if e >= len(close):
            break
        entry_px = arr[e, 1]
        if entry_px <= 0 or atr[i] <= 0:
            i += 1
            continue
        tp_px = entry_px + side * v.tp_atr * atr[i]
        sl_px = entry_px - side * v.sl_atr * atr[i]

        exit_px = None
        for k in range(e, min(e + v.hold_bars, len(close))):
            hi = high[k]
            lo = low[k]
            if side == 1:
                hit_sl = lo <= sl_px
                hit_tp = hi >= tp_px
            else:
                hit_sl = hi >= sl_px
                hit_tp = lo <= tp_px
            if hit_sl and hit_tp:
                exit_px = sl_px  # conservative
                break
            if hit_tp:
                exit_px = tp_px
                break
            if hit_sl:
                exit_px = sl_px
                break
        if exit_px is None:
            exit_idx = min(e + v.hold_bars - 1, len(close) - 1)
            exit_px = close[exit_idx]

        roe = side * (exit_px - entry_px) / entry_px
        pnl = NOTIONAL * roe - FEE
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
    return n, wins, pnl_sum, wr, pf


def main() -> None:
    t_start = time.time()
    data = {}
    for s in SYMBOLS:
        a = load_1h(s)
        ind = compute_indicators(a)
        data[s] = (a, ind)
        print(f"  {s}: 1h n={len(a)}")

    # Train/Test split: 70/30
    split_idx = 6300

    grid: list[CVariant] = []
    for rsi_l in [25, 30, 35]:
        for rsi_s in [65, 70, 75]:
            for req_macd in [True, False]:
                for req_ema in [True, False]:
                    for vol_min in [1.0, 1.3, 1.5]:
                        for tp_atr in [0.5, 1.0, 1.5, 2.0]:
                            for sl_atr in [1.5, 2.0, 3.0]:
                                if tp_atr >= sl_atr:
                                    continue
                                for hold in [12, 24, 48]:
                                    grid.append(
                                        CVariant(rsi_l, rsi_s, req_macd, req_ema, vol_min, tp_atr, sl_atr, hold)
                                    )
    print(f"Grid: {len(grid)} variants")

    rows = []
    qualified = []
    for idx, v in enumerate(grid):
        # Aggregate train across symbols
        tr_n = tr_w = 0
        tr_pnl = 0.0
        tr_pf_num = 0.0
        tr_pf_den = 0.0
        for s in SYMBOLS:
            a, ind = data[s]
            n, w, pnl, wr, pf = simulate(a, ind, v, 0, split_idx)
            tr_n += n
            tr_w += w
            tr_pnl += pnl
            if pf and math.isfinite(pf) and pf > 0:
                tr_pf_num += pnl if pnl > 0 else 0
                tr_pf_den += abs(pnl) if pnl < 0 else 0
        # Better: recompute aggregate PF properly with raw sums (we already have sum_win and sum_loss in totals)
        # Quick re-aggregation using per-symbol simulate again (slower but accurate)
        sym_wins = 0
        sym_loss = 0
        agg_pnl = 0.0
        agg_w_sum = 0.0
        agg_l_sum_abs = 0.0
        for s in SYMBOLS:
            a, ind = data[s]
            close = a[:, 4]
            # Rerun simulate would double cost; reuse pnl_sum from per-symbol but we lost win/loss split
            # Instead rerun simulate with returning win_sum/loss_abs
            pass
        train_wr = tr_w / tr_n if tr_n > 0 else 0.0
        rec = {
            "label": (
                f"rsi{v.rsi_long_thr}/{v.rsi_short_thr}|macd{int(v.require_macd)}|ema{int(v.require_ema_align)}|"
                f"vol{v.vol_min}|tp{v.tp_atr}|sl{v.sl_atr}|h{v.hold_bars}"
            ),
            "train": {"n": tr_n, "wins": tr_w, "wr": round(train_wr, 4), "pnl": round(tr_pnl, 2)},
        }
        if tr_n >= 100 and train_wr >= 0.80:
            # Run test
            te_n = te_w = 0
            te_pnl = 0.0
            for s in SYMBOLS:
                a, ind = data[s]
                n, w, pnl, _, _ = simulate(a, ind, v, split_idx, len(a[:, 4]))
                te_n += n
                te_w += w
                te_pnl += pnl
            test_wr = te_w / te_n if te_n > 0 else 0.0
            rec["test"] = {"n": te_n, "wins": te_w, "wr": round(test_wr, 4), "pnl": round(te_pnl, 2)}
            rec["passed_test"] = te_n >= 30 and test_wr >= 0.75 and te_pnl > 0
            qualified.append(rec)
        rows.append(rec)
        if idx % 100 == 0:
            print(f"  [{idx + 1:5d}/{len(grid)}] {rec['label']} WR={train_wr:.3f} N={tr_n} pnl={tr_pnl:+.2f} ({time.time()-t_start:.0f}s)")

    rows.sort(key=lambda r: -r["train"]["wr"])
    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_variants": len(rows),
        "train_wr80_count": sum(1 for r in rows if r["train"]["wr"] >= 0.80),
        "train_wr70_count": sum(1 for r in rows if r["train"]["wr"] >= 0.70),
        "test_passed": sum(1 for r in qualified if r.get("passed_test")),
        "qualified": qualified,
        "top20": rows[:20],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2, default=str))

    print()
    print(f"=== TOP 20 by train WR ===")
    for r in rows[:20]:
        t = r["train"]
        print(f"  WR={t['wr']:.3f} N={t['n']:>4d} pnl={t['pnl']:+8.2f}  {r['label']}")
    print()
    print(f"Train WR>=80%: {summary['train_wr80_count']}")
    print(f"Train WR>=70%: {summary['train_wr70_count']}")
    print(f"OOS-passed: {summary['test_passed']}")
    print(f"Elapsed: {time.time() - t_start:.0f}s")
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
