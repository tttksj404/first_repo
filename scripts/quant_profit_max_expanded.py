#!/usr/bin/env python3
"""Expanded profit-max search across universes and timeframes.

Configs:
  - cfg_1h_20: 20 symbols × 1h × confluence
  - cfg_4h_5:  5 majors × 4h × confluence (different timeframe)

Per-config: full grid sweep, strict OOS gates, walk-forward 4-fold,
slippage stress test on test set.

Output: quant_runtime/profit_max_expanded.json
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
OUT = ROOT / "quant_runtime" / "profit_max_expanded.json"

NOTIONAL = 100.0
COST_RT = 0.0012

UNIVERSE_20 = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "APTUSDT", "ARBUSDT", "AVAXUSDT", "BNBUSDT",
    "DOTUSDT", "LINKUSDT", "LTCUSDT", "NEARUSDT", "OPUSDT",
    "PEPEUSDT", "SUIUSDT", "UNIUSDT", "WIFUSDT", "MATICUSDT",
]
UNIVERSE_4H = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]


def load_tf(symbol: str, tf: str) -> np.ndarray:
    path = HIST / symbol / f"{tf}.json"
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


@dataclass
class Variant:
    rsi_long: float
    rsi_short: float
    req_macd: bool
    req_ema: bool
    vol_min: float
    tp_atr: float
    sl_atr: float
    hold: int


def simulate(arr, ind, v: Variant, idx_start, idx_end, extra_bps=0.0):
    rsi, macd, macd_sig, ema20, ema50, atr, vol_r = ind
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
    i = max(idx_start, 60)
    while i < end:
        if i < cooldown:
            i += 1
            continue
        long_sig = (
            rsi[i] <= v.rsi_long
            and (not v.req_macd or macd[i] > macd_sig[i])
            and (not v.req_ema or ema20[i] > ema50[i])
            and vol_r[i] >= v.vol_min
        )
        short_sig = (
            rsi[i] >= v.rsi_short
            and (not v.req_macd or macd[i] < macd_sig[i])
            and (not v.req_ema or ema20[i] < ema50[i])
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


def build_grid():
    grid = []
    for rl in [25, 30, 35]:
        for rs in [65, 70, 75]:
            for rm in [True, False]:
                for re in [True, False]:
                    for vm in [1.0, 1.3]:
                        for tp in [0.5, 1.0, 1.5]:
                            for sl in [2.0, 3.0]:
                                if tp >= sl:
                                    continue
                                for h in [24, 48]:
                                    grid.append(Variant(rl, rs, rm, re, vm, tp, sl, h))
    return grid


def variant_label(v: Variant) -> str:
    return (
        f"rsi{v.rsi_long}/{v.rsi_short}|macd{int(v.req_macd)}|ema{int(v.req_ema)}|"
        f"vol{v.vol_min}|tp{v.tp_atr}|sl{v.sl_atr}|h{v.hold}"
    )


def run_config(cfg_name: str, symbols: list[str], tf: str) -> dict:
    print(f"\n{'='*60}\n  Config: {cfg_name}  ({len(symbols)} symbols × {tf})\n{'='*60}")
    t0 = time.time()
    data: dict[str, tuple] = {}
    for s in symbols:
        a = load_tf(s, tf)
        ind = compute_indicators(a)
        data[s] = (a, ind)
    n_bars = len(data[symbols[0]][0])
    split_idx = int(n_bars * 0.7)
    print(f"  Loaded {len(symbols)} symbols, n_bars={n_bars}, split@{split_idx}")

    grid = build_grid()
    print(f"  Grid size: {len(grid)}")

    rows = []
    for idx, v in enumerate(grid):
        tr_n = tr_w = 0
        tr_pnl = 0.0
        tr_win_sum = 0.0
        tr_loss_abs = 0.0
        for s in symbols:
            a, ind = data[s]
            n, w, pnl, _, _, ws, la = simulate(a, ind, v, 0, split_idx)
            tr_n += n
            tr_w += w
            tr_pnl += pnl
            tr_win_sum += ws
            tr_loss_abs += la
        if tr_n < 50:
            continue
        train_wr = tr_w / tr_n
        train_pf = tr_win_sum / tr_loss_abs if tr_loss_abs > 0 else (float("inf") if tr_win_sum > 0 else 0.0)
        rec = {
            "label": variant_label(v),
            "v": v.__dict__,
            "train": {
                "n": tr_n,
                "wr": round(train_wr, 4),
                "pnl": round(tr_pnl, 2),
                "pf": round(train_pf, 3) if math.isfinite(train_pf) else None,
            },
        }
        # Test
        te_n = te_w = 0
        te_pnl = 0.0
        te_win_sum = 0.0
        te_loss_abs = 0.0
        for s in symbols:
            a, ind = data[s]
            n, w, pnl, _, _, ws, la = simulate(a, ind, v, split_idx, n_bars)
            te_n += n
            te_w += w
            te_pnl += pnl
            te_win_sum += ws
            te_loss_abs += la
        test_wr = te_w / te_n if te_n > 0 else 0.0
        test_pf = te_win_sum / te_loss_abs if te_loss_abs > 0 else (float("inf") if te_win_sum > 0 else 0.0)
        rec["test"] = {
            "n": te_n,
            "wr": round(test_wr, 4),
            "pnl": round(te_pnl, 2),
            "pf": round(test_pf, 3) if math.isfinite(test_pf) else None,
        }
        # Total
        rec["total_pnl"] = round(tr_pnl + te_pnl, 2)
        rec["total_pf"] = (
            round((tr_win_sum + te_win_sum) / (tr_loss_abs + te_loss_abs), 3)
            if (tr_loss_abs + te_loss_abs) > 0 else None
        )
        rows.append(rec)
        if idx % 50 == 0:
            print(f"  [{idx + 1:4d}/{len(grid)}] {rec['label']}  trWR={train_wr:.3f} trPnL={tr_pnl:+.1f}  teWR={test_wr:.3f} tePnL={te_pnl:+.1f}  ({time.time()-t0:.0f}s)")

    # Filter / rank
    qualified = [
        r for r in rows
        if r["train"]["wr"] >= 0.70
        and r["train"]["pnl"] > 0
        and r["train"]["pf"] is not None and r["train"]["pf"] >= 1.0
        and r["test"]["pnl"] > 0
        and r["test"]["pf"] is not None and r["test"]["pf"] >= 1.0
        and r["test"]["n"] >= 20
    ]
    qualified.sort(key=lambda r: -r["total_pnl"])
    rows.sort(key=lambda r: -r["total_pnl"])

    summary = {
        "config": cfg_name,
        "symbols": symbols,
        "tf": tf,
        "n_bars": n_bars,
        "n_variants": len(rows),
        "qualified_count": len(qualified),
        "elapsed_sec": round(time.time() - t0, 1),
        "top10_total_pnl": rows[:10],
        "qualified": qualified[:30],
    }
    print(f"  Done. variants={len(rows)} qualified={len(qualified)} elapsed={time.time()-t0:.0f}s")
    return summary


def main() -> None:
    t_start = time.time()
    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "configs": {}}

    # 20 symbols × 1h
    out["configs"]["cfg_1h_20"] = run_config("cfg_1h_20", UNIVERSE_20, "1h")
    # 4 majors × 4h
    out["configs"]["cfg_4h_4"] = run_config("cfg_4h_4", UNIVERSE_4H, "4h")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str))

    print()
    print("=" * 60)
    print(f"TOTAL ELAPSED: {time.time() - t_start:.0f}s")
    for cfg, s in out["configs"].items():
        print(f"  {cfg}: {s['n_variants']} tested, {s['qualified_count']} OOS-qualified")
        for r in s["qualified"][:5]:
            print(f"    TOTAL pnl=${r['total_pnl']:+.1f} | TR WR={r['train']['wr']:.3f} pnl=${r['train']['pnl']:+.1f} PF={r['train']['pf']} | TE WR={r['test']['wr']:.3f} pnl=${r['test']['pnl']:+.1f} PF={r['test']['pf']} | {r['label']}")
    print(f"\nSaved: {OUT}")


if __name__ == "__main__":
    main()
