#!/usr/bin/env python3
"""auto4h: 확장 신호 라이브러리 (12 신호).

각 신호는 (ind, i) → bool. ind는 compute_indicators + add_extra_features + add_obv 통과한 dict.
"""
from __future__ import annotations
import numpy as np


# === 기존 3 신호 (Phase 27 winner) ===
def vol_expansion(ind, i):
    if i < 30: return False
    return (ind["bb_width_rank"][i] >= 0.7 and ind["mom24"][i] > 0.03
            and ind["close"][i] > ind["bb_upper"][i] and ind["vol_r"][i] >= 1.5)


def momentum_obv(ind, i):
    if i < 25: return False
    return (ind["mom24"][i] > 0.05 and ind["ema20"][i] > ind["ema50"][i]
            and ind["adx"][i] > 22 and ind["vol_r"][i] >= 1.3 and ind["obv_slope"][i] > 0)


def squeeze_release(ind, i):
    if i < 22 or i < 5: return False
    if not all(ind["bb_width_rank"][k] < 0.30 for k in range(i-5, i)): return False
    return ind["close"][i] > ind["bb_upper"][i-1] and ind["vol_r"][i] > 1.3


# === 새 신호 9개 ===
def donchian_breakout_20(ind, i):
    """20-bar Donchian high breakout + volume confirm."""
    if i < 21: return False
    high20 = ind["high"][i-20:i]  # exclude current
    return (ind["close"][i] > np.max(high20) and ind["vol_r"][i] >= 1.5
            and ind["mom24"][i] > 0.02)


def atr_expansion(ind, i):
    """ATR 확장 + 추세 상방. ATR(14)이 ATR(50) MA보다 위 + close>EMA50 + 양봉."""
    if i < 50: return False
    # use bb_width as volatility proxy (same period)
    bb_w = ind["bb_width"]
    s = max(0, i - 49)
    bb_w_ma = np.mean(bb_w[s:i+1])
    return (bb_w[i] > bb_w_ma * 1.2 and ind["close"][i] > ind["ema50"][i]
            and ind["close"][i] > ind["close"][i-1] and ind["vol_r"][i] >= 1.3)


def ema_cross_long(ind, i):
    """EMA20 cross above EMA50 + volume."""
    if i < 51: return False
    cross = (ind["ema20"][i] > ind["ema50"][i]) and (ind["ema20"][i-1] <= ind["ema50"][i-1])
    return cross and ind["vol_r"][i] >= 1.5 and ind["mom24"][i] > 0.0


def pump_detect(ind, i):
    """1h price 급등 + 거래량 폭발 (메메즈 펌프)."""
    if i < 2: return False
    pct_1h = ind["close"][i] / ind["close"][i-1] - 1
    return pct_1h > 0.04 and ind["vol_r"][i] > 3.0


def rsi_breakout(ind, i):
    """RSI > 60 + close > BB middle + ADX strong (proxy via mom24)."""
    if i < 14: return False
    # rsi proxy: 14-bar gain ratio
    gains = 0; losses = 0
    for k in range(i-13, i+1):
        d = ind["close"][k] - ind["close"][k-1] if k > 0 else 0
        if d > 0: gains += d
        else: losses += -d
    rsi = 100 if losses == 0 else 100 - (100 / (1 + gains/losses))
    bb_mid = (ind["bb_upper"][i] + ind["bb_lower"][i]) / 2
    return rsi > 60 and ind["close"][i] > bb_mid and ind["adx"][i] > 25 and ind["vol_r"][i] > 1.2


def heikin_continuation(ind, i):
    """3 consecutive bullish closes + volume + price above EMA20."""
    if i < 3: return False
    bullish = all(ind["close"][k] > ind["close"][k-1] for k in range(i-2, i+1))
    return bullish and ind["close"][i] > ind["ema20"][i] and ind["vol_r"][i] > 1.4


def fractal_breakout(ind, i):
    """5-bar fractal high break."""
    if i < 6: return False
    # find the highest of the last 5 bars (excluding current)
    fractal_high = max(ind["high"][i-5:i])
    return (ind["close"][i] > fractal_high and ind["vol_r"][i] > 1.4
            and ind["ema20"][i] > ind["ema50"][i])


def adx_trend(ind, i):
    """ADX > 30 + EMA cross alignment + vol confirm. 강추세."""
    if i < 50: return False
    return (ind["adx"][i] > 30 and ind["ema20"][i] > ind["ema50"][i]
            and ind["close"][i] > ind["ema20"][i] and ind["vol_r"][i] >= 1.2
            and ind["mom24"][i] > 0.03)


def trend_pullback(ind, i):
    """추세 중 EMA20 retest + 반등 (mean reversion in trend)."""
    if i < 51: return False
    if ind["ema20"][i] <= ind["ema50"][i]: return False  # not in uptrend
    # recent 3 bars touched EMA20 (low <= ema20)
    touched = any(ind["low"][k] <= ind["ema20"][k] * 1.005 for k in range(i-3, i))
    bouncing = ind["close"][i] > ind["ema20"][i] and ind["close"][i] > ind["close"][i-1]
    return touched and bouncing and ind["vol_r"][i] > 1.3 and ind["mom24"][i] > 0.0


# === 모든 신호 dict ===
SIGNALS = {
    "vol_expansion": vol_expansion,
    "momentum_obv": momentum_obv,
    "squeeze_release": squeeze_release,
    "donchian_20": donchian_breakout_20,
    "atr_expansion": atr_expansion,
    "ema_cross": ema_cross_long,
    "pump_detect": pump_detect,
    "rsi_breakout": rsi_breakout,
    "heikin_cont": heikin_continuation,
    "fractal_break": fractal_breakout,
    "adx_trend": adx_trend,
    "trend_pullback": trend_pullback,
}
