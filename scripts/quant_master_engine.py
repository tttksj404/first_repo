#!/usr/bin/env python3
"""Master backtest engine — strategy library + cost model + validation.

Used by Phase 1-4 scripts. All numbers in USD. $50 equity baseline.

Strategies:
  - momentum_long_short: 168h price momentum threshold, EMA filter
  - atr_breakout (b3_msb-like): close>upper N-bar high + ATR buffer + ADX
  - x1_mean_rev: RSI 30/70 + MACD (S3 baseline)
  - x4_tight: RSI 25/70 + MACD + vol≥1.3
  - bb_squeeze: low-vol BB then break out
  - turnaround_long: PEPE-style long-only, big TP small price move

Cost model:
  fee_per_round = notional * COST_RT (0.12%)
  funding = notional * 0.0001 * (hold_hours // 8)
  slippage_extra = notional * extra_bps/5000 (round-trip, both legs)

Output to /quant_runtime/master_engine_runs/
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Callable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "quant_runtime" / "historical"
OUT_DIR = ROOT / "quant_runtime" / "master_engine_runs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

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
        [
            [r["open_time"], r["open_price"], r["high_price"], r["low_price"], r["close_price"], r.get("base_volume", 0.0)]
            for r in raw
        ],
        dtype=np.float64,
    )


def compute_indicators(arr: np.ndarray) -> dict:
    close = arr[:, 4]
    high = arr[:, 2]
    low = arr[:, 3]
    vol = arr[:, 5]
    n = len(close)
    # RSI(14)
    delta = np.diff(close, prepend=close[0])
    up = np.maximum(delta, 0)
    dn = np.maximum(-delta, 0)
    rsi = np.zeros(n)
    avg_up = avg_dn = 0.0
    for i in range(1, n):
        if i <= 14:
            avg_up = np.mean(up[1 : i + 1])
            avg_dn = np.mean(dn[1 : i + 1])
        else:
            avg_up = (avg_up * 13 + up[i]) / 14
            avg_dn = (avg_dn * 13 + dn[i]) / 14
        rsi[i] = 100 if avg_dn == 0 else 100 - 100 / (1 + avg_up / avg_dn)
    # EMA helpers
    def ema(x, p):
        a = 2.0 / (p + 1)
        out = np.empty(n)
        out[0] = x[0]
        for i in range(1, n):
            out[i] = a * x[i] + (1 - a) * out[i - 1]
        return out
    ema12 = ema(close, 12)
    ema26 = ema(close, 26)
    macd = ema12 - ema26
    macd_sig = ema(macd, 9)
    ema20 = ema(close, 20)
    ema50 = ema(close, 50)
    ema100 = ema(close, 100)
    # ATR(14) via EMA on TR
    prev_close = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    atr = ema(tr, 14)
    # Volume MA(20)
    vol_ma = np.zeros(n)
    for i in range(n):
        s = max(0, i - 20)
        vol_ma[i] = np.mean(vol[s : i + 1]) if i > 0 else vol[i]
    vol_r = np.where(vol_ma > 0, vol / vol_ma, 1.0)
    # ADX(14) — simplified
    pdm = np.zeros(n); mdm = np.zeros(n)
    for i in range(1, n):
        hd = high[i] - high[i - 1]; ld = low[i - 1] - low[i]
        pdm[i] = max(hd, 0) if hd > ld else 0
        mdm[i] = max(ld, 0) if ld > hd else 0
    adx = np.zeros(n)
    for i in range(15, n):
        a = np.mean(tr[i - 13 : i + 1])
        if a > 0:
            pdi = np.mean(pdm[i - 13 : i + 1]) / a * 100
            mdi = np.mean(mdm[i - 13 : i + 1]) / a * 100
            denom = max(pdi + mdi, 0.01)
            adx[i] = abs(pdi - mdi) / denom * 100
    # Momentum 168h (7-day)
    mom168 = np.zeros(n)
    for i in range(168, n):
        mom168[i] = (close[i] - close[i - 168]) / close[i - 168]
    # 20-bar high/low for breakout
    high20 = np.zeros(n); low20 = np.zeros(n)
    for i in range(n):
        s = max(0, i - 20)
        high20[i] = np.max(high[s : i + 1]) if i > 0 else high[i]
        low20[i] = np.min(low[s : i + 1]) if i > 0 else low[i]
    return {
        "close": close, "high": high, "low": low, "vol": vol,
        "rsi": rsi, "macd": macd, "macd_sig": macd_sig,
        "ema20": ema20, "ema50": ema50, "ema100": ema100,
        "atr": atr, "vol_ma": vol_ma, "vol_r": vol_r,
        "adx": adx, "mom168": mom168,
        "high20": high20, "low20": low20,
    }


@dataclass
class Trade:
    symbol: str
    side: int          # +1 long, -1 short
    entry_idx: int
    exit_idx: int
    hold_h: int
    pnl_usd: float     # at given lev/notional, fees+funding+slip already deducted
    roe_pct: float
    is_win: bool


@dataclass
class StratParams:
    name: str
    # Common
    lev: float = 1.0
    margin_pct: float = 1.0      # margin = EQUITY * margin_pct
    tp_atr: float = 0.5
    sl_atr: float = 3.0
    hold: int = 24
    extra_bps: float = 0.0
    # Strategy-specific kwargs
    rsi_long: float = 30.0
    rsi_short: float = 70.0
    vol_min: float = 1.0
    mom_min: float = 0.03
    adx_min: float = 0.0
    bb_squeeze_pct: float = 20.0
    bb_lookback: int = 50
    breakout_atr_buf: float = 0.25
    # Turnaround-style (PEPE 30x)
    tp_roe: Optional[float] = None      # if set, use ROE-based TP instead of ATR
    sl_roe: Optional[float] = None
    long_only: bool = False
    cooldown_bars: int = 2


def collect_trades(symbol: str, ind: dict, p: StratParams,
                    idx_start: int = 0, idx_end: Optional[int] = None) -> list[Trade]:
    """Single-symbol, single-strategy trade collector."""
    close = ind["close"]; high = ind["high"]; low = ind["low"]
    rsi = ind["rsi"]; macd = ind["macd"]; macd_sig = ind["macd_sig"]
    ema20 = ind["ema20"]; ema50 = ind["ema50"]
    atr = ind["atr"]; vol_r = ind["vol_r"]; adx = ind["adx"]
    mom168 = ind["mom168"]; high20 = ind["high20"]; low20 = ind["low20"]

    margin = EQUITY * p.margin_pct
    notional = margin * p.lev
    fee = notional * (COST_RT + 2 * p.extra_bps / 10000.0)

    if idx_end is None:
        idx_end = len(close)
    trades: list[Trade] = []
    cooldown = 0
    end = min(idx_end, len(close) - p.hold - 2)
    i = max(idx_start, 200)
    while i < end:
        if i < cooldown:
            i += 1
            continue
        # ----- Signal selection -----
        side = 0
        if p.name == "x1":
            if rsi[i] <= p.rsi_long and macd[i] > macd_sig[i] and vol_r[i] >= p.vol_min:
                side = 1
            elif (not p.long_only) and rsi[i] >= p.rsi_short and macd[i] < macd_sig[i] and vol_r[i] >= p.vol_min:
                side = -1
        elif p.name == "x4":
            if rsi[i] <= 25 and macd[i] > macd_sig[i] and vol_r[i] >= 1.3:
                side = 1
            elif (not p.long_only) and rsi[i] >= 70 and macd[i] < macd_sig[i] and vol_r[i] >= 1.3:
                side = -1
        elif p.name == "momentum":
            # 7-day momentum + EMA20 > EMA50 + adx>min
            if i < 168:
                i += 1
                continue
            if mom168[i] >= p.mom_min and ema20[i] > ema50[i] and adx[i] >= p.adx_min:
                side = 1
            elif (not p.long_only) and mom168[i] <= -p.mom_min and ema20[i] < ema50[i] and adx[i] >= p.adx_min:
                side = -1
        elif p.name == "atr_breakout":
            # b3_msb-like: close > 20-bar high + ATR buffer
            if close[i] > high20[i - 1] + p.breakout_atr_buf * atr[i] and adx[i] >= p.adx_min:
                side = 1
            elif (not p.long_only) and close[i] < low20[i - 1] - p.breakout_atr_buf * atr[i] and adx[i] >= p.adx_min:
                side = -1
        elif p.name == "turnaround":
            # PEPE long-only turnaround: rsi oversold + bouncing
            if rsi[i] <= 25 and close[i] > close[i - 1] and macd[i] > macd_sig[i]:
                side = 1
        else:
            i += 1
            continue

        if side == 0:
            i += 1
            continue
        e = i + 1
        if e >= len(close):
            break
        entry_px = close[e - 1] if e == 0 else close[e - 1]  # use close at signal bar = open at next
        entry_px = close[i]  # simpler: use close at signal bar
        if entry_px <= 0 or atr[i] <= 0:
            i += 1
            continue

        # ----- Exit logic -----
        if p.tp_roe is not None and p.sl_roe is not None:
            # ROE-based exit (turnaround/momentum style)
            tp_price_pct = p.tp_roe / 100.0 / p.lev
            sl_price_pct = p.sl_roe / 100.0 / p.lev  # negative
            tp_px = entry_px * (1 + side * tp_price_pct)
            sl_px = entry_px * (1 + side * sl_price_pct)
        else:
            tp_px = entry_px + side * p.tp_atr * atr[i]
            sl_px = entry_px - side * p.sl_atr * atr[i]

        exit_px = None
        exit_k = None
        for k in range(e, min(e + p.hold, len(close))):
            hi, lo = high[k], low[k]
            hit_sl = (lo <= sl_px) if side == 1 else (hi >= sl_px)
            hit_tp = (hi >= tp_px) if side == 1 else (lo <= tp_px)
            if hit_sl and hit_tp:
                exit_px = sl_px; exit_k = k; break
            if hit_tp:
                exit_px = tp_px; exit_k = k; break
            if hit_sl:
                exit_px = sl_px; exit_k = k; break
        if exit_px is None:
            exit_k = min(e + p.hold - 1, len(close) - 1)
            exit_px = close[exit_k]

        hold_h = (exit_k - e) + 1
        funding = notional * FUNDING_8H * (hold_h // 8)
        price_chg = side * (exit_px - entry_px) / entry_px
        roe = price_chg * p.lev * 100  # ROE %
        # PnL on margin: margin * (roe/100), then fees+funding
        pnl = margin * (roe / 100.0) - fee - funding
        trades.append(Trade(symbol, side, e, exit_k, hold_h, pnl, roe, pnl > 0))
        i = e + 1
        cooldown = i + p.cooldown_bars
    return trades


def aggregate(trades: list[Trade]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0, "wr": 0, "pf": None, "total_pnl": 0, "max_dd": 0,
                "avg_win": 0, "avg_loss": 0, "max_consec_loss": 0,
                "annual_pct": 0}
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
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return {
        "n": n,
        "wr": round(wr, 4),
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
    finals = []
    mins = []
    for _ in range(n_runs):
        order = rng.permutation(len(pnls))
        e = EQUITY
        m = e
        wiped = False
        for j in order:
            e += pnls[j]
            if e < m:
                m = e
            if e <= 0:
                wiped = True
                break
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


# ===== Helper: build & run a strategy across universe =====

def run_strategy(symbols: list[str], data_cache: dict, p: StratParams,
                  idx_start: int = 0, idx_end: Optional[int] = None) -> list[Trade]:
    out: list[Trade] = []
    for s in symbols:
        if s not in data_cache:
            continue
        ind = data_cache[s]
        out.extend(collect_trades(s, ind, p, idx_start, idx_end))
    return out


# ===== Universes =====
UNIVERSES = {
    "PEPE_only": ["PEPEUSDT"],
    "WIF_only": ["WIFUSDT"],
    "DOGE_only": ["DOGEUSDT"],
    "memes": ["PEPEUSDT", "WIFUSDT", "DOGEUSDT"],
    "top5_alts": ["OPUSDT", "NEARUSDT", "SUIUSDT", "ETHUSDT", "UNIUSDT"],
    "majors": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    "all20": [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
        "ADAUSDT", "APTUSDT", "ARBUSDT", "AVAXUSDT", "BNBUSDT",
        "DOTUSDT", "LINKUSDT", "LTCUSDT", "NEARUSDT", "OPUSDT",
        "PEPEUSDT", "SUIUSDT", "UNIUSDT", "WIFUSDT", "MATICUSDT",
    ],
}


if __name__ == "__main__":
    print("This is a library — import into phase scripts.")
