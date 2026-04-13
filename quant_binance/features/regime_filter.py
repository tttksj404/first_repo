"""Regime detection via Hurst exponent + HAR-RV volatility forecast.

References:
- Hurst 1951, Peters 1991 — R/S analysis
- Di Matteo 2007 — multi-scale Hurst for market inefficiency
- Corsi 2009 — HAR-RV model
- Bollerslev et al 2016 — HAR-RV with jump component
- Bariviera 2017 — Hurst in cryptocurrency markets
- Catania & Sandholdt 2019 — HAR-RV in crypto
"""
from __future__ import annotations

import math
from typing import Sequence


def hurst_rs(prices: Sequence[float], min_lag: int = 10, max_lag: int = 100) -> float:
    """R/S (Rescaled Range) analysis estimator for Hurst exponent.

    H > 0.5 → trending (persistent)
    H ≈ 0.5 → random walk (efficient)
    H < 0.5 → mean-reverting (anti-persistent)

    Returns H in [0, 1]. Returns 0.5 if data insufficient.
    """
    n = len(prices)
    if n < max_lag + 10:
        return 0.5

    lags = []
    rs_values = []

    for lag in range(min_lag, min(max_lag, n // 2), max(1, (max_lag - min_lag) // 20)):
        rs_chunk = []
        for start in range(0, n - lag, lag):
            segment = list(prices[start:start + lag])
            if len(segment) < lag:
                continue
            mean = sum(segment) / lag
            deviations = [p - mean for p in segment]
            cum_dev = []
            acc = 0.0
            for d in deviations:
                acc += d
                cum_dev.append(acc)
            R = max(cum_dev) - min(cum_dev)
            mean_sq = sum(d * d for d in deviations) / lag
            S = math.sqrt(mean_sq)
            if S > 0:
                rs_chunk.append(R / S)
        if rs_chunk:
            lags.append(lag)
            rs_values.append(sum(rs_chunk) / len(rs_chunk))

    if len(lags) < 4:
        return 0.5

    # Linear fit in log-log space
    log_lags = [math.log(l) for l in lags]
    log_rs = [math.log(r) if r > 0 else 0 for r in rs_values]
    n_pts = len(log_lags)
    mean_x = sum(log_lags) / n_pts
    mean_y = sum(log_rs) / n_pts
    num = sum((log_lags[i] - mean_x) * (log_rs[i] - mean_y) for i in range(n_pts))
    den = sum((log_lags[i] - mean_x) ** 2 for i in range(n_pts))
    if den == 0:
        return 0.5
    hurst = num / den
    return max(0.0, min(1.0, hurst))


def realized_variance(returns: Sequence[float]) -> float:
    """Sum of squared returns."""
    return sum(r * r for r in returns)


def har_rv_forecast(
    returns_5m: Sequence[float],
    weights: tuple[float, float, float] = (0.35, 0.35, 0.30),
) -> tuple[float, float, float, float]:
    """HAR-RV model: forecast next-period realized variance.

    Corsi (2009): RV_t+1 = β_0 + β_d·RV_d + β_w·RV_w + β_m·RV_m + ε

    Uses simplified equal-ish weights if no historical fit available.

    Args:
        returns_5m: 5m log returns
        weights: (daily, weekly, monthly) weights

    Returns:
        (forecast, rv_daily, rv_weekly, rv_monthly) all as bps²
    """
    n = len(returns_5m)
    if n < 2016:  # need at least 1 week
        return 0.0, 0.0, 0.0, 0.0

    # Convert to bps for interpretability
    r_bps = [r * 10000 for r in returns_5m]

    rv_d = realized_variance(r_bps[-288:])  # last 1 day (288 * 5m = 1440min)
    rv_w = realized_variance(r_bps[-2016:])  # last 7 days
    rv_m_samples = r_bps[-8640:] if n >= 8640 else r_bps
    rv_m = realized_variance(rv_m_samples) * (8640 / len(rv_m_samples)) if rv_m_samples else rv_w

    # Forecast = weighted combo (scaled to per-bar units)
    w_d, w_w, w_m = weights
    forecast = w_d * (rv_d / 288) + w_w * (rv_w / 2016) + w_m * (rv_m / 8640)

    return forecast, rv_d, rv_w, rv_m


def classify_regime(
    hurst: float,
    trending_threshold: float = 0.55,
    reverting_threshold: float = 0.45,
) -> str:
    """Classify market regime from Hurst exponent.

    Returns:
        "trending" — Hurst > trending_threshold
        "reverting" — Hurst < reverting_threshold
        "random" — between thresholds (no entry recommended)
    """
    if hurst > trending_threshold:
        return "trending"
    if hurst < reverting_threshold:
        return "reverting"
    return "random"


def vol_regime(
    rv_forecast: float,
    historical_rv_median: float,
) -> str:
    """Classify volatility regime from HAR-RV forecast vs historical median.

    Returns:
        "high" — forecast > 1.5× median (expansion, good for reversal)
        "low" — forecast < 0.5× median (compression, wait)
        "normal" — in between
    """
    if historical_rv_median <= 0:
        return "normal"
    ratio = rv_forecast / historical_rv_median
    if ratio > 1.5:
        return "high"
    if ratio < 0.5:
        return "low"
    return "normal"


def entry_allowed(
    hurst: float,
    vol_regime_value: str,
    strategy_type: str,
) -> bool:
    """Combined regime filter: decide if entry should proceed.

    Args:
        hurst: Hurst exponent (0-1)
        vol_regime_value: "high", "normal", "low" from vol_regime()
        strategy_type: "reversal" or "trend"

    Returns:
        True if regime supports this strategy type
    """
    price_regime = classify_regime(hurst)

    # Reversal needs mean-reverting market + high volatility
    if strategy_type == "reversal":
        return price_regime == "reverting" and vol_regime_value in ("high", "normal")

    # Trend-following needs trending market + high/normal volatility
    if strategy_type == "trend":
        return price_regime == "trending" and vol_regime_value in ("high", "normal")

    return False
