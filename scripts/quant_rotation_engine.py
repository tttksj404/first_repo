#!/usr/bin/env python3
"""Rotation engine: priority-ordered universe, single position at a time.

Replicates the production "rotation 30x basket" mechanic:
  - At each bar, scan symbols in priority order
  - First symbol with valid signal → enter
  - Hold until TP/SL/hold-cap → exit
  - Then resume scanning

Cost model: COST_RT 0.0012, FUNDING 0.0001/8h
Equity: $50, fixed margin (no compounding).

Expose:
  - rotation_backtest(symbols, data_cache, signal_fn, params) -> trades
  - signal library: x1, x4, momentum, atr_breakout, turnaround
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "quant_runtime" / "historical"
COST_RT = 0.0012
FUNDING_8H = 0.0001
EQUITY = 50.0


def load_1h(symbol: str) -> Optional[np.ndarray]:
    path = HIST / symbol / "1h.json"
    if not path.exists():
        return None
    raw = json.loads(path.read_text())
    if len(raw) < 2000:
        return None
    return np.array(
        [[r["open_time"], r["open_price"], r["high_price"], r["low_price"], r["close_price"], r.get("base_volume", 0.0)]
         for r in raw],
        dtype=np.float64,
    )


def compute_indicators(arr: np.ndarray) -> dict:
    close = arr[:, 4]; high = arr[:, 2]; low = arr[:, 3]; vol = arr[:, 5]
    n = len(close)
    delta = np.diff(close, prepend=close[0])
    up = np.maximum(delta, 0); dn = np.maximum(-delta, 0)
    rsi = np.zeros(n)
    avg_up = avg_dn = 0.0
    for i in range(1, n):
        if i <= 14:
            avg_up = np.mean(up[1:i+1]); avg_dn = np.mean(dn[1:i+1])
        else:
            avg_up = (avg_up * 13 + up[i]) / 14
            avg_dn = (avg_dn * 13 + dn[i]) / 14
        rsi[i] = 100 if avg_dn == 0 else 100 - 100 / (1 + avg_up/avg_dn)
    def ema(x, p):
        a = 2.0 / (p+1); out = np.empty(n); out[0] = x[0]
        for i in range(1, n):
            out[i] = a*x[i] + (1-a)*out[i-1]
        return out
    ema12 = ema(close, 12); ema26 = ema(close, 26)
    macd = ema12 - ema26; macd_sig = ema(macd, 9)
    ema20 = ema(close, 20); ema50 = ema(close, 50)
    prev = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high-low, np.maximum(np.abs(high-prev), np.abs(low-prev)))
    atr = ema(tr, 14)
    vol_ma = np.zeros(n)
    for i in range(n):
        s = max(0, i-20)
        vol_ma[i] = np.mean(vol[s:i+1]) if i > 0 else vol[i]
    vol_r = np.where(vol_ma > 0, vol/vol_ma, 1.0)
    # ADX(14)
    pdm = np.zeros(n); mdm = np.zeros(n)
    for i in range(1, n):
        hd = high[i]-high[i-1]; ld = low[i-1]-low[i]
        pdm[i] = max(hd, 0) if hd > ld else 0
        mdm[i] = max(ld, 0) if ld > hd else 0
    adx = np.zeros(n)
    for i in range(15, n):
        a = np.mean(tr[i-13:i+1])
        if a > 0:
            pdi = np.mean(pdm[i-13:i+1])/a*100
            mdi = np.mean(mdm[i-13:i+1])/a*100
            denom = max(pdi+mdi, 0.01)
            adx[i] = abs(pdi-mdi)/denom*100
    # Momentum 168h
    mom168 = np.zeros(n)
    for i in range(168, n):
        mom168[i] = (close[i]-close[i-168])/close[i-168]
    # 20-bar high/low
    high20 = np.zeros(n); low20 = np.zeros(n)
    for i in range(n):
        s = max(0, i-20)
        high20[i] = np.max(high[s:i+1]) if i > 0 else high[i]
        low20[i] = np.min(low[s:i+1]) if i > 0 else low[i]
    return {
        "close": close, "high": high, "low": low,
        "rsi": rsi, "macd": macd, "macd_sig": macd_sig,
        "ema20": ema20, "ema50": ema50, "atr": atr, "vol_r": vol_r,
        "adx": adx, "mom168": mom168, "high20": high20, "low20": low20,
    }


# ===== Signal library =====
# Each signal function: (ind, i, long_only) -> int (1=long, -1=short, 0=none)

def sig_x1(ind, i, long_only=False):
    if ind["rsi"][i] <= 30 and ind["macd"][i] > ind["macd_sig"][i]:
        return 1
    if (not long_only) and ind["rsi"][i] >= 70 and ind["macd"][i] < ind["macd_sig"][i]:
        return -1
    return 0


def sig_x4(ind, i, long_only=False):
    if ind["rsi"][i] <= 25 and ind["macd"][i] > ind["macd_sig"][i] and ind["vol_r"][i] >= 1.3:
        return 1
    if (not long_only) and ind["rsi"][i] >= 70 and ind["macd"][i] < ind["macd_sig"][i] and ind["vol_r"][i] >= 1.3:
        return -1
    return 0


def sig_momentum(ind, i, long_only=False, mom_min=0.03, adx_min=0.0):
    if i < 168:
        return 0
    if ind["mom168"][i] >= mom_min and ind["ema20"][i] > ind["ema50"][i] and ind["adx"][i] >= adx_min:
        return 1
    if (not long_only) and ind["mom168"][i] <= -mom_min and ind["ema20"][i] < ind["ema50"][i] and ind["adx"][i] >= adx_min:
        return -1
    return 0


def sig_atr_breakout(ind, i, long_only=False, buf=0.25, adx_min=0.0):
    close = ind["close"][i]; atr = ind["atr"][i]; adx = ind["adx"][i]
    if adx < adx_min or atr <= 0:
        return 0
    if close > ind["high20"][i-1] + buf * atr:
        return 1
    if (not long_only) and close < ind["low20"][i-1] - buf * atr:
        return -1
    return 0


def sig_turnaround(ind, i, long_only=True):
    # Long-only oversold bounce: rsi<25 + price up vs prev close + macd cross
    if ind["rsi"][i] <= 25 and ind["close"][i] > ind["close"][i-1] and ind["macd"][i] > ind["macd_sig"][i]:
        return 1
    return 0


def sig_combined(ind, i, long_only=False):
    """OR-combination: any of x1/momentum/atr_breakout fires."""
    s = sig_x1(ind, i, long_only)
    if s != 0:
        return s
    s = sig_momentum(ind, i, long_only, mom_min=0.03, adx_min=15)
    if s != 0:
        return s
    s = sig_atr_breakout(ind, i, long_only, buf=0.25, adx_min=15)
    if s != 0:
        return s
    return 0


SIGNALS = {
    "x1": sig_x1,
    "x4": sig_x4,
    "momentum": sig_momentum,
    "atr_breakout": sig_atr_breakout,
    "turnaround": sig_turnaround,
    "combined": sig_combined,
}


# ===== Rotation Engine =====
@dataclass
class RotationParams:
    signal: str = "combined"
    long_only: bool = False
    lev: float = 30.0
    margin_pct: float = 0.35
    # Exit: ROE-based (matching production rotation_30x)
    tp_roe: float = 30.0
    sl_roe: float = -10.0
    abort_roe: float = -18.0    # turnaround abort
    use_atr_exit: bool = False  # if true, use TP/SL ATR multiples instead
    tp_atr: float = 2.0
    sl_atr: float = 3.0
    hold_h: int = 48
    extra_bps: float = 0.0
    cooldown_bars: int = 2


@dataclass
class Trade:
    symbol: str
    side: int
    entry_idx: int
    exit_idx: int
    hold_h: int
    pnl_usd: float
    roe_pct: float


def rotation_backtest(priority: list[str], data_cache: dict, p: RotationParams,
                       idx_start: int = 200, idx_end: Optional[int] = None) -> list[Trade]:
    """Single-position rotation: at each free bar, scan priority list, take 1st signal."""
    sig_fn = SIGNALS[p.signal]
    margin = EQUITY * p.margin_pct
    notional = margin * p.lev
    fee = notional * (COST_RT + 2 * p.extra_bps / 10000.0)

    valid_syms = [s for s in priority if s in data_cache]
    if not valid_syms:
        return []
    # Determine common length
    n = min(len(data_cache[s]["close"]) for s in valid_syms)
    if idx_end is None:
        idx_end = n
    idx_end = min(idx_end, n - p.hold_h - 2)

    trades: list[Trade] = []
    i = max(idx_start, 200)
    cooldown = 0
    while i < idx_end:
        if i < cooldown:
            i += 1
            continue
        # Scan priority order
        chosen_sym = None
        chosen_side = 0
        for s in valid_syms:
            ind = data_cache[s]
            side = sig_fn(ind, i, p.long_only)
            if side != 0:
                chosen_sym = s
                chosen_side = side
                break
        if chosen_sym is None:
            i += 1
            continue

        ind = data_cache[chosen_sym]
        e = i + 1
        if e >= n:
            break
        entry_px = ind["close"][i]  # close of signal bar
        if entry_px <= 0:
            i += 1
            continue

        # Compute exit prices
        if p.use_atr_exit:
            atr_e = ind["atr"][i]
            if atr_e <= 0:
                i += 1
                continue
            tp_px = entry_px + chosen_side * p.tp_atr * atr_e
            sl_px = entry_px - chosen_side * p.sl_atr * atr_e
            abort_px = sl_px  # same
        else:
            # ROE-based: roe% / lev = price_pct
            tp_pct = p.tp_roe / 100.0 / p.lev
            sl_pct = p.sl_roe / 100.0 / p.lev   # negative
            abort_pct = p.abort_roe / 100.0 / p.lev
            tp_px = entry_px * (1 + chosen_side * tp_pct)
            sl_px = entry_px * (1 + chosen_side * sl_pct)
            abort_px = entry_px * (1 + chosen_side * abort_pct)

        exit_px = None
        exit_k = None
        # Walk forward
        for k in range(e, min(e + p.hold_h, n)):
            hi = ind["high"][k]; lo = ind["low"][k]
            if chosen_side == 1:
                hit_abort = lo <= abort_px
                hit_sl = lo <= sl_px
                hit_tp = hi >= tp_px
            else:
                hit_abort = hi >= abort_px
                hit_sl = hi >= sl_px
                hit_tp = lo <= tp_px
            # Conservative ordering: abort first (deepest), then sl/tp
            if hit_sl and hit_tp:
                exit_px = sl_px; exit_k = k; break
            if hit_tp:
                exit_px = tp_px; exit_k = k; break
            if hit_abort:
                exit_px = abort_px; exit_k = k; break
            if hit_sl:
                exit_px = sl_px; exit_k = k; break
        if exit_px is None:
            exit_k = min(e + p.hold_h - 1, n - 1)
            exit_px = ind["close"][exit_k]

        hold_h = (exit_k - e) + 1
        funding = notional * FUNDING_8H * (hold_h // 8)
        price_chg = chosen_side * (exit_px - entry_px) / entry_px
        roe = price_chg * p.lev * 100.0
        pnl = margin * (roe / 100.0) - fee - funding
        trades.append(Trade(chosen_sym, chosen_side, e, exit_k, hold_h, pnl, roe))
        i = exit_k + p.cooldown_bars
        cooldown = i
    return trades


def aggregate(trades: list[Trade]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0, "wr": 0, "pf": None, "total_pnl": 0, "max_dd": 0,
                "avg_win": 0, "avg_loss": 0, "max_consec_loss": 0, "annual_pct": 0}
    pnls = np.array([t.pnl_usd for t in trades])
    wins = int((pnls > 0).sum())
    wr = wins / n
    total = float(pnls.sum())
    win_sum = float(pnls[pnls > 0].sum())
    loss_abs = float(np.abs(pnls[pnls <= 0]).sum())
    pf = win_sum / loss_abs if loss_abs > 0 else float("inf")
    eq = np.cumsum(pnls)
    peak = np.maximum.accumulate(eq)
    max_dd = float((peak - eq).max())
    avg_win = win_sum / wins if wins else 0
    avg_loss = -loss_abs / (n - wins) if (n - wins) else 0
    streak = max_streak = 0
    for x in pnls:
        if x <= 0:
            streak += 1; max_streak = max(max_streak, streak)
        else:
            streak = 0
    return {
        "n": n, "wr": round(wr, 4),
        "pf": round(pf, 3) if math.isfinite(pf) else None,
        "total_pnl": round(total, 2),
        "max_dd": round(max_dd, 2),
        "avg_win": round(avg_win, 3),
        "avg_loss": round(avg_loss, 3),
        "max_consec_loss": max_streak,
        "annual_pct": round(total / EQUITY * 100, 1),
    }


def mc_ruin(trades: list[Trade], n_runs: int = 5000, ruin_threshold: float = 0.5) -> dict:
    pnls = np.array([t.pnl_usd for t in trades])
    if len(pnls) == 0:
        return {"ruin_pct": 0, "median_final": EQUITY, "p5_final": EQUITY,
                "p5_min_eq": EQUITY, "median_min_eq": EQUITY}
    rng = np.random.default_rng(42)
    ruin = 0
    finals = []; mins = []
    for _ in range(n_runs):
        order = rng.permutation(len(pnls))
        e = EQUITY; m = e; wiped = False
        for j in order:
            e += pnls[j]
            if e < m: m = e
            if e <= 0: wiped = True; break
        finals.append(e if not wiped else 0.0)
        mins.append(m if not wiped else 0.0)
        if m <= EQUITY * (1 - ruin_threshold):
            ruin += 1
    return {
        "ruin_pct": round(ruin / n_runs * 100, 2),
        "median_final": round(float(np.median(finals)), 2),
        "p5_final": round(float(np.percentile(finals, 5)), 2),
        "p5_min_eq": round(float(np.percentile(mins, 5)), 2),
        "median_min_eq": round(float(np.median(mins)), 2),
    }


# ===== Universes =====
PRIORITY_UNIVERSES = {
    "rotation_30x_orig": ["PEPEUSDT", "DOGEUSDT", "ETHUSDT", "SOLUSDT"],
    "memes_first":     ["PEPEUSDT", "WIFUSDT", "DOGEUSDT"],
    "memes_alts":      ["PEPEUSDT", "DOGEUSDT", "WIFUSDT", "OPUSDT", "SUIUSDT"],
    "majors_first":    ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
    "wide_basket":     ["PEPEUSDT", "DOGEUSDT", "WIFUSDT", "ETHUSDT", "SOLUSDT", "BTCUSDT", "OPUSDT", "SUIUSDT"],
    "alt_first":       ["OPUSDT", "NEARUSDT", "SUIUSDT", "ETHUSDT", "UNIUSDT"],
    "PEPE_only":       ["PEPEUSDT"],
    "PEPE_DOGE":       ["PEPEUSDT", "DOGEUSDT"],
    "DOGE_first":      ["DOGEUSDT", "PEPEUSDT", "WIFUSDT"],
    "ETH_first":       ["ETHUSDT", "SOLUSDT", "BTCUSDT"],
}


if __name__ == "__main__":
    print("Library — import into phase scripts.")
