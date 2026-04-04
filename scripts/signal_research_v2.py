#!/usr/bin/env python3
"""
Signal Research V2 — 심화 최적화
================================
Phase 1에서 발견한 핵심 인사이트:
- MA Cross + ADX >= 25 가 최강 조합
- 볼린저밴드 역추세는 크립토에서 작동 안 함
- 추세추종 + 필터 조합이 유일한 수익 전략

V2에서 시도하는 것:
1. MA Cross + ADX 파라미터 정밀 탐색
2. ATR 변동성 필터 추가
3. 볼륨 확인 강화
4. 복합 진입 조건 (MA Cross + RSI 확인)
5. 심볼별 최적 파라미터
6. 레버리지 반영 수익 계산
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from itertools import product

import numpy as np

HIST_DIR = Path(__file__).resolve().parent.parent / "quant_runtime" / "historical"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
FUTURES_FEE_BPS = 4.0
SLIPPAGE_BPS = 3.0


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


# ── 지표 ──────────────────────────────────────────────
def ema(arr, period):
    result = np.full_like(arr, np.nan, dtype=np.float64)
    if len(arr) < period:
        return result
    alpha = 2.0 / (period + 1)
    result[period - 1] = np.mean(arr[:period])
    for i in range(period, len(arr)):
        result[i] = alpha * arr[i] + (1 - alpha) * result[i - 1]
    return result


def sma(arr, period):
    result = np.full_like(arr, np.nan, dtype=np.float64)
    if len(arr) < period:
        return result
    cs = np.cumsum(arr)
    result[period - 1:] = (cs[period - 1:] - np.concatenate([[0], cs[:-period]])) / period
    return result


def rsi(close, period=14):
    result = np.full_like(close, np.nan)
    if len(close) < period + 1:
        return result
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    ag = np.full(len(delta), np.nan)
    al = np.full(len(delta), np.nan)
    ag[period - 1] = np.mean(gain[:period])
    al[period - 1] = np.mean(loss[:period])
    for i in range(period, len(delta)):
        ag[i] = (ag[i - 1] * (period - 1) + gain[i]) / period
        al[i] = (al[i - 1] * (period - 1) + loss[i]) / period
    rs = ag / np.where(al == 0, 1e-10, al)
    result[1:] = 100.0 - 100.0 / (1.0 + rs)
    return result


def atr(high, low, close, period=14):
    result = np.full_like(close, np.nan)
    if len(close) < period + 1:
        return result
    tr = np.maximum(high[1:] - low[1:], np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])))
    av = np.full(len(tr), np.nan)
    av[period - 1] = np.mean(tr[:period])
    for i in range(period, len(tr)):
        av[i] = (av[i - 1] * (period - 1) + tr[i]) / period
    result[1:] = av
    return result


def adx(high, low, close, period=14):
    result = np.full_like(close, np.nan)
    n = len(close)
    if n < 2 * period + 1:
        return result
    up = high[1:] - high[:-1]
    down = low[:-1] - low[1:]
    pdm = np.where((up > down) & (up > 0), up, 0.0)
    mdm = np.where((down > up) & (down > 0), down, 0.0)
    tr = np.maximum(high[1:] - low[1:], np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])))
    st = np.full(len(tr), np.nan)
    sp = np.full(len(tr), np.nan)
    sm = np.full(len(tr), np.nan)
    st[period - 1] = np.sum(tr[:period])
    sp[period - 1] = np.sum(pdm[:period])
    sm[period - 1] = np.sum(mdm[:period])
    for i in range(period, len(tr)):
        st[i] = st[i - 1] - st[i - 1] / period + tr[i]
        sp[i] = sp[i - 1] - sp[i - 1] / period + pdm[i]
        sm[i] = sm[i - 1] - sm[i - 1] / period + mdm[i]
    pdi = 100.0 * sp / np.where(st == 0, 1e-10, st)
    mdi = 100.0 * sm / np.where(st == 0, 1e-10, st)
    dx = 100.0 * np.abs(pdi - mdi) / np.where((pdi + mdi) == 0, 1e-10, pdi + mdi)
    av = np.full(len(dx), np.nan)
    start = 2 * period - 1
    if start < len(dx):
        av[start] = np.mean(dx[period - 1:start + 1])
        for i in range(start + 1, len(dx)):
            av[i] = (av[i - 1] * (period - 1) + dx[i]) / period
    result[1:] = av
    return result


def volume_sma(vol, period=20):
    return sma(vol, period)


# ── 트레이드 ──────────────────────────────────────────
@dataclass
class Trade:
    entry_idx: int
    exit_idx: int
    side: str
    entry_price: float
    exit_price: float
    return_bps: float
    net_return_bps: float
    holding_bars: int


def round_trip_cost(mode="futures"):
    fee = FUTURES_FEE_BPS if mode == "futures" else 10.0
    return 2 * fee + 2 * SLIPPAGE_BPS


@dataclass
class Result:
    name: str
    symbol: str
    params: dict
    trades: list[Trade] = field(default_factory=list)

    def stats(self) -> dict:
        if not self.trades:
            return {"trades": 0}
        returns = [t.net_return_bps for t in self.trades]
        n = len(returns)
        wins = sum(1 for r in returns if r > 0)
        total = sum(returns)
        gross_p = sum(r for r in returns if r > 0)
        gross_l = abs(sum(r for r in returns if r < 0))
        pf = gross_p / gross_l if gross_l > 0 else (float("inf") if gross_p > 0 else 0)
        eq = np.cumsum(returns)
        peak = np.maximum.accumulate(eq)
        dd = eq - peak
        mdd = abs(np.min(dd)) if len(dd) else 0
        sharpe = np.mean(returns) / np.std(returns, ddof=1) if n > 1 and np.std(returns, ddof=1) > 0 else 0
        return {
            "trades": n, "win_rate": wins / n, "pf": pf,
            "total_bps": total, "avg_bps": np.mean(returns),
            "max_dd_bps": mdd, "sharpe": sharpe,
        }


# ── 전략: Enhanced MA Cross ──────────────────────────
def enhanced_ma_cross(data, *, fast, slow, hold_bars, adx_min=0.0,
                      vol_mult=0.0, atr_stop_mult=2.0, rsi_confirm=False,
                      rsi_long_max=70, rsi_short_min=30, mode="futures") -> list[Trade]:
    close = data["close"]
    h, l = data["high"], data["low"]
    ef = ema(close, fast)
    es = ema(close, slow)
    trades = []
    cost = round_trip_cost(mode)
    adx_v = adx(h, l, close) if adx_min > 0 else None
    vol_s = volume_sma(data["volume"], 20) if vol_mult > 0 else None
    atr_v = atr(h, l, close)
    rsi_v = rsi(close) if rsi_confirm else None

    i = max(slow + 1, 30)
    while i < len(close) - hold_bars:
        if np.isnan(ef[i]) or np.isnan(es[i]) or np.isnan(ef[i-1]) or np.isnan(es[i-1]):
            i += 1; continue
        if adx_min > 0 and adx_v is not None and (np.isnan(adx_v[i]) or adx_v[i] < adx_min):
            i += 1; continue
        if vol_mult > 0 and vol_s is not None and (np.isnan(vol_s[i]) or data["volume"][i] < vol_s[i] * vol_mult):
            i += 1; continue

        cross_up = ef[i-1] <= es[i-1] and ef[i] > es[i]
        cross_down = ef[i-1] >= es[i-1] and ef[i] < es[i]

        if not (cross_up or cross_down):
            i += 1; continue

        side = "long" if cross_up else "short"

        # RSI confirmation
        if rsi_confirm and rsi_v is not None and not np.isnan(rsi_v[i]):
            if side == "long" and rsi_v[i] > rsi_long_max:
                i += 1; continue  # RSI too high for long
            if side == "short" and rsi_v[i] < rsi_short_min:
                i += 1; continue  # RSI too low for short

        entry = close[i]
        exit_idx = min(i + hold_bars, len(close) - 1)

        # ATR trailing stop
        if not np.isnan(atr_v[i]):
            sd = atr_stop_mult * atr_v[i]
            ts = entry - sd if side == "long" else entry + sd
            for j in range(i+1, exit_idx+1):
                a = atr_v[min(j, len(atr_v)-1)]
                if np.isnan(a): a = atr_v[i]
                if side == "long":
                    ts = max(ts, close[j] - atr_stop_mult * a)
                    if l[j] <= ts: exit_idx = j; break
                else:
                    ts = min(ts, close[j] + atr_stop_mult * a)
                    if h[j] >= ts: exit_idx = j; break

        ep = close[exit_idx]
        rb = (ep - entry) / entry * 10000 if side == "long" else (entry - ep) / entry * 10000
        trades.append(Trade(i, exit_idx, side, entry, ep, rb, rb - cost, exit_idx - i))
        i = exit_idx + 1

    return trades


# ── 전략: Momentum with Trend Confirmation ──────────
def momentum_trend(data, *, lookback, hold_bars, adx_min=25.0,
                   vol_mult=1.2, atr_stop_mult=2.5, ema_trend_period=50,
                   mode="futures") -> list[Trade]:
    close = data["close"]
    h, l = data["high"], data["low"]
    trades = []
    cost = round_trip_cost(mode)
    adx_v = adx(h, l, close)
    vol_s = volume_sma(data["volume"], 20)
    atr_v = atr(h, l, close)
    ema_trend = ema(close, ema_trend_period)

    i = max(lookback + 1, ema_trend_period + 1)
    while i < len(close) - hold_bars:
        if np.isnan(adx_v[i]) or adx_v[i] < adx_min:
            i += 1; continue
        if np.isnan(vol_s[i]) or data["volume"][i] < vol_s[i] * vol_mult:
            i += 1; continue
        if np.isnan(ema_trend[i]):
            i += 1; continue

        highest = np.max(h[i-lookback:i])
        lowest = np.min(l[i-lookback:i])

        side = None
        if close[i] > highest and close[i] > ema_trend[i]:
            side = "long"
        elif close[i] < lowest and close[i] < ema_trend[i]:
            side = "short"

        if not side:
            i += 1; continue

        entry = close[i]
        exit_idx = min(i + hold_bars, len(close) - 1)

        if not np.isnan(atr_v[i]):
            sd = atr_stop_mult * atr_v[i]
            ts = entry - sd if side == "long" else entry + sd
            for j in range(i+1, exit_idx+1):
                a = atr_v[min(j, len(atr_v)-1)]
                if np.isnan(a): a = atr_v[i]
                if side == "long":
                    ts = max(ts, close[j] - atr_stop_mult * a)
                    if l[j] <= ts: exit_idx = j; break
                else:
                    ts = min(ts, close[j] + atr_stop_mult * a)
                    if h[j] >= ts: exit_idx = j; break

        ep = close[exit_idx]
        rb = (ep - entry) / entry * 10000 if side == "long" else (entry - ep) / entry * 10000
        trades.append(Trade(i, exit_idx, side, entry, ep, rb, rb - cost, exit_idx - i))
        i = exit_idx + 1

    return trades


# ── 전략: Multi-TF Enhanced ──────────────────────────
def mtf_enhanced(data_5m, data_1h, *, fast=9, slow=21, hold_bars_5m=48,
                 adx_1h_min=20.0, vol_mult_5m=0.0, atr_stop_mult=2.0,
                 rsi_confirm=False, ema_100_filter=False, mode="futures") -> list[Trade]:
    close_5m = data_5m["close"]
    time_5m = data_5m["time"]
    close_1h = data_1h["close"]
    time_1h = data_1h["time"]

    ema20_1h = ema(close_1h, 20)
    ema50_1h = ema(close_1h, 50)
    ema100_1h = ema(close_1h, 100) if ema_100_filter else None
    adx_1h = adx(data_1h["high"], data_1h["low"], close_1h)

    ef_5m = ema(close_5m, fast)
    es_5m = ema(close_5m, slow)
    vol_s_5m = volume_sma(data_5m["volume"], 20) if vol_mult_5m > 0 else None
    atr_5m = atr(data_5m["high"], data_5m["low"], close_5m)
    rsi_5m = rsi(close_5m) if rsi_confirm else None

    trades = []
    cost = round_trip_cost(mode)

    def get_1h_trend(ts):
        idx = np.searchsorted(time_1h, ts, side="right") - 1
        if idx < 100 or idx >= len(close_1h):
            return 0
        if np.isnan(ema20_1h[idx]) or np.isnan(ema50_1h[idx]) or np.isnan(adx_1h[idx]):
            return 0
        if adx_1h[idx] < adx_1h_min:
            return 0
        if ema_100_filter and ema100_1h is not None:
            if np.isnan(ema100_1h[idx]):
                return 0
            if ema20_1h[idx] > ema50_1h[idx] > ema100_1h[idx] and close_1h[idx] > ema20_1h[idx]:
                return 1
            elif ema20_1h[idx] < ema50_1h[idx] < ema100_1h[idx] and close_1h[idx] < ema20_1h[idx]:
                return -1
            return 0
        if ema20_1h[idx] > ema50_1h[idx] and close_1h[idx] > ema20_1h[idx]:
            return 1
        elif ema20_1h[idx] < ema50_1h[idx] and close_1h[idx] < ema20_1h[idx]:
            return -1
        return 0

    i = max(slow + 1, 60)
    while i < len(close_5m) - hold_bars_5m:
        if np.isnan(ef_5m[i]) or np.isnan(es_5m[i]):
            i += 1; continue
        if vol_mult_5m > 0 and vol_s_5m is not None and (np.isnan(vol_s_5m[i]) or data_5m["volume"][i] < vol_s_5m[i] * vol_mult_5m):
            i += 1; continue

        trend = get_1h_trend(time_5m[i])
        if trend == 0:
            i += 1; continue

        cross_up = ef_5m[i-1] <= es_5m[i-1] and ef_5m[i] > es_5m[i]
        cross_down = ef_5m[i-1] >= es_5m[i-1] and ef_5m[i] < es_5m[i]

        side = None
        if cross_up and trend == 1: side = "long"
        elif cross_down and trend == -1: side = "short"
        if not side:
            i += 1; continue

        # RSI confirm
        if rsi_confirm and rsi_5m is not None and not np.isnan(rsi_5m[i]):
            if side == "long" and rsi_5m[i] > 70:
                i += 1; continue
            if side == "short" and rsi_5m[i] < 30:
                i += 1; continue

        entry = close_5m[i]
        exit_idx = min(i + hold_bars_5m, len(close_5m) - 1)

        if not np.isnan(atr_5m[i]):
            sd = atr_stop_mult * atr_5m[i]
            ts = entry - sd if side == "long" else entry + sd
            for j in range(i+1, exit_idx+1):
                a = atr_5m[min(j, len(atr_5m)-1)]
                if np.isnan(a): a = atr_5m[i]
                if side == "long":
                    ts = max(ts, close_5m[j] - atr_stop_mult * a)
                    if data_5m["low"][j] <= ts: exit_idx = j; break
                else:
                    ts = min(ts, close_5m[j] + atr_stop_mult * a)
                    if data_5m["high"][j] >= ts: exit_idx = j; break

        ep = close_5m[exit_idx]
        rb = (ep - entry) / entry * 10000 if side == "long" else (entry - ep) / entry * 10000
        trades.append(Trade(i, exit_idx, side, entry, ep, rb, rb - cost, exit_idx - i))
        i = exit_idx + 1

    return trades


# ── Composite strategy: combine signals ──────────────
def composite_strategy(data_1h, *, mode="futures") -> list[Trade]:
    """
    Combined signal: MA cross + ADX + volume + RSI confirmation.
    Only enter when:
    1. EMA 9/21 cross on 1h
    2. ADX >= 22
    3. Volume >= 0.9x SMA(20)
    4. RSI not overbought/oversold against direction
    5. EMA 50 confirms direction
    """
    close = data_1h["close"]
    h, l = data_1h["high"], data_1h["low"]
    ef = ema(close, 9)
    es = ema(close, 21)
    e50 = ema(close, 50)
    adx_v = adx(h, l, close)
    vol_s = volume_sma(data_1h["volume"], 20)
    atr_v = atr(h, l, close)
    rsi_v = rsi(close)

    trades = []
    cost = round_trip_cost(mode)

    i = 52
    while i < len(close) - 24:
        if any(np.isnan(x[i]) for x in [ef, es, e50, adx_v, vol_s, atr_v, rsi_v]):
            i += 1; continue
        if np.isnan(ef[i-1]) or np.isnan(es[i-1]):
            i += 1; continue

        cross_up = ef[i-1] <= es[i-1] and ef[i] > es[i]
        cross_down = ef[i-1] >= es[i-1] and ef[i] < es[i]
        if not (cross_up or cross_down):
            i += 1; continue

        # ADX filter
        if adx_v[i] < 22:
            i += 1; continue

        # Volume
        if data_1h["volume"][i] < vol_s[i] * 0.9:
            i += 1; continue

        side = "long" if cross_up else "short"

        # EMA 50 trend confirmation
        if side == "long" and close[i] < e50[i]:
            i += 1; continue
        if side == "short" and close[i] > e50[i]:
            i += 1; continue

        # RSI guard
        if side == "long" and rsi_v[i] > 72:
            i += 1; continue
        if side == "short" and rsi_v[i] < 28:
            i += 1; continue

        entry = close[i]
        hold = 18  # 18h hold max
        exit_idx = min(i + hold, len(close) - 1)

        # ATR trailing stop (1.8x)
        sd = 1.8 * atr_v[i]
        ts = entry - sd if side == "long" else entry + sd
        for j in range(i+1, exit_idx+1):
            a = atr_v[min(j, len(atr_v)-1)]
            if np.isnan(a): a = atr_v[i]
            if side == "long":
                ts = max(ts, close[j] - 1.8 * a)
                if l[j] <= ts: exit_idx = j; break
            else:
                ts = min(ts, close[j] + 1.8 * a)
                if h[j] >= ts: exit_idx = j; break

        ep = close[exit_idx]
        rb = (ep - entry) / entry * 10000 if side == "long" else (entry - ep) / entry * 10000
        trades.append(Trade(i, exit_idx, side, entry, ep, rb, rb - cost, exit_idx - i))
        i = exit_idx + 1

    return trades


# ── 실행 ──────────────────────────────────────────────
def main():
    print("=" * 100)
    print("SIGNAL RESEARCH V2 — Deep Optimization")
    print("=" * 100)

    all_results: list[tuple[str, str, dict, dict]] = []  # (name, symbol, params, stats)

    for symbol in SYMBOLS:
        print(f"\n{'─' * 80}")
        print(f"  {symbol}")
        print(f"{'─' * 80}")

        d1h = candles_to_arrays(load_candles(symbol, "1h"))
        d5m = candles_to_arrays(load_candles(symbol, "5m"))
        if not d1h:
            continue

        # ── 1. Enhanced MA Cross — 정밀 탐색 ──────────
        for fast, slow in [(8, 21), (9, 21), (10, 21), (9, 26), (12, 26)]:
            for hold in [10, 12, 15, 18, 24]:
                for adx_min in [20, 22, 25, 28]:
                    for vol_m in [0.0, 0.8, 1.0]:
                        for atr_m in [1.5, 1.8, 2.0, 2.5]:
                            for rsi_c in [False, True]:
                                p = {"fast": fast, "slow": slow, "hold_bars": hold,
                                     "adx_min": adx_min, "vol_mult": vol_m,
                                     "atr_stop_mult": atr_m, "rsi_confirm": rsi_c}
                                trades = enhanced_ma_cross(d1h, **p)
                                r = Result("EMA_Cross", symbol, p, trades)
                                s = r.stats()
                                if s["trades"] >= 5:
                                    all_results.append(("EMA_Cross", symbol, p, s))

        # ── 2. Momentum Trend ──────────────────────────
        for lookback in [15, 20, 25, 30]:
            for hold in [18, 24, 36, 48]:
                for adx_min in [20, 25, 30]:
                    for vol_m in [1.0, 1.2, 1.5]:
                        for atr_m in [2.0, 2.5, 3.0]:
                            p = {"lookback": lookback, "hold_bars": hold,
                                 "adx_min": adx_min, "vol_mult": vol_m,
                                 "atr_stop_mult": atr_m}
                            trades = momentum_trend(d1h, **p)
                            r = Result("Momentum", symbol, p, trades)
                            s = r.stats()
                            if s["trades"] >= 5:
                                all_results.append(("Momentum", symbol, p, s))

        # ── 3. MTF Enhanced ──────────────────────────
        if d5m:
            for fast, slow in [(5, 13), (9, 21)]:
                for hold in [36, 48, 72, 96]:
                    for adx_1h in [18, 20, 22, 25]:
                        for atr_m in [1.5, 2.0, 2.5]:
                            for rsi_c in [False, True]:
                                for ema100 in [False, True]:
                                    p = {"fast": fast, "slow": slow, "hold_bars_5m": hold,
                                         "adx_1h_min": adx_1h, "atr_stop_mult": atr_m,
                                         "rsi_confirm": rsi_c, "ema_100_filter": ema100}
                                    trades = mtf_enhanced(d5m, d1h, **p)
                                    r = Result("MTF", symbol, p, trades)
                                    s = r.stats()
                                    if s["trades"] >= 5:
                                        all_results.append(("MTF", symbol, p, s))

        # ── 4. Composite ──────────────────────────────
        trades = composite_strategy(d1h)
        r = Result("Composite", symbol, {}, trades)
        s = r.stats()
        if s["trades"] >= 3:
            all_results.append(("Composite", symbol, {}, s))

    # ── 결과 정렬 & 출력 ──────────────────────────
    print(f"\n\n{'=' * 100}")
    print("  RESULTS")
    print(f"{'=' * 100}")

    # Sort by profit factor
    all_results.sort(key=lambda x: x[3].get("pf", 0) if x[3].get("pf", 0) < 100 else 99, reverse=True)

    profitable = [(n, sy, p, s) for n, sy, p, s in all_results if s.get("pf", 0) > 1.0 and s["trades"] >= 5]
    total = len(all_results)

    print(f"\n총 조합: {total}")
    print(f"수익 (PF>1.0, n>=5): {len(profitable)}")
    print(f"비율: {len(profitable)/total*100:.1f}%" if total else "N/A")

    # Top 30
    print(f"\n{'─' * 100}")
    print(f"  TOP 30 STRATEGIES")
    print(f"{'─' * 100}")
    print(f"{'Strategy':<12} {'Symbol':<10} {'N':>4} {'WinR':>6} {'PF':>6} {'TotBps':>8} {'AvgBps':>7} {'MaxDD':>8} {'Sharpe':>7}  Key Params")
    print(f"{'─' * 100}")

    for name, sym, params, stats in profitable[:30]:
        pf = stats["pf"]
        pf_s = f"{pf:.2f}" if pf < 100 else "inf"
        key_params = []
        for k in ["fast", "slow", "hold_bars", "adx_min", "vol_mult", "atr_stop_mult", "rsi_confirm",
                   "lookback", "hold_bars_5m", "adx_1h_min", "ema_100_filter"]:
            if k in params:
                v = params[k]
                if isinstance(v, bool):
                    if v: key_params.append(k)
                elif isinstance(v, float) and v == 0.0:
                    continue
                else:
                    key_params.append(f"{k}={v}")
        print(f"{name:<12} {sym:<10} {stats['trades']:>4} {stats['win_rate']:>5.1%} {pf_s:>6} {stats['total_bps']:>8.1f} {stats['avg_bps']:>7.1f} {stats['max_dd_bps']:>8.1f} {stats['sharpe']:>7.3f}  {', '.join(key_params)}")

    # ── Cross-symbol consistency ──────────────────
    print(f"\n\n{'=' * 100}")
    print("  CROSS-SYMBOL CONSISTENCY (strategies that work on 3+ symbols)")
    print(f"{'=' * 100}")

    # Group by (strategy, key params)
    from collections import defaultdict
    param_groups = defaultdict(list)
    for name, sym, params, stats in profitable:
        # Create a hashable key from core params
        key_parts = [name]
        for k in sorted(params.keys()):
            key_parts.append(f"{k}={params[k]}")
        key = tuple(key_parts)
        param_groups[key].append((sym, stats))

    multi_symbol = [(k, v) for k, v in param_groups.items() if len(v) >= 3]
    multi_symbol.sort(key=lambda x: np.mean([s["pf"] for _, s in x[1] if s["pf"] < 100]), reverse=True)

    if multi_symbol:
        for key, sym_stats in multi_symbol[:15]:
            avg_pf = np.mean([s["pf"] for _, s in sym_stats if s["pf"] < 100])
            avg_wr = np.mean([s["win_rate"] for _, s in sym_stats])
            avg_sharpe = np.mean([s["sharpe"] for _, s in sym_stats])
            total_trades = sum(s["trades"] for _, s in sym_stats)
            syms = ", ".join(sy for sy, _ in sym_stats)
            params_str = ", ".join(key[1:])
            print(f"\n  Avg PF={avg_pf:.2f}  WR={avg_wr:.1%}  Sharpe={avg_sharpe:.3f}  Total trades={total_trades}")
            print(f"  Symbols: {syms}")
            print(f"  Params: {params_str}")
            for sy, s in sym_stats:
                pf_s = f"{s['pf']:.2f}" if s['pf'] < 100 else "inf"
                print(f"    {sy}: n={s['trades']} WR={s['win_rate']:.1%} PF={pf_s} Total={s['total_bps']:.0f}bps Sharpe={s['sharpe']:.3f}")
    else:
        print("  None found. Showing best 2-symbol combos:")
        two_sym = [(k, v) for k, v in param_groups.items() if len(v) >= 2]
        two_sym.sort(key=lambda x: np.mean([s["pf"] for _, s in x[1] if s["pf"] < 100]), reverse=True)
        for key, sym_stats in two_sym[:10]:
            avg_pf = np.mean([s["pf"] for _, s in sym_stats if s["pf"] < 100])
            syms = ", ".join(sy for sy, _ in sym_stats)
            print(f"  PF={avg_pf:.2f} [{syms}] {', '.join(key[1:5])}")

    # ── Save results ──────────────────────────────
    output_dir = Path(__file__).resolve().parent.parent / "quant_runtime" / "output" / "signal_research"
    output_dir.mkdir(parents=True, exist_ok=True)

    top_results = []
    for name, sym, params, stats in profitable[:50]:
        top_results.append({
            "strategy": name, "symbol": sym,
            "params": {k: v for k, v in params.items()},
            **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in stats.items()},
        })
    with open(output_dir / "v2_top_results.json", "w") as f:
        json.dump(top_results, f, indent=2, default=str)

    # Save cross-symbol consistent params
    consistent = []
    for key, sym_stats in (multi_symbol or two_sym[:5]):
        consistent.append({
            "params_key": list(key),
            "symbols": [{sy: {k: round(v, 4) if isinstance(v, float) else v for k, v in s.items()}} for sy, s in sym_stats],
            "avg_pf": round(np.mean([s["pf"] for _, s in sym_stats if s["pf"] < 100]), 4),
            "avg_sharpe": round(np.mean([s["sharpe"] for _, s in sym_stats]), 4),
        })
    with open(output_dir / "v2_consistent_params.json", "w") as f:
        json.dump(consistent, f, indent=2, default=str)

    print(f"\n결과 저장: {output_dir}")


if __name__ == "__main__":
    main()
