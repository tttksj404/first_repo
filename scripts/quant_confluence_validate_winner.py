#!/usr/bin/env python3
"""Stress-test the OOS-passed variants from confluence_oos.

For each strict OOS-passed candidate:
1. Per-symbol breakdown (avoid concentration in 1-2 symbols)
2. Walk-forward 4-fold (each fold WR check)
3. Drawdown / max consecutive loss
4. Slippage stress (extra 5/10/20 bps cost)
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "quant_runtime" / "historical"
OUT = ROOT / "quant_runtime" / "confluence_winner_validate.json"
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "APTUSDT", "ARBUSDT", "AVAXUSDT", "BNBUSDT",
    "DOTUSDT", "LINKUSDT", "LTCUSDT", "NEARUSDT", "OPUSDT",
    "PEPEUSDT", "SUIUSDT", "UNIUSDT", "WIFUSDT", "MATICUSDT",
]
NOTIONAL = 100.0
COST_RT = 0.0012


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
    avg_up = 0.0
    avg_dn = 0.0
    for i in range(1, len(close)):
        if i <= 14:
            avg_up = np.mean(up[1 : i + 1])
            avg_dn = np.mean(dn[1 : i + 1])
        else:
            avg_up = (avg_up * 13 + up[i]) / 14
            avg_dn = (avg_dn * 13 + dn[i]) / 14
        if avg_dn == 0:
            rsi[i] = 100
        else:
            rs = avg_up / avg_dn
            rsi[i] = 100 - 100 / (1 + rs)

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
    ema20 = ema(close, 20)
    ema50 = ema(close, 50)

    prev_close = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    atr = ema(tr, 14)

    vol_ma = np.zeros_like(vol)
    for i in range(len(vol)):
        s = max(0, i - 20)
        vol_ma[i] = np.mean(vol[s : i + 1]) if i > 0 else vol[i]
    vol_r = np.where(vol_ma > 0, vol / vol_ma, 1.0)
    return rsi, macd, macd_sig, ema20, ema50, atr, vol_r


def simulate(arr, ind, params, idx_start, idx_end, extra_bps=0.0):
    rsi, macd, macd_sig, ema20, ema50, atr, vol_r = ind
    close = arr[:, 4]
    high = arr[:, 2]
    low = arr[:, 3]
    fee = NOTIONAL * (COST_RT + 2 * extra_bps / 10000.0)
    rsi_l = params["rsi_long"]
    rsi_s = params["rsi_short"]
    req_macd = params["req_macd"]
    req_ema = params["req_ema"]
    vol_min = params["vol_min"]
    tp_atr = params["tp_atr"]
    sl_atr = params["sl_atr"]
    hold = params["hold"]

    wins = 0
    losses = 0
    pnl_sum = 0.0
    pnls: list[float] = []
    cooldown = 0
    end = min(idx_end, len(close) - hold - 2)
    i = max(idx_start, 60)
    while i < end:
        if i < cooldown:
            i += 1
            continue
        long_sig = (
            rsi[i] <= rsi_l
            and (not req_macd or macd[i] > macd_sig[i])
            and (not req_ema or ema20[i] > ema50[i])
            and vol_r[i] >= vol_min
        )
        short_sig = (
            rsi[i] >= rsi_s
            and (not req_macd or macd[i] < macd_sig[i])
            and (not req_ema or ema20[i] < ema50[i])
            and vol_r[i] >= vol_min
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
        tp_px = entry_px + side * tp_atr * atr[i]
        sl_px = entry_px - side * sl_atr * atr[i]
        exit_px = None
        for k in range(e, min(e + hold, len(close))):
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
            exit_idx = min(e + hold - 1, len(close) - 1)
            exit_px = close[exit_idx]
        roe = side * (exit_px - entry_px) / entry_px
        pnl = NOTIONAL * roe - fee
        pnl_sum += pnl
        pnls.append(pnl)
        if pnl > 0:
            wins += 1
        else:
            losses += 1
        i = e + 1
        cooldown = i + 2
    n = wins + losses
    wr = wins / n if n > 0 else 0.0
    win_pnl = sum(p for p in pnls if p > 0)
    loss_pnl_abs = sum(abs(p) for p in pnls if p <= 0)
    pf = win_pnl / loss_pnl_abs if loss_pnl_abs > 0 else (float("inf") if win_pnl > 0 else 0.0)
    return n, wins, pnl_sum, wr, pf, pnls


CANDIDATES = [
    # NEW: 20-symbol expanded OOS winners (rsi30/70 + MACD)
    {"name": "X1_rsi30_70_macd_h24", "rsi_long": 30, "rsi_short": 70, "req_macd": True, "req_ema": False, "vol_min": 1.0, "tp_atr": 0.5, "sl_atr": 3.0, "hold": 24},
    {"name": "X2_rsi30_70_macd_h48", "rsi_long": 30, "rsi_short": 70, "req_macd": True, "req_ema": False, "vol_min": 1.0, "tp_atr": 0.5, "sl_atr": 3.0, "hold": 48},
    {"name": "X3_rsi25_70_macd_h24", "rsi_long": 25, "rsi_short": 70, "req_macd": True, "req_ema": False, "vol_min": 1.0, "tp_atr": 0.5, "sl_atr": 3.0, "hold": 24},
    {"name": "X4_rsi25_70_macd_vol1.3_h24", "rsi_long": 25, "rsi_short": 70, "req_macd": True, "req_ema": False, "vol_min": 1.3, "tp_atr": 0.5, "sl_atr": 3.0, "hold": 24},
    # Earlier WR-max candidate kept for comparison
    {"name": "WR_C3_rsi30_macd_h24", "rsi_long": 30, "rsi_short": 65, "req_macd": True, "req_ema": False, "vol_min": 1.0, "tp_atr": 0.5, "sl_atr": 3.0, "hold": 24},
]


def main() -> None:
    t0 = time.time()
    data = {s: (load_1h(s), None) for s in SYMBOLS}
    for s in SYMBOLS:
        a, _ = data[s]
        data[s] = (a, compute_indicators(a))
    n_bars = len(data[SYMBOLS[0]][0])
    print(f"Bars per symbol: {n_bars}, total per-symbol days: {n_bars / 24:.0f}")

    out = {"candidates": []}
    for c in CANDIDATES:
        print(f"\n=== {c['name']} | {c} ===")
        # 1. Per-symbol breakdown
        per_sym = {}
        agg_n = 0
        agg_w = 0
        agg_pnl = 0.0
        agg_pnls: list[float] = []
        for s in SYMBOLS:
            a, ind = data[s]
            n, w, pnl, wr, pf, pnls = simulate(a, ind, c, 0, n_bars)
            per_sym[s] = {"n": n, "wins": w, "wr": round(wr, 3), "pnl": round(pnl, 2), "pf": round(pf, 3) if math.isfinite(pf) else None}
            agg_n += n
            agg_w += w
            agg_pnl += pnl
            agg_pnls.extend(pnls)
        agg_wr = agg_w / agg_n if agg_n > 0 else 0
        win_pnl = sum(p for p in agg_pnls if p > 0)
        loss_abs = sum(abs(p) for p in agg_pnls if p <= 0)
        agg_pf = win_pnl / loss_abs if loss_abs > 0 else float("inf")
        # Max drawdown over equity curve
        equity = np.cumsum(agg_pnls)
        peak = np.maximum.accumulate(equity) if len(equity) else np.array([0])
        dd = (peak - equity)
        max_dd = float(dd.max()) if len(dd) else 0.0
        # Max consecutive losses
        max_streak = 0
        cur = 0
        for p in agg_pnls:
            if p <= 0:
                cur += 1
                max_streak = max(max_streak, cur)
            else:
                cur = 0

        # 2. Walk-forward 4-fold
        wf_results = []
        fold_size = n_bars // 4
        for f in range(4):
            f_start = f * fold_size
            f_end = (f + 1) * fold_size if f < 3 else n_bars
            n_f = w_f = 0
            pnl_f = 0.0
            for s in SYMBOLS:
                a, ind = data[s]
                n, w, pnl, _, _, _ = simulate(a, ind, c, f_start, f_end)
                n_f += n
                w_f += w
                pnl_f += pnl
            wr_f = w_f / n_f if n_f > 0 else 0
            wf_results.append({"fold": f + 1, "n": n_f, "wr": round(wr_f, 3), "pnl": round(pnl_f, 2)})

        wf_pass = sum(1 for r in wf_results if r["wr"] >= 0.70 and r["n"] >= 5)

        # 3. Slippage stress (test set only: idx 6300+)
        slip_results = []
        for extra in [0.0, 5.0, 10.0, 20.0]:
            n_s = w_s = 0
            pnl_s = 0.0
            for s in SYMBOLS:
                a, ind = data[s]
                n, w, pnl, _, _, _ = simulate(a, ind, c, 6300, n_bars, extra_bps=extra)
                n_s += n
                w_s += w
                pnl_s += pnl
            wr_s = w_s / n_s if n_s > 0 else 0
            slip_results.append({"extra_bps": extra, "n": n_s, "wr": round(wr_s, 3), "pnl": round(pnl_s, 2)})

        candidate_out = {
            "name": c["name"],
            "params": c,
            "aggregate": {
                "n": agg_n,
                "wins": agg_w,
                "wr": round(agg_wr, 4),
                "pnl_total_usd": round(agg_pnl, 2),
                "pnl_per_trade_usd": round(agg_pnl / agg_n, 4) if agg_n else 0,
                "pf": round(agg_pf, 3) if math.isfinite(agg_pf) else None,
                "max_dd_usd": round(max_dd, 2),
                "max_consecutive_losses": max_streak,
            },
            "per_symbol": per_sym,
            "walk_forward_4fold": wf_results,
            "wf_pass_count": wf_pass,
            "slippage_stress": slip_results,
        }
        out["candidates"].append(candidate_out)
        print(f"  Aggregate: N={agg_n} WR={agg_wr:.3f} PnL={agg_pnl:+.2f} PF={agg_pf:.2f} maxDD={max_dd:.2f} maxLossStreak={max_streak}")
        print(f"  Per-symbol:")
        for s, ps in per_sym.items():
            print(f"    {s}: N={ps['n']:>3d} WR={ps['wr']:.3f} pnl={ps['pnl']:+.2f}")
        print(f"  Walk-forward 4-fold (target WR>=0.70 in >=3/4):")
        for r in wf_results:
            mk = "✓" if r["wr"] >= 0.70 and r["n"] >= 5 else "✗"
            print(f"    fold {r['fold']}: N={r['n']:>3d} WR={r['wr']:.3f} pnl={r['pnl']:+.2f} {mk}")
        print(f"    WF passed: {wf_pass}/4")
        print(f"  Slippage stress (test set):")
        for r in slip_results:
            print(f"    +{r['extra_bps']:.0f}bps: N={r['n']} WR={r['wr']:.3f} pnl={r['pnl']:+.2f}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2))
    print(f"\nElapsed: {time.time() - t0:.1f}s")
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
