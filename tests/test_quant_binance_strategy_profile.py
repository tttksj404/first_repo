from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from pathlib import Path

from quant_binance.models import FeatureVector, MarketSnapshot
from quant_binance.settings import Settings
from quant_binance.strategy.regime import evaluate_snapshot


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class QuantBinanceStrategyProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_profile = os.environ.get("STRATEGY_PROFILE")
        os.environ.pop("STRATEGY_PROFILE", None)

    def tearDown(self) -> None:
        if self.old_profile is not None:
            os.environ["STRATEGY_PROFILE"] = self.old_profile
        else:
            os.environ.pop("STRATEGY_PROFILE", None)

    def test_default_profile_is_conservative(self) -> None:
        settings = Settings.load(CONFIG_PATH)
        self.assertEqual(settings.strategy_profile, "conservative")
        self.assertEqual(settings.mode_thresholds.spot_score_min, 55)
        self.assertEqual(settings.cost_gate.edge_to_cost_multiple_min, 1.5)

    def test_balanced_profile_relaxes_spot_constraints(self) -> None:
        os.environ["STRATEGY_PROFILE"] = "balanced"
        settings = Settings.load(CONFIG_PATH)
        self.assertEqual(settings.strategy_profile, "balanced")
        self.assertEqual(settings.mode_thresholds.spot_score_min, 50)
        self.assertEqual(settings.cost_gate.edge_to_cost_multiple_min, 1.2)
        self.assertEqual(settings.spot_support.support_alignment_min, 0.2)

    def test_active_profile_is_more_permissive(self) -> None:
        os.environ["STRATEGY_PROFILE"] = "active"
        settings = Settings.load(CONFIG_PATH)
        self.assertEqual(settings.strategy_profile, "active")
        self.assertEqual(settings.mode_thresholds.spot_score_min, 42)
        self.assertEqual(settings.cost_gate.edge_to_cost_multiple_min, 0.9)
        self.assertFalse(settings.mode_behavior.spot_require_positive_trend)
        self.assertEqual(settings.cash_reserve.when_futures_enabled, 0.1)
        self.assertEqual(settings.spot_support.support_alignment_min, 0.0)
        self.assertEqual(settings.spot_support.resistance_penalty_max, 0.9)
        self.assertEqual(settings.spot_support.sentiment_support_min, 0.0)
        self.assertEqual(settings.spot_support.liquidity_relaxation, 0.12)
        self.assertEqual(settings.spot_support.breakout_resistance_override_min, 0.78)
        self.assertEqual(settings.spot_support.bottoming_support_override_min, 0.12)
        self.assertEqual(settings.macro_gates.spot_block_penalty, 0.98)
        self.assertTrue(settings.mode_behavior.spot_allow_bottoming_reversal)
        self.assertEqual(settings.symbol_eligibility.observe_only_liquidity_max, 0.28)

    def test_active_profile_thresholds_affect_spot_decision(self) -> None:
        os.environ["STRATEGY_PROFILE"] = "active"
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.8,
            ret_rank_4h=0.78,
            breakout_norm=0.82,
            ema_stack_score=1.0,
            vol_z_5m_norm=0.7,
            vol_z_1h_norm=0.72,
            taker_imbalance_norm=0.69,
            spread_bps_norm=0.2,
            probe_slippage_bps_norm=0.25,
            depth_10bps_norm=0.86,
            book_stability_norm=0.9,
            realized_vol_1h_norm=0.3,
            realized_vol_4h_norm=0.28,
            vol_shock_norm=0.35,
            funding_abs_percentile=0.14,
            oi_surge_percentile=0.1,
            basis_stretch_percentile=0.18,
            regime_alignment=1.0,
            trend_direction=0,
            trend_strength=0.58,
            volume_confirmation=0.74,
            liquidity_score=0.7,
            volatility_penalty=0.25,
            overheat_penalty=0.14,
            support_alignment=0.05,
            resistance_penalty=0.8,
            macro_risk_penalty=0.9,
            sentiment_support_score=0.05,
            gross_expected_edge_bps=30.0,
            estimated_round_trip_cost_bps=20.0,
        )
        snapshot = MarketSnapshot(
            snapshot_id="snap-active",
            config_version=settings.config_version,
            snapshot_schema_version=settings.snapshot_schema_version,
            symbol="ETHUSDT",
            decision_time=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
            last_trade_price=50000.0,
            best_bid=49999.5,
            best_ask=50000.5,
            funding_rate=0.0001,
            open_interest=1000000.0,
            basis_bps=4.5,
            data_freshness_ms=100,
            feature_values=features,
        )
        decision = evaluate_snapshot(
            snapshot,
            settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=settings.cash_reserve.when_futures_enabled,
        )
        self.assertEqual(decision.final_mode, "spot")

    def test_active_profile_allows_bottoming_reversal_with_relaxed_liquidity(self) -> None:
        os.environ["STRATEGY_PROFILE"] = "active"
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.8,
            ret_rank_4h=0.78,
            breakout_norm=0.82,
            ema_stack_score=1.0,
            vol_z_5m_norm=0.7,
            vol_z_1h_norm=0.72,
            taker_imbalance_norm=0.69,
            spread_bps_norm=0.2,
            probe_slippage_bps_norm=0.25,
            depth_10bps_norm=0.86,
            book_stability_norm=0.9,
            realized_vol_1h_norm=0.3,
            realized_vol_4h_norm=0.28,
            vol_shock_norm=0.35,
            funding_abs_percentile=0.14,
            oi_surge_percentile=0.1,
            basis_stretch_percentile=0.18,
            regime_alignment=1.0,
            trend_direction=-1,
            trend_strength=0.58,
            volume_confirmation=0.74,
            liquidity_score=0.34,
            volatility_penalty=0.25,
            overheat_penalty=0.14,
            support_alignment=0.2,
            resistance_penalty=0.88,
            macro_risk_penalty=0.2,
            sentiment_regime="bottoming",
            sentiment_support_score=0.6,
            gross_expected_edge_bps=35.0,
            estimated_round_trip_cost_bps=20.0,
        )
        snapshot = MarketSnapshot(
            snapshot_id="snap-bottoming",
            config_version=settings.config_version,
            snapshot_schema_version=settings.snapshot_schema_version,
            symbol="SIGNUSDT",
            decision_time=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
            last_trade_price=50000.0,
            best_bid=49999.5,
            best_ask=50000.5,
            funding_rate=0.0001,
            open_interest=1000000.0,
            basis_bps=4.5,
            data_freshness_ms=100,
            feature_values=features,
        )
        decision = evaluate_snapshot(
            snapshot,
            settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=settings.cash_reserve.when_futures_enabled,
        )
        self.assertEqual(decision.final_mode, "spot")


if __name__ == "__main__":
    unittest.main()
