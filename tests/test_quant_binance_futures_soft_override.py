from __future__ import annotations

import os
import unittest
from pathlib import Path

from quant_binance.models import FeatureVector
from quant_binance.settings import Settings
from quant_binance.strategy.regime import _futures_entry_plan


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class QuantBinanceFuturesSoftOverrideTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_profile = os.environ.get("STRATEGY_PROFILE")
        os.environ["STRATEGY_PROFILE"] = "alpha_max"

    def tearDown(self) -> None:
        if self.old_profile is None:
            os.environ.pop("STRATEGY_PROFILE", None)
        else:
            os.environ["STRATEGY_PROFILE"] = self.old_profile

    def test_soft_only_reasons_can_enter_futures_with_reduced_size(self) -> None:
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.45,
            ret_rank_4h=0.4,
            breakout_norm=0.72,
            ema_stack_score=1.0,
            vol_z_5m_norm=0.6,
            vol_z_1h_norm=0.58,
            taker_imbalance_norm=0.52,
            spread_bps_norm=0.28,
            probe_slippage_bps_norm=0.3,
            depth_10bps_norm=0.7,
            book_stability_norm=0.8,
            realized_vol_1h_norm=0.83,
            realized_vol_4h_norm=0.77,
            vol_shock_norm=0.22,
            funding_abs_percentile=0.42,
            oi_surge_percentile=0.4,
            basis_stretch_percentile=0.36,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.64,
            volume_confirmation=0.46,
            liquidity_score=0.58,
            volatility_penalty=0.83,
            overheat_penalty=0.68,
            sentiment_regime="caution",
            macro_risk_penalty=0.2,
            macro_liquidity_support_score=0.42,
            macro_event_risk_score=0.2,
            gross_expected_edge_bps=20.0,
            estimated_round_trip_cost_bps=19.0,
            net_expected_edge_bps=1.0,
            predictability_score=58.0,
        )
        ok, reasons, size_multiplier = _futures_entry_plan(features, settings, "XRPUSDT")
        self.assertTrue(ok)
        self.assertIn("SENTIMENT_CAUTION", reasons)
        self.assertIn("EDGE_TOO_THIN", reasons)
        self.assertLess(size_multiplier, 1.0)

    def test_hard_reason_still_blocks_futures_even_with_override(self) -> None:
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.45,
            ret_rank_4h=0.4,
            breakout_norm=0.72,
            ema_stack_score=0.0,
            vol_z_5m_norm=0.6,
            vol_z_1h_norm=0.58,
            taker_imbalance_norm=0.52,
            spread_bps_norm=0.28,
            probe_slippage_bps_norm=0.3,
            depth_10bps_norm=0.7,
            book_stability_norm=0.8,
            realized_vol_1h_norm=0.83,
            realized_vol_4h_norm=0.77,
            vol_shock_norm=0.22,
            funding_abs_percentile=0.42,
            oi_surge_percentile=0.4,
            basis_stretch_percentile=0.36,
            regime_alignment=0.0,
            trend_direction=0,
            trend_strength=0.64,
            volume_confirmation=0.46,
            liquidity_score=0.58,
            volatility_penalty=0.83,
            overheat_penalty=0.68,
            sentiment_regime="caution",
            macro_risk_penalty=0.2,
            macro_liquidity_support_score=0.42,
            macro_event_risk_score=0.2,
            gross_expected_edge_bps=20.0,
            estimated_round_trip_cost_bps=19.0,
            net_expected_edge_bps=1.0,
            predictability_score=57.0,
        )
        ok, reasons, _ = _futures_entry_plan(features, settings, "XRPUSDT")
        self.assertFalse(ok)
        self.assertIn("DIRECTION_CONFLICT", reasons)


if __name__ == "__main__":
    unittest.main()
