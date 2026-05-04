#!/usr/bin/env python3
"""Monte Carlo ruin simulation for X3 / X4 winner candidates.

Per CLAUDE.md mandatory checklist: MC ruin >= 1000 runs, ruin <= 5% (safe).

Method:
1. Run X3 / X4 strategy on full data, collect per-trade PnL series.
2. Bootstrap 5000 random orderings.
3. For each, simulate $50 equity with $100 fixed notional × leverage.
4. Ruin = equity drops to <= 25 (50% drawdown) OR <= 0 (wipeout).
5. Report ruin rate at multiple leverages.

Output: quant_runtime/x3_x4_mc_ruin.json
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
OUT = ROOT / "quant_runtime" / "x3_x4_mc_ruin.json"

NOTIONAL = 100.0
COST_RT = 0.0012
EQUITY = 50.0

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
class P:
    rsi_long: float
    rsi_short: float
    vol_min: float
    tp_atr: float
    sl_atr: float
    hold: int


def collect_pnls(arr, ind, p: P) -> list[float]:
    rsi, macd, macd_sig, atr, vol_r = ind
    close = arr[:, 4]
    high = arr[:, 2]
    low = arr[:, 3]
    fee = NOTIONAL * COST_RT
    pnls: list[float] = []
    cooldown = 0
    end = len(close) - p.hold - 2
    i = 60
    while i < end:
        if i < cooldown:
            i += 1
            continue
        long_sig = rsi[i] <= p.rsi_long and macd[i] > macd_sig[i] and vol_r[i] >= p.vol_min
        short_sig = rsi[i] >= p.rsi_short and macd[i] < macd_sig[i] and vol_r[i] >= p.vol_min
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
        tp_px = entry_px + side * p.tp_atr * atr[i]
        sl_px = entry_px - side * p.sl_atr * atr[i]
        exit_px = None
        for k in range(e, min(e + p.hold, len(close))):
            hi, lo = high[k], low[k]
            hit_sl = (lo <= sl_px) if side == 1 else (hi >= sl_px)
            hit_tp = (hi >= tp_px) if side == 1 else (lo <= tp_px)
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
            exit_px = close[min(e + p.hold - 1, len(close) - 1)]
        roe = side * (exit_px - entry_px) / entry_px
        pnls.append(NOTIONAL * roe - fee)
        i = e + 1
        cooldown = i + 2
    return pnls


def mc_ruin(pnls: list[float], leverage: float, n_runs: int = 5000, equity_start: float = EQUITY,
            ruin_threshold: float = 0.5) -> dict:
    """Bootstrap shuffle PnLs, compute ruin probability."""
    arr = np.array(pnls, dtype=np.float64) * leverage  # leverage scales each trade PnL
    n_trades = len(arr)
    if n_trades == 0:
        return {"ruin_rate": 0, "median_final": equity_start, "n_runs": 0}
    rng = np.random.default_rng(42)
    final_eqs: list[float] = []
    ruin_count = 0
    min_eq_each_run: list[float] = []
    for _ in range(n_runs):
        order = rng.permutation(n_trades)
        eq = equity_start
        min_eq = eq
        for j in order:
            eq += arr[j]
            if eq < min_eq:
                min_eq = eq
        final_eqs.append(eq)
        min_eq_each_run.append(min_eq)
        if min_eq <= equity_start * (1 - ruin_threshold):
            ruin_count += 1
    return {
        "leverage": leverage,
        "n_runs": n_runs,
        "n_trades": n_trades,
        "ruin_rate": ruin_count / n_runs,
        "median_final_eq": float(np.median(final_eqs)),
        "p5_final_eq": float(np.percentile(final_eqs, 5)),
        "p95_final_eq": float(np.percentile(final_eqs, 95)),
        "median_min_eq": float(np.median(min_eq_each_run)),
        "p5_min_eq": float(np.percentile(min_eq_each_run, 5)),
        "mean_total_pnl": float(np.mean(arr) * n_trades),
    }


def main():
    t0 = time.time()
    data = {}
    for s in UNIVERSE_20:
        a = load_1h(s)
        ind = compute_indicators(a)
        data[s] = (a, ind)
    print(f"Loaded 20 symbols × 1h × {len(data[UNIVERSE_20[0]][0])} bars in {time.time()-t0:.1f}s")

    candidates = [
        ("X3", P(25, 70, 1.0, 0.5, 3.0, 24)),
        ("X4", P(25, 70, 1.3, 0.5, 3.0, 24)),
        ("X1", P(30, 70, 1.0, 0.5, 3.0, 24)),
    ]

    out = {}
    for name, p in candidates:
        t1 = time.time()
        all_pnls: list[float] = []
        for s in UNIVERSE_20:
            arr, ind = data[s]
            all_pnls.extend(collect_pnls(arr, ind, p))
        n = len(all_pnls)
        wins = sum(1 for x in all_pnls if x > 0)
        wr = wins / n if n else 0
        total = sum(all_pnls)
        win_sum = sum(x for x in all_pnls if x > 0)
        loss_abs = sum(abs(x) for x in all_pnls if x <= 0)
        pf = win_sum / loss_abs if loss_abs > 0 else float("inf")
        avg_win = win_sum / wins if wins else 0
        avg_loss = -loss_abs / (n - wins) if (n - wins) else 0

        # MC ruin at multiple leverages
        ruin_results = []
        for lev in [1.0, 2.0, 3.0, 5.0, 10.0]:
            r = mc_ruin(all_pnls, lev, n_runs=5000)
            ruin_results.append(r)

        out[name] = {
            "params": p.__dict__,
            "n_trades": n,
            "wr": round(wr, 4),
            "pf": round(pf, 3) if math.isfinite(pf) else None,
            "total_pnl_usd": round(total, 2),
            "avg_win_usd": round(avg_win, 3),
            "avg_loss_usd": round(avg_loss, 3),
            "ev_per_trade_usd": round(total / n, 4) if n else 0,
            "fee_per_trade_usd": round(NOTIONAL * COST_RT, 4),
            "fee_to_avg_loss": round((NOTIONAL * COST_RT) / abs(avg_loss), 3) if avg_loss else None,
            "mc_ruin_at_leverages": ruin_results,
        }

        print(f"\n=== {name} ===")
        print(f"  N={n}  WR={wr:.3f}  PF={pf:.3f}  total=${total:+.2f}")
        print(f"  avg_win=${avg_win:.3f}  avg_loss=${avg_loss:.3f}  EV=${total/n:+.4f}/trade")
        print(f"  fee=${NOTIONAL * COST_RT:.4f}  fee/avg_loss={(NOTIONAL * COST_RT) / abs(avg_loss):.3f}")
        print(f"  MC ruin (50% DD threshold, $50 start, 5000 runs):")
        for r in ruin_results:
            print(f"    lev {r['leverage']:>4.1f}x: ruin={r['ruin_rate']*100:>5.1f}%  median_final=${r['median_final_eq']:>6.2f}  p5_min=${r['p5_min_eq']:>6.2f}")

    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nElapsed: {time.time() - t0:.1f}s, saved: {OUT}")


if __name__ == "__main__":
    main()
