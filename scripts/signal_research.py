#!/usr/bin/env python3
"""
Signal Research & Backtest Engine
=================================
실제 forward return 기반 백테스트. 기존 시스템의 estimated edge가 아닌
실제 가격 변동으로 전략 성과를 측정.

사용법:
    python scripts/signal_research.py
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

# ── 데이터 로드 ──────────────────────────────────────────────
HIST_DIR = Path(__file__).resolve().parent.parent / "quant_runtime" / "historical"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]

# 비용 설정 (bps)
FUTURES_FEE_BPS = 4.0  # taker
SPOT_FEE_BPS = 10.0
SLIPPAGE_BPS = 3.0  # 편도 슬리피지 추정


def load_candles(symbol: str, tf: str) -> list[dict]:
    path = HIST_DIR / symbol / f"{tf}.json"
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


def candles_to_arrays(candles: list[dict]) -> dict[str, np.ndarray]:
    if not candles:
        return {}
    return {
        "time": np.array([c["open_time"] for c in candles], dtype=np.int64),
        "open": np.array([c["open_price"] for c in candles], dtype=np.float64),
        "high": np.array([c["high_price"] for c in candles], dtype=np.float64),
        "low": np.array([c["low_price"] for c in candles], dtype=np.float64),
        "close": np.array([c["close_price"] for c in candles], dtype=np.float64),
        "volume": np.array([c["quote_volume"] for c in candles], dtype=np.float64),
    }


# ── 지표 계산 ──────────────────────────────────────────────
def ema(arr: np.ndarray, period: int) -> np.ndarray:
    result = np.full_like(arr, np.nan)
    if len(arr) < period:
        return result
    alpha = 2.0 / (period + 1)
    result[period - 1] = np.mean(arr[:period])
    for i in range(period, len(arr)):
        result[i] = alpha * arr[i] + (1 - alpha) * result[i - 1]
    return result


def sma(arr: np.ndarray, period: int) -> np.ndarray:
    result = np.full_like(arr, np.nan)
    if len(arr) < period:
        return result
    cumsum = np.cumsum(arr)
    result[period - 1:] = (cumsum[period - 1:] - np.concatenate([[0], cumsum[:-period]])) / period
    return result


def rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    result = np.full_like(close, np.nan)
    if len(close) < period + 1:
        return result
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = np.full(len(delta), np.nan)
    avg_loss = np.full(len(delta), np.nan)
    avg_gain[period - 1] = np.mean(gain[:period])
    avg_loss[period - 1] = np.mean(loss[:period])
    for i in range(period, len(delta)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i]) / period
    rs = avg_gain / np.where(avg_loss == 0, 1e-10, avg_loss)
    rsi_vals = 100.0 - 100.0 / (1.0 + rs)
    result[1:] = rsi_vals
    return result


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    result = np.full_like(close, np.nan)
    if len(close) < period + 1:
        return result
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1]),
        ),
    )
    atr_vals = np.full(len(tr), np.nan)
    atr_vals[period - 1] = np.mean(tr[:period])
    for i in range(period, len(tr)):
        atr_vals[i] = (atr_vals[i - 1] * (period - 1) + tr[i]) / period
    result[1:] = atr_vals
    return result


def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """Average Directional Index"""
    result = np.full_like(close, np.nan)
    n = len(close)
    if n < 2 * period + 1:
        return result
    up_move = high[1:] - high[:-1]
    down_move = low[:-1] - low[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])),
    )
    # Smoothed
    sm_tr = np.full(len(tr), np.nan)
    sm_plus = np.full(len(tr), np.nan)
    sm_minus = np.full(len(tr), np.nan)
    sm_tr[period - 1] = np.sum(tr[:period])
    sm_plus[period - 1] = np.sum(plus_dm[:period])
    sm_minus[period - 1] = np.sum(minus_dm[:period])
    for i in range(period, len(tr)):
        sm_tr[i] = sm_tr[i - 1] - sm_tr[i - 1] / period + tr[i]
        sm_plus[i] = sm_plus[i - 1] - sm_plus[i - 1] / period + plus_dm[i]
        sm_minus[i] = sm_minus[i - 1] - sm_minus[i - 1] / period + minus_dm[i]
    plus_di = 100.0 * sm_plus / np.where(sm_tr == 0, 1e-10, sm_tr)
    minus_di = 100.0 * sm_minus / np.where(sm_tr == 0, 1e-10, sm_tr)
    dx = 100.0 * np.abs(plus_di - minus_di) / np.where((plus_di + minus_di) == 0, 1e-10, plus_di + minus_di)
    # ADX = EMA of DX
    adx_vals = np.full(len(dx), np.nan)
    start = 2 * period - 1
    if start < len(dx):
        adx_vals[start] = np.mean(dx[period - 1:start + 1])
        for i in range(start + 1, len(dx)):
            adx_vals[i] = (adx_vals[i - 1] * (period - 1) + dx[i]) / period
    result[1:] = adx_vals
    return result


def bollinger_bands(close: np.ndarray, period: int = 20, num_std: float = 2.0):
    mid = sma(close, period)
    std = np.full_like(close, np.nan)
    for i in range(period - 1, len(close)):
        std[i] = np.std(close[i - period + 1:i + 1], ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    return mid, upper, lower


def volume_sma(volume: np.ndarray, period: int = 20) -> np.ndarray:
    return sma(volume, period)


# ── 백테스트 엔진 ──────────────────────────────────────────
@dataclass
class Trade:
    entry_idx: int
    exit_idx: int
    side: str  # "long" or "short"
    entry_price: float
    exit_price: float
    return_bps: float
    net_return_bps: float  # after costs
    holding_bars: int


@dataclass
class BacktestResult:
    strategy_name: str
    symbol: str
    timeframe: str
    params: dict
    trades: list[Trade] = field(default_factory=list)
    total_trades: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    total_return_bps: float = 0.0
    avg_return_bps: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_bps: float = 0.0
    sharpe_ratio: float = 0.0

    def compute_stats(self):
        if not self.trades:
            return
        self.total_trades = len(self.trades)
        returns = [t.net_return_bps for t in self.trades]
        self.win_count = sum(1 for r in returns if r > 0)
        self.loss_count = sum(1 for r in returns if r <= 0)
        self.win_rate = self.win_count / self.total_trades if self.total_trades else 0
        self.total_return_bps = sum(returns)
        self.avg_return_bps = np.mean(returns) if returns else 0.0
        gross_profit = sum(r for r in returns if r > 0)
        gross_loss = abs(sum(r for r in returns if r < 0))
        self.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
        # Max drawdown
        equity = np.cumsum(returns)
        peak = np.maximum.accumulate(equity)
        dd = equity - peak
        self.max_drawdown_bps = abs(np.min(dd)) if len(dd) else 0.0
        # Sharpe (per-trade)
        if len(returns) > 1:
            self.sharpe_ratio = np.mean(returns) / np.std(returns, ddof=1) if np.std(returns, ddof=1) > 0 else 0.0
        else:
            self.sharpe_ratio = 0.0


def round_trip_cost_bps(mode: str = "futures") -> float:
    fee = FUTURES_FEE_BPS if mode == "futures" else SPOT_FEE_BPS
    return 2 * fee + 2 * SLIPPAGE_BPS  # entry + exit fees + slippage


# ── 전략 정의 ──────────────────────────────────────────────

def strategy_ma_cross(data: dict, fast: int, slow: int, mode: str = "futures",
                      hold_bars: int = 12, adx_filter: float = 0.0,
                      vol_filter: bool = False, hour_filter: tuple | None = None) -> list[Trade]:
    """MA Crossover: fast EMA crosses above/below slow EMA"""
    close = data["close"]
    time_arr = data["time"]
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    trades = []
    cost = round_trip_cost_bps(mode)

    # Optional filters
    adx_vals = adx(data["high"], data["low"], close) if adx_filter > 0 else None
    vol_sma_vals = volume_sma(data["volume"], 20) if vol_filter else None
    atr_vals = atr(data["high"], data["low"], close) if True else None  # for trailing stop

    i = max(slow + 1, 30)  # warmup
    while i < len(close) - hold_bars:
        if np.isnan(ema_fast[i]) or np.isnan(ema_slow[i]) or np.isnan(ema_fast[i - 1]) or np.isnan(ema_slow[i - 1]):
            i += 1
            continue

        # Hour filter
        if hour_filter is not None:
            hour = (time_arr[i] // 3600000) % 24
            if hour < hour_filter[0] or hour > hour_filter[1]:
                i += 1
                continue

        # ADX filter
        if adx_filter > 0 and adx_vals is not None:
            if np.isnan(adx_vals[i]) or adx_vals[i] < adx_filter:
                i += 1
                continue

        # Volume filter
        if vol_filter and vol_sma_vals is not None:
            if np.isnan(vol_sma_vals[i]) or data["volume"][i] < vol_sma_vals[i] * 0.8:
                i += 1
                continue

        cross_up = ema_fast[i - 1] <= ema_slow[i - 1] and ema_fast[i] > ema_slow[i]
        cross_down = ema_fast[i - 1] >= ema_slow[i - 1] and ema_fast[i] < ema_slow[i]

        if cross_up or cross_down:
            side = "long" if cross_up else "short"
            entry_price = close[i]

            # ATR trailing stop exit or fixed hold
            best_exit_idx = min(i + hold_bars, len(close) - 1)
            exit_idx = best_exit_idx

            if atr_vals is not None and not np.isnan(atr_vals[i]):
                stop_dist = 2.0 * atr_vals[i]
                trail_stop = entry_price - stop_dist if side == "long" else entry_price + stop_dist
                for j in range(i + 1, best_exit_idx + 1):
                    if side == "long":
                        trail_stop = max(trail_stop, close[j] - 2.0 * atr_vals[min(j, len(atr_vals) - 1)])
                        if data["low"][j] <= trail_stop:
                            exit_idx = j
                            break
                    else:
                        trail_stop = min(trail_stop, close[j] + 2.0 * atr_vals[min(j, len(atr_vals) - 1)])
                        if data["high"][j] >= trail_stop:
                            exit_idx = j
                            break

            exit_price = close[exit_idx]
            if side == "long":
                ret_bps = (exit_price - entry_price) / entry_price * 10000
            else:
                ret_bps = (entry_price - exit_price) / entry_price * 10000

            trades.append(Trade(
                entry_idx=i, exit_idx=exit_idx, side=side,
                entry_price=entry_price, exit_price=exit_price,
                return_bps=ret_bps, net_return_bps=ret_bps - cost,
                holding_bars=exit_idx - i,
            ))
            i = exit_idx + 1
        else:
            i += 1
    return trades


def strategy_rsi_reversal(data: dict, period: int = 14, oversold: float = 30,
                          overbought: float = 70, mode: str = "futures",
                          hold_bars: int = 12, adx_filter: float = 0.0,
                          vol_filter: bool = False, hour_filter: tuple | None = None) -> list[Trade]:
    """RSI mean-reversion: buy oversold, sell overbought"""
    close = data["close"]
    time_arr = data["time"]
    rsi_vals = rsi(close, period)
    trades = []
    cost = round_trip_cost_bps(mode)
    adx_vals = adx(data["high"], data["low"], close) if adx_filter > 0 else None
    vol_sma_vals = volume_sma(data["volume"], 20) if vol_filter else None

    i = period + 2
    while i < len(close) - hold_bars:
        if np.isnan(rsi_vals[i]):
            i += 1
            continue

        if hour_filter is not None:
            hour = (time_arr[i] // 3600000) % 24
            if hour < hour_filter[0] or hour > hour_filter[1]:
                i += 1
                continue

        # For RSI reversal, we want LOW ADX (range-bound) - opposite of trend
        if adx_filter > 0 and adx_vals is not None:
            if np.isnan(adx_vals[i]) or adx_vals[i] > adx_filter:  # ADX should be BELOW threshold
                i += 1
                continue

        if vol_filter and vol_sma_vals is not None:
            if np.isnan(vol_sma_vals[i]) or data["volume"][i] < vol_sma_vals[i] * 0.8:
                i += 1
                continue

        side = None
        if rsi_vals[i] <= oversold and rsi_vals[i - 1] > oversold:
            side = "long"
        elif rsi_vals[i] >= overbought and rsi_vals[i - 1] < overbought:
            side = "short"

        if side:
            entry_price = close[i]
            exit_idx = min(i + hold_bars, len(close) - 1)
            # Exit when RSI returns to middle
            for j in range(i + 1, exit_idx + 1):
                if not np.isnan(rsi_vals[j]):
                    if side == "long" and rsi_vals[j] >= 50:
                        exit_idx = j
                        break
                    elif side == "short" and rsi_vals[j] <= 50:
                        exit_idx = j
                        break

            exit_price = close[exit_idx]
            if side == "long":
                ret_bps = (exit_price - entry_price) / entry_price * 10000
            else:
                ret_bps = (entry_price - exit_price) / entry_price * 10000

            trades.append(Trade(
                entry_idx=i, exit_idx=exit_idx, side=side,
                entry_price=entry_price, exit_price=exit_price,
                return_bps=ret_bps, net_return_bps=ret_bps - cost,
                holding_bars=exit_idx - i,
            ))
            i = exit_idx + 1
        else:
            i += 1
    return trades


def strategy_bb_reversal(data: dict, period: int = 20, num_std: float = 2.0,
                         mode: str = "futures", hold_bars: int = 12,
                         adx_filter: float = 0.0, vol_filter: bool = False,
                         hour_filter: tuple | None = None) -> list[Trade]:
    """Bollinger Band reversal: buy at lower band, sell at upper band"""
    close = data["close"]
    time_arr = data["time"]
    mid, upper, lower = bollinger_bands(close, period, num_std)
    trades = []
    cost = round_trip_cost_bps(mode)
    adx_vals = adx(data["high"], data["low"], close) if adx_filter > 0 else None
    vol_sma_vals = volume_sma(data["volume"], 20) if vol_filter else None

    i = period + 1
    while i < len(close) - hold_bars:
        if np.isnan(mid[i]):
            i += 1
            continue

        if hour_filter is not None:
            hour = (time_arr[i] // 3600000) % 24
            if hour < hour_filter[0] or hour > hour_filter[1]:
                i += 1
                continue

        if adx_filter > 0 and adx_vals is not None:
            if np.isnan(adx_vals[i]) or adx_vals[i] > adx_filter:  # low ADX = range
                i += 1
                continue

        if vol_filter and vol_sma_vals is not None:
            if np.isnan(vol_sma_vals[i]) or data["volume"][i] < vol_sma_vals[i] * 0.8:
                i += 1
                continue

        side = None
        if close[i] <= lower[i] and close[i - 1] > lower[i - 1]:
            side = "long"
        elif close[i] >= upper[i] and close[i - 1] < upper[i - 1]:
            side = "short"

        if side:
            entry_price = close[i]
            exit_idx = min(i + hold_bars, len(close) - 1)
            for j in range(i + 1, exit_idx + 1):
                if not np.isnan(mid[j]):
                    if side == "long" and close[j] >= mid[j]:
                        exit_idx = j
                        break
                    elif side == "short" and close[j] <= mid[j]:
                        exit_idx = j
                        break

            exit_price = close[exit_idx]
            if side == "long":
                ret_bps = (exit_price - entry_price) / entry_price * 10000
            else:
                ret_bps = (entry_price - exit_price) / entry_price * 10000

            trades.append(Trade(
                entry_idx=i, exit_idx=exit_idx, side=side,
                entry_price=entry_price, exit_price=exit_price,
                return_bps=ret_bps, net_return_bps=ret_bps - cost,
                holding_bars=exit_idx - i,
            ))
            i = exit_idx + 1
        else:
            i += 1
    return trades


def strategy_momentum_breakout(data: dict, lookback: int = 20, mode: str = "futures",
                               hold_bars: int = 24, adx_filter: float = 25.0,
                               vol_filter: bool = True, hour_filter: tuple | None = None) -> list[Trade]:
    """Momentum breakout: buy new highs, sell new lows with trend confirmation"""
    close = data["close"]
    high = data["high"]
    low = data["low"]
    time_arr = data["time"]
    trades = []
    cost = round_trip_cost_bps(mode)
    adx_vals = adx(high, low, close)
    vol_sma_vals = volume_sma(data["volume"], 20)
    atr_vals = atr(high, low, close)

    i = lookback + 1
    while i < len(close) - hold_bars:
        if hour_filter is not None:
            hour = (time_arr[i] // 3600000) % 24
            if hour < hour_filter[0] or hour > hour_filter[1]:
                i += 1
                continue

        if adx_filter > 0 and (np.isnan(adx_vals[i]) or adx_vals[i] < adx_filter):
            i += 1
            continue

        if vol_filter and (np.isnan(vol_sma_vals[i]) or data["volume"][i] < vol_sma_vals[i] * 1.2):
            i += 1
            continue

        highest = np.max(high[i - lookback:i])
        lowest = np.min(low[i - lookback:i])

        side = None
        if close[i] > highest:
            side = "long"
        elif close[i] < lowest:
            side = "short"

        if side:
            entry_price = close[i]
            exit_idx = min(i + hold_bars, len(close) - 1)

            # ATR trailing stop
            if not np.isnan(atr_vals[i]):
                stop_dist = 2.5 * atr_vals[i]
                trail_stop = entry_price - stop_dist if side == "long" else entry_price + stop_dist
                for j in range(i + 1, exit_idx + 1):
                    a = atr_vals[min(j, len(atr_vals) - 1)]
                    if np.isnan(a):
                        a = atr_vals[i]
                    if side == "long":
                        trail_stop = max(trail_stop, close[j] - 2.5 * a)
                        if low[j] <= trail_stop:
                            exit_idx = j
                            break
                    else:
                        trail_stop = min(trail_stop, close[j] + 2.5 * a)
                        if high[j] >= trail_stop:
                            exit_idx = j
                            break

            exit_price = close[exit_idx]
            if side == "long":
                ret_bps = (exit_price - entry_price) / entry_price * 10000
            else:
                ret_bps = (entry_price - exit_price) / entry_price * 10000

            trades.append(Trade(
                entry_idx=i, exit_idx=exit_idx, side=side,
                entry_price=entry_price, exit_price=exit_price,
                return_bps=ret_bps, net_return_bps=ret_bps - cost,
                holding_bars=exit_idx - i,
            ))
            i = exit_idx + 1
        else:
            i += 1
    return trades


def strategy_mtf_trend(data_5m: dict, data_1h: dict, mode: str = "futures",
                       hold_bars_5m: int = 48, fast: int = 9, slow: int = 21,
                       adx_filter: float = 20.0, vol_filter: bool = False,
                       hour_filter: tuple | None = None) -> list[Trade]:
    """Multi-timeframe: 1h trend direction + 5m entry timing"""
    close_5m = data_5m["close"]
    time_5m = data_5m["time"]
    close_1h = data_1h["close"]
    time_1h = data_1h["time"]

    # 1h indicators
    ema20_1h = ema(close_1h, 20)
    ema50_1h = ema(close_1h, 50)
    adx_1h = adx(data_1h["high"], data_1h["low"], close_1h)

    # 5m indicators
    ema_fast_5m = ema(close_5m, fast)
    ema_slow_5m = ema(close_5m, slow)
    vol_sma_5m = volume_sma(data_5m["volume"], 20)
    atr_5m = atr(data_5m["high"], data_5m["low"], close_5m)

    trades = []
    cost = round_trip_cost_bps(mode)

    def get_1h_trend(ts: int) -> int:
        """Find 1h candle for given 5m timestamp, return trend direction"""
        idx = np.searchsorted(time_1h, ts, side="right") - 1
        if idx < 50 or idx >= len(close_1h):
            return 0
        if np.isnan(ema20_1h[idx]) or np.isnan(ema50_1h[idx]):
            return 0
        if adx_filter > 0 and (np.isnan(adx_1h[idx]) or adx_1h[idx] < adx_filter):
            return 0
        if ema20_1h[idx] > ema50_1h[idx] and close_1h[idx] > ema20_1h[idx]:
            return 1
        elif ema20_1h[idx] < ema50_1h[idx] and close_1h[idx] < ema20_1h[idx]:
            return -1
        return 0

    i = max(slow + 1, 60)
    while i < len(close_5m) - hold_bars_5m:
        if np.isnan(ema_fast_5m[i]) or np.isnan(ema_slow_5m[i]):
            i += 1
            continue

        if hour_filter is not None:
            hour = (time_5m[i] // 3600000) % 24
            if hour < hour_filter[0] or hour > hour_filter[1]:
                i += 1
                continue

        if vol_filter and (np.isnan(vol_sma_5m[i]) or data_5m["volume"][i] < vol_sma_5m[i] * 0.8):
            i += 1
            continue

        trend = get_1h_trend(time_5m[i])
        if trend == 0:
            i += 1
            continue

        cross_up = ema_fast_5m[i - 1] <= ema_slow_5m[i - 1] and ema_fast_5m[i] > ema_slow_5m[i]
        cross_down = ema_fast_5m[i - 1] >= ema_slow_5m[i - 1] and ema_fast_5m[i] < ema_slow_5m[i]

        side = None
        if cross_up and trend == 1:
            side = "long"
        elif cross_down and trend == -1:
            side = "short"

        if side:
            entry_price = close_5m[i]
            exit_idx = min(i + hold_bars_5m, len(close_5m) - 1)

            # ATR trailing stop
            if not np.isnan(atr_5m[i]):
                stop_dist = 2.0 * atr_5m[i]
                trail_stop = entry_price - stop_dist if side == "long" else entry_price + stop_dist
                for j in range(i + 1, exit_idx + 1):
                    a = atr_5m[min(j, len(atr_5m) - 1)]
                    if np.isnan(a):
                        a = atr_5m[i]
                    if side == "long":
                        trail_stop = max(trail_stop, close_5m[j] - 2.0 * a)
                        if data_5m["low"][j] <= trail_stop:
                            exit_idx = j
                            break
                    else:
                        trail_stop = min(trail_stop, close_5m[j] + 2.0 * a)
                        if data_5m["high"][j] >= trail_stop:
                            exit_idx = j
                            break

            exit_price = close_5m[exit_idx]
            if side == "long":
                ret_bps = (exit_price - entry_price) / entry_price * 10000
            else:
                ret_bps = (entry_price - exit_price) / entry_price * 10000

            trades.append(Trade(
                entry_idx=i, exit_idx=exit_idx, side=side,
                entry_price=entry_price, exit_price=exit_price,
                return_bps=ret_bps, net_return_bps=ret_bps - cost,
                holding_bars=exit_idx - i,
            ))
            i = exit_idx + 1
        else:
            i += 1
    return trades


# ── 실행 ──────────────────────────────────────────────────
def run_all_strategies():
    print("=" * 90)
    print("SIGNAL RESEARCH — Forward Return Based Backtest")
    print("=" * 90)

    results: list[BacktestResult] = []

    for symbol in SYMBOLS:
        print(f"\n{'─' * 70}")
        print(f"  {symbol}")
        print(f"{'─' * 70}")

        data_5m = candles_to_arrays(load_candles(symbol, "5m"))
        data_1h = candles_to_arrays(load_candles(symbol, "1h"))
        data_4h = candles_to_arrays(load_candles(symbol, "4h"))

        if not data_1h:
            print(f"  [SKIP] No 1h data for {symbol}")
            continue

        # ────────────────────────────────────────────────
        # Strategy 1: MA Crossover variants on 1h
        # ────────────────────────────────────────────────
        ma_params = [
            {"fast": 9, "slow": 21, "hold_bars": 12},
            {"fast": 9, "slow": 21, "hold_bars": 24},
            {"fast": 12, "slow": 26, "hold_bars": 12},
            {"fast": 12, "slow": 26, "hold_bars": 24},
            {"fast": 20, "slow": 50, "hold_bars": 24},
            {"fast": 20, "slow": 50, "hold_bars": 48},
            # With ADX filter
            {"fast": 9, "slow": 21, "hold_bars": 12, "adx_filter": 25.0},
            {"fast": 12, "slow": 26, "hold_bars": 24, "adx_filter": 25.0},
            # With volume filter
            {"fast": 9, "slow": 21, "hold_bars": 12, "vol_filter": True},
            {"fast": 12, "slow": 26, "hold_bars": 24, "vol_filter": True},
            # With ADX + volume
            {"fast": 9, "slow": 21, "hold_bars": 12, "adx_filter": 25.0, "vol_filter": True},
            # Hour filter (Asian/London/NY sessions)
            {"fast": 9, "slow": 21, "hold_bars": 12, "hour_filter": (8, 20)},  # European+US
            {"fast": 9, "slow": 21, "hold_bars": 12, "hour_filter": (13, 21)},  # US session
        ]
        for p in ma_params:
            trades = strategy_ma_cross(data_1h, **p)
            r = BacktestResult(strategy_name="MA_Cross_1h", symbol=symbol, timeframe="1h", params=p, trades=trades)
            r.compute_stats()
            results.append(r)

        # ────────────────────────────────────────────────
        # Strategy 2: RSI Reversal variants on 1h
        # ────────────────────────────────────────────────
        rsi_params = [
            {"period": 14, "oversold": 30, "overbought": 70, "hold_bars": 12},
            {"period": 14, "oversold": 25, "overbought": 75, "hold_bars": 12},
            {"period": 14, "oversold": 30, "overbought": 70, "hold_bars": 24},
            {"period": 7, "oversold": 25, "overbought": 75, "hold_bars": 6},
            {"period": 14, "oversold": 30, "overbought": 70, "hold_bars": 12, "adx_filter": 30.0},  # Low ADX
            {"period": 14, "oversold": 30, "overbought": 70, "hold_bars": 12, "vol_filter": True},
        ]
        for p in rsi_params:
            trades = strategy_rsi_reversal(data_1h, **p)
            r = BacktestResult(strategy_name="RSI_Rev_1h", symbol=symbol, timeframe="1h", params=p, trades=trades)
            r.compute_stats()
            results.append(r)

        # ────────────────────────────────────────────────
        # Strategy 3: Bollinger Band Reversal on 1h
        # ────────────────────────────────────────────────
        bb_params = [
            {"period": 20, "num_std": 2.0, "hold_bars": 12},
            {"period": 20, "num_std": 2.5, "hold_bars": 12},
            {"period": 20, "num_std": 2.0, "hold_bars": 24},
            {"period": 20, "num_std": 2.0, "hold_bars": 12, "adx_filter": 30.0},
            {"period": 20, "num_std": 2.0, "hold_bars": 12, "vol_filter": True},
        ]
        for p in bb_params:
            trades = strategy_bb_reversal(data_1h, **p)
            r = BacktestResult(strategy_name="BB_Rev_1h", symbol=symbol, timeframe="1h", params=p, trades=trades)
            r.compute_stats()
            results.append(r)

        # ────────────────────────────────────────────────
        # Strategy 4: Momentum Breakout on 1h
        # ────────────────────────────────────────────────
        mo_params = [
            {"lookback": 20, "hold_bars": 24, "adx_filter": 25.0, "vol_filter": True},
            {"lookback": 20, "hold_bars": 48, "adx_filter": 25.0, "vol_filter": True},
            {"lookback": 30, "hold_bars": 24, "adx_filter": 20.0, "vol_filter": True},
            {"lookback": 20, "hold_bars": 24, "adx_filter": 25.0, "vol_filter": False},
        ]
        for p in mo_params:
            trades = strategy_momentum_breakout(data_1h, **p)
            r = BacktestResult(strategy_name="Momentum_1h", symbol=symbol, timeframe="1h", params=p, trades=trades)
            r.compute_stats()
            results.append(r)

        # ────────────────────────────────────────────────
        # Strategy 5: MTF Trend (1h direction + 5m entry)
        # ────────────────────────────────────────────────
        if data_5m:
            mtf_params = [
                {"fast": 9, "slow": 21, "hold_bars_5m": 48, "adx_filter": 20.0},
                {"fast": 9, "slow": 21, "hold_bars_5m": 96, "adx_filter": 20.0},
                {"fast": 5, "slow": 13, "hold_bars_5m": 36, "adx_filter": 25.0},
                {"fast": 9, "slow": 21, "hold_bars_5m": 48, "adx_filter": 20.0, "vol_filter": True},
                {"fast": 9, "slow": 21, "hold_bars_5m": 48, "adx_filter": 20.0, "hour_filter": (8, 20)},
            ]
            for p in mtf_params:
                trades = strategy_mtf_trend(data_5m, data_1h, **p)
                r = BacktestResult(strategy_name="MTF_Trend", symbol=symbol, timeframe="5m+1h", params=p, trades=trades)
                r.compute_stats()
                results.append(r)

    # ── 결과 출력 ──────────────────────────────────────
    print("\n\n" + "=" * 90)
    print("  RESULTS SUMMARY")
    print("=" * 90)

    # Sort by profit_factor descending
    results.sort(key=lambda r: r.profit_factor if r.profit_factor != float("inf") else 999, reverse=True)

    # Profitable strategies
    profitable = [r for r in results if r.profit_factor > 1.0 and r.total_trades >= 5]
    unprofitable = [r for r in results if r.profit_factor <= 1.0 and r.total_trades >= 5]
    no_trades = [r for r in results if r.total_trades < 5]

    print(f"\n총 조합: {len(results)}")
    print(f"수익 (PF>1.0, trades>=5): {len(profitable)}")
    print(f"손실: {len(unprofitable)}")
    print(f"거래 부족 (<5): {len(no_trades)}")

    if profitable:
        print(f"\n{'─' * 90}")
        print("  TOP PROFITABLE STRATEGIES (PF > 1.0)")
        print(f"{'─' * 90}")
        print(f"{'Strategy':<16} {'Symbol':<10} {'TF':<8} {'Trades':>6} {'WinR':>6} {'PF':>6} {'TotBps':>8} {'AvgBps':>7} {'MaxDD':>8} {'Sharpe':>7}  Params")
        print(f"{'─' * 90}")
        for r in profitable[:40]:
            params_str = ", ".join(f"{k}={v}" for k, v in r.params.items())
            pf_str = f"{r.profit_factor:.2f}" if r.profit_factor < 100 else "inf"
            print(f"{r.strategy_name:<16} {r.symbol:<10} {r.timeframe:<8} {r.total_trades:>6} {r.win_rate:>5.1%} {pf_str:>6} {r.total_return_bps:>8.1f} {r.avg_return_bps:>7.1f} {r.max_drawdown_bps:>8.1f} {r.sharpe_ratio:>7.3f}  {params_str}")

    if unprofitable:
        print(f"\n{'─' * 90}")
        print("  LOSING STRATEGIES (sample)")
        print(f"{'─' * 90}")
        print(f"{'Strategy':<16} {'Symbol':<10} {'TF':<8} {'Trades':>6} {'WinR':>6} {'PF':>6} {'TotBps':>8} {'AvgBps':>7}  Params")
        for r in unprofitable[-10:]:
            params_str = ", ".join(f"{k}={v}" for k, v in r.params.items())
            print(f"{r.strategy_name:<16} {r.symbol:<10} {r.timeframe:<8} {r.total_trades:>6} {r.win_rate:>5.1%} {r.profit_factor:>6.2f} {r.total_return_bps:>8.1f} {r.avg_return_bps:>7.1f}  {params_str}")

    # ── 분석: 어떤 필터가 도움이 되는지 ──────────────
    print(f"\n\n{'=' * 90}")
    print("  FILTER ANALYSIS")
    print(f"{'=' * 90}")

    # Group by strategy+symbol, compare with/without filters
    from collections import defaultdict
    groups = defaultdict(list)
    for r in results:
        if r.total_trades >= 3:
            key = (r.strategy_name, r.symbol)
            groups[key].append(r)

    print(f"\n{'Strategy':<16} {'Symbol':<10} {'Best PF':>7} {'Best WR':>7} {'Best Params'}")
    print(f"{'─' * 90}")
    for key, rs in sorted(groups.items()):
        best = max(rs, key=lambda x: x.profit_factor if x.profit_factor < 100 else 0)
        if best.profit_factor > 0.5:
            params_str = ", ".join(f"{k}={v}" for k, v in best.params.items())
            pf_str = f"{best.profit_factor:.2f}" if best.profit_factor < 100 else "inf"
            print(f"{key[0]:<16} {key[1]:<10} {pf_str:>7} {best.win_rate:>6.1%} {params_str}")

    # ── JSON 결과 저장 ──────────────────────────────
    output_dir = Path(__file__).resolve().parent.parent / "quant_runtime" / "output" / "signal_research"
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = []
    for r in results:
        summary.append({
            "strategy": r.strategy_name,
            "symbol": r.symbol,
            "timeframe": r.timeframe,
            "params": r.params,
            "total_trades": r.total_trades,
            "win_rate": round(r.win_rate, 4),
            "profit_factor": round(r.profit_factor, 4) if r.profit_factor < 1000 else None,
            "total_return_bps": round(r.total_return_bps, 2),
            "avg_return_bps": round(r.avg_return_bps, 2),
            "max_drawdown_bps": round(r.max_drawdown_bps, 2),
            "sharpe_ratio": round(r.sharpe_ratio, 4),
        })

    with open(output_dir / "backtest_results.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n결과 저장: {output_dir / 'backtest_results.json'}")

    return results


if __name__ == "__main__":
    run_all_strategies()
