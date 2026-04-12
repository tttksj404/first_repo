"""Tests for alpha sub-strategies that generate new entry opportunities."""

from __future__ import annotations

import pytest
from quant_binance.models import FeatureVector
from quant_binance.strategy.alpha_strategies import (
    vwap_mean_reversion,
    smc_fvg_fill,
    oi_momentum_surge,
    scan_alpha_signals,
    best_alpha_signal,
    AlphaSignalType,
)


def _base(**overrides) -> FeatureVector:
    defaults = dict(
        ret_rank_1h=50.0, ret_rank_4h=50.0, breakout_norm=0.3,
        ema_stack_score=0.5, vol_z_5m_norm=0.5, vol_z_1h_norm=0.5,
        taker_imbalance_norm=0.5, spread_bps_norm=0.3,
        probe_slippage_bps_norm=0.3, depth_10bps_norm=0.6,
        book_stability_norm=0.7, realized_vol_1h_norm=0.4,
        realized_vol_4h_norm=0.35, vol_shock_norm=0.3,
        funding_abs_percentile=0.15, oi_surge_percentile=0.1,
        basis_stretch_percentile=0.18, regime_alignment=0.5,
        trend_direction=0, trend_strength=0.3,
        volume_confirmation=0.5, liquidity_score=0.7,
        volatility_penalty=0.25, overheat_penalty=0.15,
        adx_1h=12.0, atr_14_1h_bps=50.0,
        oi_divergence_score=0.0, vwap_price=100.0,
        vwap_deviation_z=0.0, smc_fvg_score=0.0,
        smc_ob_score=0.0, smc_structure_score=0.0,
        smc_composite_score=0.0,
    )
    defaults.update(overrides)
    return FeatureVector(**defaults)


class TestVWAPMeanReversion:
    def test_no_signal_in_trending_market(self):
        f = _base(adx_1h=25.0, vwap_deviation_z=2.5)
        assert vwap_mean_reversion(f) is None

    def test_no_signal_small_deviation(self):
        f = _base(adx_1h=12.0, vwap_deviation_z=1.0)
        assert vwap_mean_reversion(f) is None

    def test_short_on_high_vwap_deviation(self):
        f = _base(adx_1h=12.0, vwap_deviation_z=2.5, liquidity_score=0.7)
        sig = vwap_mean_reversion(f)
        assert sig is not None
        assert sig.side == "short"
        assert sig.signal_type == AlphaSignalType.VWAP_MEAN_REVERT
        assert sig.leverage_cap <= 4

    def test_long_on_low_vwap_deviation(self):
        f = _base(adx_1h=12.0, vwap_deviation_z=-2.5, liquidity_score=0.7)
        sig = vwap_mean_reversion(f)
        assert sig is not None
        assert sig.side == "long"

    def test_no_signal_if_oi_surging(self):
        f = _base(adx_1h=12.0, vwap_deviation_z=2.5, oi_divergence_score=0.6)
        assert vwap_mean_reversion(f) is None

    def test_no_signal_low_liquidity(self):
        f = _base(adx_1h=12.0, vwap_deviation_z=2.5, liquidity_score=0.3)
        assert vwap_mean_reversion(f) is None


class TestSMCFVGFill:
    def test_no_signal_without_fvg(self):
        f = _base(smc_fvg_score=0.0, smc_structure_score=0.5, trend_direction=1)
        assert smc_fvg_fill(f) is None

    def test_signal_with_fvg_and_structure(self):
        f = _base(
            smc_fvg_score=0.6, smc_structure_score=0.5,
            smc_composite_score=0.5, trend_direction=1,
            volume_confirmation=0.6,
        )
        sig = smc_fvg_fill(f)
        assert sig is not None
        assert sig.side == "long"
        assert sig.signal_type == AlphaSignalType.SMC_FVG_FILL
        assert sig.target_bps > sig.stop_bps  # RR > 1

    def test_short_signal_in_downtrend(self):
        f = _base(
            smc_fvg_score=0.5, smc_structure_score=0.4,
            smc_composite_score=0.4, trend_direction=-1,
            volume_confirmation=0.6,
        )
        sig = smc_fvg_fill(f)
        assert sig is not None
        assert sig.side == "short"

    def test_uses_intraday_when_no_trend(self):
        f = _base(
            smc_fvg_score=0.5, smc_structure_score=0.4,
            smc_composite_score=0.4, trend_direction=0,
            intraday_trend_direction=1, volume_confirmation=0.6,
        )
        sig = smc_fvg_fill(f)
        assert sig is not None
        assert sig.side == "long"


class TestOIMomentumSurge:
    def test_no_signal_without_oi_surge(self):
        f = _base(oi_divergence_score=0.2, trend_direction=1, taker_imbalance_norm=0.6)
        assert oi_momentum_surge(f) is None

    def test_long_signal_on_surge(self):
        f = _base(
            oi_divergence_score=0.7, trend_direction=1,
            taker_imbalance_norm=0.65, volume_confirmation=0.7,
        )
        sig = oi_momentum_surge(f)
        assert sig is not None
        assert sig.side == "long"
        assert sig.signal_type == AlphaSignalType.OI_MOMENTUM_SURGE
        assert sig.leverage_cap >= 6

    def test_no_signal_taker_mismatch(self):
        f = _base(
            oi_divergence_score=0.7, trend_direction=1,
            taker_imbalance_norm=0.4,  # taker selling, not buying
        )
        assert oi_momentum_surge(f) is None

    def test_no_signal_in_overheat(self):
        f = _base(
            oi_divergence_score=0.7, trend_direction=1,
            taker_imbalance_norm=0.65, overheat_penalty=0.7,
        )
        assert oi_momentum_surge(f) is None


class TestAlphaScanner:
    def test_no_signals_in_normal_market(self):
        f = _base()
        signals = scan_alpha_signals(f)
        assert len(signals) == 0

    def test_multiple_signals_sorted_by_confidence(self):
        f = _base(
            adx_1h=12.0, vwap_deviation_z=-2.5,
            smc_fvg_score=0.5, smc_structure_score=0.4,
            smc_composite_score=0.45, trend_direction=0,
            intraday_trend_direction=1, volume_confirmation=0.6,
            liquidity_score=0.7,
        )
        signals = scan_alpha_signals(f)
        assert len(signals) >= 1
        if len(signals) >= 2:
            assert signals[0].confidence >= signals[1].confidence

    def test_best_alpha_returns_highest(self):
        f = _base(
            oi_divergence_score=0.7, trend_direction=1,
            taker_imbalance_norm=0.65, volume_confirmation=0.7,
        )
        sig = best_alpha_signal(f)
        assert sig is not None
        assert sig.signal_type == AlphaSignalType.OI_MOMENTUM_SURGE

    def test_best_alpha_none_when_quiet(self):
        f = _base()
        assert best_alpha_signal(f) is None
