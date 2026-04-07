"""Coin-specific strategy profiles from $100 micro-capital optimization.

374-day validated (2025-03 ~ 2026-04):
- Walk-forward 67/33 split
- Monte Carlo 10K sims, ruin < 3%
- Stress test: cost 2x, PF > 1.0
- Leverage: MC파산 < 3% at optimal leverage, $100 start
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CoinProfile:
    ema_fast: int
    ema_slow: int
    adx_floor: float
    sl_atr_mult: float
    rr: float
    hold_bars: int          # max holding period in 1h bars
    side_filter: str        # "both" | "long"
    optimal_leverage: int   # MC-validated max leverage ($100, ruin < 3%)
    wr: float               # historical win rate
    pf: float               # historical profit factor
    # Pullback strategy (optional — 0 = disabled)
    pullback_ema: int = 0
    pullback_adx_floor: float = 0
    pullback_sl_mult: float = 0
    pullback_rr: float = 0
    # Short-specific EMA params (optional — 0 = use main params)
    short_ema_fast: int = 0
    short_ema_slow: int = 0
    short_adx_floor: float = 0
    short_sl_mult: float = 0
    short_rr: float = 0
    short_hold_bars: int = 0
    # Mirror strategy (optional — 0 = disabled)
    mirror_rsi_ob: float = 0
    mirror_rsi_os: float = 0
    mirror_adx_max: float = 0
    mirror_sl_mult: float = 0
    mirror_rr: float = 0
    mirror_hold_bars: int = 0


# 374d grid search → $100 MC leverage validation
# Sorted by optimal_leverage × median return
COIN_PROFILES: dict[str, CoinProfile] = {
    "BTCUSDT": CoinProfile(
        ema_fast=10, ema_slow=21, adx_floor=33, sl_atr_mult=1.0, rr=0.5,
        hold_bars=6, side_filter="long", optimal_leverage=20,
        wr=0.89, pf=4.58,
        pullback_ema=21, pullback_adx_floor=20, pullback_sl_mult=2.0, pullback_rr=1.0,
    ),
    "XRPUSDT": CoinProfile(
        ema_fast=9, ema_slow=21, adx_floor=40, sl_atr_mult=3.0, rr=0.75,
        hold_bars=36, side_filter="both", optimal_leverage=7,
        wr=0.88, pf=4.19,
    ),
    "ADAUSDT": CoinProfile(
        ema_fast=12, ema_slow=26, adx_floor=30, sl_atr_mult=1.0, rr=1.0,
        hold_bars=12, side_filter="long", optimal_leverage=20,
        wr=0.79, pf=4.85,
    ),
    "MATICUSDT": CoinProfile(
        ema_fast=8, ema_slow=21, adx_floor=33, sl_atr_mult=1.0, rr=1.2,
        hold_bars=36, side_filter="long", optimal_leverage=15,
        wr=0.76, pf=4.04,
    ),
    "BNBUSDT": CoinProfile(
        ema_fast=5, ema_slow=13, adx_floor=38, sl_atr_mult=2.5, rr=0.5,
        hold_bars=72, side_filter="both", optimal_leverage=15,
        wr=0.86, pf=4.31,
        short_ema_fast=10, short_ema_slow=21, short_adx_floor=30, short_sl_mult=4.0, short_rr=0.75, short_hold_bars=24,
    ),
    "DOGEUSDT": CoinProfile(
        ema_fast=9, ema_slow=21, adx_floor=38, sl_atr_mult=1.0, rr=1.5,
        hold_bars=6, side_filter="both", optimal_leverage=15,
        wr=0.71, pf=3.70,
    ),
    "ETHUSDT": CoinProfile(
        ema_fast=8, ema_slow=21, adx_floor=33, sl_atr_mult=3.0, rr=1.0,
        hold_bars=24, side_filter="both", optimal_leverage=10,
        wr=0.83, pf=4.13,
        pullback_ema=21, pullback_adx_floor=20, pullback_sl_mult=1.5, pullback_rr=1.0,
        short_ema_fast=10, short_ema_slow=21, short_adx_floor=25, short_sl_mult=4.0, short_rr=0.5, short_hold_bars=36,
    ),
    "LTCUSDT": CoinProfile(
        ema_fast=5, ema_slow=13, adx_floor=38, sl_atr_mult=3.0, rr=1.2,
        hold_bars=12, side_filter="long", optimal_leverage=10,
        wr=0.74, pf=3.91,
    ),
    "SOLUSDT": CoinProfile(
        ema_fast=20, ema_slow=50, adx_floor=30, sl_atr_mult=4.0, rr=0.5,
        hold_bars=48, side_filter="both", optimal_leverage=15,
        wr=0.89, pf=6.37,
        short_ema_fast=20, short_ema_slow=50, short_adx_floor=28, short_sl_mult=2.0, short_rr=1.0, short_hold_bars=48,
        mirror_rsi_ob=75, mirror_rsi_os=20, mirror_adx_max=30, mirror_sl_mult=3.0, mirror_rr=0.75, mirror_hold_bars=36,
    ),
    "PEPEUSDT": CoinProfile(
        ema_fast=20, ema_slow=50, adx_floor=28, sl_atr_mult=1.5, rr=1.2,
        hold_bars=48, side_filter="both", optimal_leverage=7,
        wr=0.79, pf=4.14,
        pullback_ema=21, pullback_adx_floor=25, pullback_sl_mult=1.0, pullback_rr=1.5,  # WR 70% PF 3.72
    ),
    "LINKUSDT": CoinProfile(
        ema_fast=8, ema_slow=21, adx_floor=35, sl_atr_mult=2.5, rr=1.5,
        hold_bars=18, side_filter="long", optimal_leverage=5,
        wr=0.79, pf=3.09,
        pullback_ema=21, pullback_adx_floor=25, pullback_sl_mult=1.5, pullback_rr=1.5,  # WR 70% PF 5.44
    ),
}

# Default for unknown symbols (conservative)
DEFAULT_PROFILE = CoinProfile(
    ema_fast=9, ema_slow=21, adx_floor=30, sl_atr_mult=2.0, rr=1.5,
    hold_bars=24, side_filter="both", optimal_leverage=3,
    wr=0.0, pf=0.0,
)


def get_profile(symbol: str) -> CoinProfile:
    return COIN_PROFILES.get(symbol, DEFAULT_PROFILE)


def is_profiled(symbol: str) -> bool:
    return symbol in COIN_PROFILES
