"""Tests for OI-VWAP-SMC integrated strategy."""

from __future__ import annotations

import pytest
from quant_binance.models import FeatureVector
from quant_binance.strategy.oi_vwap_smc_strategy import (
    evaluate_entry,
    should_block_entry,
    OIVWAPSMCResult,
)


def _base_features(**overrides) -> FeatureVector:
    defaults = dict(
        ret_rank_1h=55.0,
        ret_rank_4h=52.0,
        breakout_norm=0.5,
        ema_stack_score=0.8,
        vol_z_5m_norm=0.5,
        vol_z_1h_norm=0.5,
        taker_imbalance_norm=0.55,
        spread_bps_norm=0.3,
        probe_slippage_bps_norm=0.3,
        depth_10bps_norm=0.6,
        book_stability_norm=0.7,
        realized_vol_1h_norm=0.4,
        realized_vol_4h_norm=0.35,
        vol_shock_norm=0.3,
        funding_abs_percentile=0.15,
        oi_surge_percentile=0.1,
        basis_stretch_percentile=0.18,
        regime_alignment=1.0,
        trend_direction=1,
        trend_strength=0.75,
        volume_confirmation=0.7,
        liquidity_score=0.8,
        volatility_penalty=0.25,
        overheat_penalty=0.15,
        adx_1h=28.0,
        oi_divergence_score=0.0,
        vwap_deviation_z=0.0,
        smc_composite_score=0.0,
    )
    defaults.update(overrides)
    return FeatureVector(**defaults)


class TestOIVWAPSMCEntry:
    def test_default_features_allow_entry(self):
        features = _base_features()
        result = evaluate_entry(features, "BTCUSDT")
        assert result.entry_ok is True

    def test_fake_breakout_blocks_entry(self):
        features = _base_features(oi_divergence_score=-0.7)
        result = evaluate_entry(features, "BTCUSDT")
        assert result.entry_ok is False
        assert "OI_FAKE_BREAKOUT" in result.reasons
        assert result.signal_quality == "reject"

    def test_oi_soft_warn_reduces_size(self):
        features = _base_features(oi_divergence_score=-0.4)
        result = evaluate_entry(features, "BTCUSDT")
        assert result.entry_ok is True
        assert result.size_multiplier < 1.0
        assert "OI_DIVERGENCE_WARN" in result.reasons

    def test_weak_smc_reduces_size(self):
        features = _base_features(smc_composite_score=0.1)
        result = evaluate_entry(features, "BTCUSDT")
        assert result.entry_ok is True
        assert result.size_multiplier < 1.0
        assert "SMC_WEAK_STRUCTURE" in result.reasons

    def test_strong_smc_boosts(self):
        features = _base_features(smc_composite_score=0.7)
        result = evaluate_entry(features, "BTCUSDT")
        assert result.entry_ok is True
        assert "SMC_STRONG_STRUCTURE" in result.boost_reasons

    def test_vwap_extreme_ranging_reduces_size(self):
        features = _base_features(adx_1h=12.0, vwap_deviation_z=3.0)
        result = evaluate_entry(features, "BTCUSDT")
        assert result.entry_ok is True
        assert result.size_multiplier < 1.0
        assert "VWAP_EXTREME_RANGING" in result.reasons

    def test_vwap_pullback_in_uptrend(self):
        features = _base_features(
            trend_direction=1,
            adx_1h=28.0,
            vwap_deviation_z=-1.0,  # price below VWAP in uptrend = pullback
        )
        result = evaluate_entry(features, "BTCUSDT")
        assert "VWAP_TREND_PULLBACK" in result.boost_reasons

    def test_all_signals_aligned_strong(self):
        features = _base_features(
            oi_divergence_score=0.6,     # OI confirms
            smc_composite_score=0.6,      # SMC confirms
            vwap_deviation_z=-1.0,        # VWAP pullback
            adx_1h=28.0,
            trend_direction=1,
        )
        result = evaluate_entry(features, "BTCUSDT")
        assert result.signal_quality == "strong"
        assert result.size_multiplier >= 1.3
        assert "ALL_SIGNALS_ALIGNED" in result.boost_reasons

    def test_should_block_entry_quick(self):
        features = _base_features(oi_divergence_score=-0.8)
        block, reason = should_block_entry(features)
        assert block is True
        assert reason == "OI_FAKE_BREAKOUT"

    def test_should_not_block_normal(self):
        features = _base_features(oi_divergence_score=0.2)
        block, reason = should_block_entry(features)
        assert block is False

    def test_moderate_quality_two_signals(self):
        features = _base_features(
            oi_divergence_score=0.5,
            smc_composite_score=0.4,
            vwap_deviation_z=2.0,  # not in pullback zone
            adx_1h=25.0,
        )
        result = evaluate_entry(features, "BTCUSDT")
        assert result.signal_quality == "moderate"
