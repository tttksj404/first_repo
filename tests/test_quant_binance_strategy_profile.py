from __future__ import annotations

import os
import unittest
from dataclasses import replace
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

    def test_balanced_profile_relaxes_spot_and_futures_constraints(self) -> None:
        os.environ["STRATEGY_PROFILE"] = "balanced"
        settings = Settings.load(CONFIG_PATH)
        self.assertEqual(settings.strategy_profile, "balanced")
        self.assertEqual(settings.mode_thresholds.futures_score_min, 73)
        self.assertEqual(settings.mode_thresholds.futures_trend_strength_min, 0.66)
        self.assertEqual(settings.mode_thresholds.futures_liquidity_min, 0.68)
        self.assertEqual(settings.mode_thresholds.futures_volatility_penalty_max, 0.47)
        self.assertEqual(settings.mode_thresholds.futures_overheat_penalty_max, 0.38)
        self.assertEqual(settings.mode_thresholds.spot_score_min, 50)
        self.assertEqual(settings.cost_gate.edge_to_cost_multiple_min, 1.1)
        self.assertEqual(settings.spot_support.support_alignment_min, 0.2)
        self.assertEqual(settings.futures_exposure.soft_liquidity_floor, 0.62)
        self.assertEqual(settings.futures_exposure.reduced_size_multiplier, 0.65)
        self.assertEqual(settings.futures_exposure.strong_size_multiplier, 1.2)

    def test_active_profile_is_more_permissive(self) -> None:
        os.environ["STRATEGY_PROFILE"] = "active"
        settings = Settings.load(CONFIG_PATH)
        self.assertEqual(settings.strategy_profile, "active")
        self.assertEqual(settings.mode_thresholds.futures_score_min, 60)
        self.assertEqual(settings.mode_thresholds.futures_trend_strength_min, 0.58)
        self.assertEqual(settings.mode_thresholds.spot_score_min, 48)
        self.assertEqual(settings.cost_gate.edge_to_cost_multiple_min, 1.05)
        self.assertEqual(settings.risk.target_futures_leverage, 5.0)
        self.assertEqual(settings.risk.max_futures_leverage, 10.0)
        self.assertFalse(settings.mode_behavior.spot_require_positive_trend)
        self.assertEqual(settings.cash_reserve.when_futures_enabled, 0.12)
        self.assertEqual(settings.spot_support.support_alignment_min, 0.12)
        self.assertEqual(settings.spot_support.resistance_penalty_max, 0.82)
        self.assertEqual(settings.spot_support.sentiment_support_min, 0.05)
        self.assertEqual(settings.spot_support.liquidity_relaxation, 0.1)
        self.assertEqual(settings.spot_support.breakout_resistance_override_min, 0.82)
        self.assertEqual(settings.spot_support.bottoming_support_override_min, 0.16)
        self.assertEqual(
            settings.spot_support.priority_symbols,
            ("DOGEUSDT", "SOLUSDT", "ADAUSDT", "FLOWUSDT", "WLDUSDT"),
        )
        self.assertEqual(settings.macro_gates.futures_block_penalty, 0.72)
        self.assertEqual(settings.macro_gates.spot_block_penalty, 0.95)
        self.assertTrue(settings.mode_behavior.spot_allow_bottoming_reversal)
        self.assertEqual(settings.symbol_eligibility.observe_only_liquidity_max, 0.28)
        self.assertEqual(settings.futures_exposure.macro_support_min, 0.55)
        self.assertEqual(settings.futures_exposure.macro_score_relaxation, 5.0)
        self.assertEqual(settings.futures_exposure.soft_volatility_penalty_max, 0.72)
        self.assertEqual(settings.futures_exposure.reduced_entry_net_edge_bps, 6.0)
        self.assertEqual(
            settings.futures_exposure.priority_symbols,
            ("DOGEUSDT", "SOLUSDT", "TRXUSDT", "FLOWUSDT", "ADAUSDT", "WLDUSDT"),
        )
        self.assertEqual(settings.futures_exposure.priority_score_relaxation, 5.0)
        self.assertEqual(settings.futures_exposure.priority_min_entry_net_edge_bps, 0.5)
        self.assertTrue(settings.portfolio_focus.enabled)
        self.assertEqual(settings.portfolio_focus.spot_top_n, 1)
        self.assertEqual(settings.portfolio_focus.futures_top_n, 2)

    def test_live_aggressive_profile_is_more_permissive_for_futures(self) -> None:
        os.environ["STRATEGY_PROFILE"] = "live-aggressive"
        settings = Settings.load(CONFIG_PATH)
        self.assertEqual(settings.strategy_profile, "live-aggressive")
        self.assertEqual(settings.mode_thresholds.futures_score_min, 50)
        self.assertEqual(settings.mode_thresholds.futures_liquidity_min, 0.46)
        self.assertEqual(settings.cost_gate.edge_to_cost_multiple_min, 0.82)
        self.assertEqual(settings.risk.target_futures_leverage, 6.0)
        self.assertEqual(settings.risk.max_futures_leverage, 12.0)
        self.assertEqual(settings.futures_exposure.reduced_entry_net_edge_bps, 1.5)
        self.assertEqual(settings.portfolio_focus.futures_top_n, 4)

    def test_live_ultra_aggressive_profile_pushes_futures_even_lower(self) -> None:
        os.environ["STRATEGY_PROFILE"] = "live-ultra-aggressive"
        settings = Settings.load(CONFIG_PATH)
        self.assertEqual(settings.strategy_profile, "live-ultra-aggressive")
        self.assertEqual(settings.mode_thresholds.futures_score_min, 42)
        self.assertEqual(settings.mode_thresholds.futures_liquidity_min, 0.32)
        self.assertEqual(settings.cost_gate.edge_to_cost_multiple_min, 0.65)
        self.assertEqual(settings.risk.target_futures_leverage, 8.0)
        self.assertEqual(settings.risk.max_futures_leverage, 15.0)
        self.assertEqual(settings.futures_exposure.reduced_entry_net_edge_bps, -1.0)
        self.assertEqual(settings.futures_exposure.reduced_size_multiplier, 0.75)
        self.assertEqual(settings.futures_exposure.strong_size_multiplier, 2.8)
        self.assertEqual(settings.futures_exposure.major_symbols, ("BTCUSDT", "ETHUSDT", "SOLUSDT"))
        self.assertEqual(settings.futures_exposure.major_size_boost_multiplier, 1.35)
        self.assertEqual(settings.futures_exposure.major_medium_size_boost_multiplier, 1.15)
        self.assertEqual(settings.futures_exposure.major_medium_min_entry_notional_usd, 140.0)
        self.assertEqual(settings.futures_exposure.major_medium_total_notional_fraction_relaxation, 0.08)
        self.assertEqual(settings.futures_exposure.major_medium_safety_cap_fraction, 0.7)
        self.assertEqual(settings.futures_exposure.major_strong_min_entry_notional_usd, 180.0)
        self.assertEqual(settings.futures_exposure.major_strong_total_notional_fraction_relaxation, 0.22)
        self.assertEqual(settings.futures_exposure.major_strong_safety_cap_fraction, 0.92)
        self.assertEqual(settings.futures_exposure.alt_score_penalty_without_macro, 4.0)
        self.assertTrue(settings.futures_exposure.pyramid_enabled)
        self.assertEqual(settings.futures_exposure.major_reallocation_score_advantage_relaxation, 2.5)
        self.assertEqual(settings.live_position_risk.partial_exit_min_interval_minutes, 60)
        self.assertEqual(settings.live_position_risk.major_partial_exit_fraction, 0.75)
        self.assertTrue(settings.live_position_risk.major_drawdown_grace_enabled)
        self.assertEqual(settings.live_position_risk.major_drawdown_grace_minutes, 120)
        self.assertEqual(settings.live_position_risk.major_drawdown_abort_roe_percent, -12.0)
        self.assertEqual(settings.live_position_risk.major_reentry_cooldown_minutes, 90)
        self.assertEqual(settings.live_position_risk.major_reversal_confirmation_cycles, 3)
        self.assertEqual(settings.live_position_risk.major_reversal_min_holding_minutes, 45)
        self.assertEqual(settings.live_position_risk.major_loss_reentry_cooldown_minutes, 180)
        self.assertEqual(settings.live_position_risk.major_loss_reentry_trigger_usd, 1.0)
        self.assertEqual(settings.live_position_risk.major_missing_on_exchange_threshold, 10)
        self.assertEqual(settings.live_position_risk.major_drawdown_grace_minutes, 120)
        self.assertEqual(settings.portfolio_focus.futures_top_n, 6)
        self.assertEqual(settings.operational_limits.max_concurrent_futures_symbols, 6)

    def test_active_profile_allows_strong_bearish_futures_short_under_caution(self) -> None:
        os.environ["STRATEGY_PROFILE"] = "active"
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.22,
            ret_rank_4h=0.18,
            breakout_norm=0.78,
            ema_stack_score=1.0,
            vol_z_5m_norm=0.76,
            vol_z_1h_norm=0.74,
            taker_imbalance_norm=0.18,
            spread_bps_norm=0.18,
            probe_slippage_bps_norm=0.2,
            depth_10bps_norm=0.88,
            book_stability_norm=0.9,
            realized_vol_1h_norm=0.66,
            realized_vol_4h_norm=0.6,
            vol_shock_norm=0.25,
            funding_abs_percentile=0.22,
            oi_surge_percentile=0.2,
            basis_stretch_percentile=0.18,
            regime_alignment=1.0,
            trend_direction=-1,
            trend_strength=0.74,
            volume_confirmation=0.68,
            liquidity_score=0.72,
            volatility_penalty=0.66,
            overheat_penalty=0.34,
            support_alignment=0.08,
            resistance_penalty=0.14,
            sentiment_regime="caution",
            sentiment_support_score=0.2,
            gross_expected_edge_bps=44.0,
            estimated_round_trip_cost_bps=20.0,
            net_expected_edge_bps=24.0,
        )
        snapshot = MarketSnapshot(
            snapshot_id="snap-active-bearish-short",
            config_version=settings.config_version,
            snapshot_schema_version=settings.snapshot_schema_version,
            symbol="BTCUSDT",
            decision_time=datetime(2026, 3, 11, 0, 0, tzinfo=timezone.utc),
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

        self.assertEqual(decision.final_mode, "futures")
        self.assertEqual(decision.side, "short")

    def test_active_profile_uses_leverage_aware_notional_for_small_capital_strong_futures(self) -> None:
        os.environ["STRATEGY_PROFILE"] = "active"
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.18,
            ret_rank_4h=0.14,
            breakout_norm=0.9,
            ema_stack_score=1.0,
            vol_z_5m_norm=0.8,
            vol_z_1h_norm=0.78,
            taker_imbalance_norm=0.14,
            spread_bps_norm=0.14,
            probe_slippage_bps_norm=0.16,
            depth_10bps_norm=0.9,
            book_stability_norm=0.92,
            realized_vol_1h_norm=0.25,
            realized_vol_4h_norm=0.22,
            vol_shock_norm=0.12,
            funding_abs_percentile=0.18,
            oi_surge_percentile=0.16,
            basis_stretch_percentile=0.14,
            regime_alignment=1.0,
            trend_direction=-1,
            trend_strength=0.88,
            volume_confirmation=0.82,
            liquidity_score=0.85,
            volatility_penalty=0.24,
            overheat_penalty=0.18,
            support_alignment=0.04,
            resistance_penalty=0.1,
            sentiment_regime="neutral",
            sentiment_support_score=0.1,
            gross_expected_edge_bps=40.0,
            estimated_round_trip_cost_bps=12.0,
            net_expected_edge_bps=28.0,
        )
        snapshot = MarketSnapshot(
            snapshot_id="snap-active-small-cap-futures",
            config_version=settings.config_version,
            snapshot_schema_version=settings.snapshot_schema_version,
            symbol="BTCUSDT",
            decision_time=datetime(2026, 3, 11, 0, 5, tzinfo=timezone.utc),
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
            equity_usd=100.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=settings.cash_reserve.when_futures_enabled,
        )

        self.assertEqual(decision.final_mode, "futures")
        self.assertEqual(decision.side, "short")
        self.assertGreater(decision.order_intent_notional_usd, 100.0)

    def test_balanced_profile_routes_mildly_heated_futures_setup_to_spot(self) -> None:
        conservative_settings = Settings.load(CONFIG_PATH)
        os.environ["STRATEGY_PROFILE"] = "balanced"
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.78,
            ret_rank_4h=0.76,
            breakout_norm=0.78,
            ema_stack_score=0.95,
            vol_z_5m_norm=0.68,
            vol_z_1h_norm=0.69,
            taker_imbalance_norm=0.66,
            spread_bps_norm=0.22,
            probe_slippage_bps_norm=0.25,
            depth_10bps_norm=0.8,
            book_stability_norm=0.88,
            realized_vol_1h_norm=1.3,
            realized_vol_4h_norm=1.2,
            vol_shock_norm=0.34,
            funding_abs_percentile=0.22,
            oi_surge_percentile=0.18,
            basis_stretch_percentile=0.2,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.76,
            volume_confirmation=0.76,
            liquidity_score=0.66,
            volatility_penalty=0.48,
            overheat_penalty=0.39,
            support_alignment=0.48,
            resistance_penalty=0.18,
            sentiment_regime="neutral",
            sentiment_support_score=0.62,
            gross_expected_edge_bps=20.0,
            estimated_round_trip_cost_bps=17.0,
        )
        snapshot = MarketSnapshot(
            snapshot_id="snap-balanced-futures",
            config_version=settings.config_version,
            snapshot_schema_version=settings.snapshot_schema_version,
            symbol="BTCUSDT",
            decision_time=datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc),
            last_trade_price=50000.0,
            best_bid=49999.5,
            best_ask=50000.5,
            funding_rate=0.0001,
            open_interest=1000000.0,
            basis_bps=4.5,
            data_freshness_ms=100,
            feature_values=features,
        )
        conservative_decision = evaluate_snapshot(
            snapshot,
            conservative_settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=conservative_settings.cash_reserve.when_futures_enabled,
        )
        decision = evaluate_snapshot(
            snapshot,
            settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=settings.cash_reserve.when_futures_enabled,
        )
        self.assertNotEqual(conservative_decision.final_mode, "futures")
        self.assertEqual(decision.final_mode, "spot")
        self.assertEqual(decision.side, "long")
        self.assertIn("EDGE_TOO_THIN", decision.rejection_reasons)

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
            support_alignment=0.12,
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
            liquidity_score=0.41,
            volatility_penalty=0.25,
            overheat_penalty=0.14,
            support_alignment=0.2,
            resistance_penalty=0.8,
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

    def test_active_profile_relaxes_futures_under_supportive_macro(self) -> None:
        conservative_settings = Settings.load(CONFIG_PATH)
        os.environ["STRATEGY_PROFILE"] = "active"
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.78,
            ret_rank_4h=0.76,
            breakout_norm=0.78,
            ema_stack_score=0.95,
            vol_z_5m_norm=0.68,
            vol_z_1h_norm=0.69,
            taker_imbalance_norm=0.66,
            spread_bps_norm=0.22,
            probe_slippage_bps_norm=0.25,
            depth_10bps_norm=0.8,
            book_stability_norm=0.88,
            realized_vol_1h_norm=0.3,
            realized_vol_4h_norm=0.28,
            vol_shock_norm=0.3,
            funding_abs_percentile=0.22,
            oi_surge_percentile=0.18,
            basis_stretch_percentile=0.2,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.7,
            volume_confirmation=0.72,
            liquidity_score=0.53,
            volatility_penalty=0.34,
            overheat_penalty=0.54,
            support_alignment=0.3,
            resistance_penalty=0.12,
            macro_regime="supportive",
            macro_risk_penalty=0.2,
            macro_liquidity_support_score=0.72,
            macro_event_risk_score=0.2,
            sentiment_regime="risk_on",
            sentiment_support_score=0.62,
            gross_expected_edge_bps=40.0,
            estimated_round_trip_cost_bps=20.0,
            net_expected_edge_bps=12.0,
        )
        snapshot = MarketSnapshot(
            snapshot_id="snap-active-futures-macro",
            config_version=settings.config_version,
            snapshot_schema_version=settings.snapshot_schema_version,
            symbol="BTCUSDT",
            decision_time=datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc),
            last_trade_price=50000.0,
            best_bid=49999.5,
            best_ask=50000.5,
            funding_rate=0.0001,
            open_interest=1000000.0,
            basis_bps=4.5,
            data_freshness_ms=100,
            feature_values=features,
        )
        conservative_decision = evaluate_snapshot(
            snapshot,
            conservative_settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=conservative_settings.cash_reserve.when_futures_enabled,
        )
        active_decision = evaluate_snapshot(
            snapshot,
            settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=settings.cash_reserve.when_futures_enabled,
        )
        self.assertNotEqual(conservative_decision.final_mode, "futures")
        self.assertEqual(active_decision.final_mode, "futures")

    def test_active_profile_priority_symbol_relaxes_futures_more_than_non_priority(self) -> None:
        os.environ["STRATEGY_PROFILE"] = "active"
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.78,
            ret_rank_4h=0.76,
            breakout_norm=0.78,
            ema_stack_score=0.95,
            vol_z_5m_norm=0.68,
            vol_z_1h_norm=0.69,
            taker_imbalance_norm=0.66,
            spread_bps_norm=0.22,
            probe_slippage_bps_norm=0.25,
            depth_10bps_norm=0.8,
            book_stability_norm=0.88,
            realized_vol_1h_norm=0.3,
            realized_vol_4h_norm=0.28,
            vol_shock_norm=0.3,
            funding_abs_percentile=0.22,
            oi_surge_percentile=0.18,
            basis_stretch_percentile=0.2,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.7,
            volume_confirmation=0.72,
            liquidity_score=0.56,
            volatility_penalty=0.34,
            overheat_penalty=0.58,
            support_alignment=0.3,
            resistance_penalty=0.12,
            macro_regime="supportive",
            macro_risk_penalty=0.2,
            macro_liquidity_support_score=0.72,
            macro_event_risk_score=0.2,
            sentiment_regime="caution",
            sentiment_support_score=0.62,
            gross_expected_edge_bps=21.0,
            estimated_round_trip_cost_bps=20.0,
            net_expected_edge_bps=1.0,
        )
        def make(symbol: str) -> MarketSnapshot:
            return MarketSnapshot(
                snapshot_id=f"snap-{symbol}",
                config_version=settings.config_version,
                snapshot_schema_version=settings.snapshot_schema_version,
                symbol=symbol,
                decision_time=datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc),
                last_trade_price=50000.0,
                best_bid=49999.5,
                best_ask=50000.5,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=4.5,
                data_freshness_ms=100,
                feature_values=features,
            )
        priority_decision = evaluate_snapshot(
            make("DOGEUSDT"),
            settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=settings.cash_reserve.when_futures_enabled,
        )
        non_priority_decision = evaluate_snapshot(
            make("ETHUSDT"),
            settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=settings.cash_reserve.when_futures_enabled,
        )
        self.assertEqual(priority_decision.final_mode, "futures")
        self.assertNotEqual(non_priority_decision.final_mode, "futures")

    def test_active_profile_priority_alt_symbol_relaxes_spot_more_than_non_priority(self) -> None:
        os.environ["STRATEGY_PROFILE"] = "active"
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.78,
            ret_rank_4h=0.76,
            breakout_norm=0.84,
            ema_stack_score=0.95,
            vol_z_5m_norm=0.68,
            vol_z_1h_norm=0.69,
            taker_imbalance_norm=0.66,
            spread_bps_norm=0.22,
            probe_slippage_bps_norm=0.25,
            depth_10bps_norm=0.8,
            book_stability_norm=0.88,
            realized_vol_1h_norm=0.3,
            realized_vol_4h_norm=0.28,
            vol_shock_norm=0.3,
            funding_abs_percentile=0.22,
            oi_surge_percentile=0.18,
            basis_stretch_percentile=0.2,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.5,
            volume_confirmation=0.72,
            liquidity_score=0.36,
            volatility_penalty=0.34,
            overheat_penalty=0.2,
            support_alignment=0.02,
            resistance_penalty=0.9,
            macro_regime="supportive",
            macro_risk_penalty=0.2,
            macro_liquidity_support_score=0.72,
            macro_event_risk_score=0.2,
            sentiment_regime="neutral",
            sentiment_support_score=0.2,
            alt_market_regime="neutral",
            alt_breadth_score=0.6,
            alt_liquidity_support_score=0.55,
            alt_fundamental_score=0.55,
            alt_smart_money_score=0.55,
            gross_expected_edge_bps=24.0,
            estimated_round_trip_cost_bps=20.0,
            net_expected_edge_bps=1.0,
        )
        def make(symbol: str) -> MarketSnapshot:
            return MarketSnapshot(
                snapshot_id=f"snap-{symbol}",
                config_version=settings.config_version,
                snapshot_schema_version=settings.snapshot_schema_version,
                symbol=symbol,
                decision_time=datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc),
                last_trade_price=50000.0,
                best_bid=49999.5,
                best_ask=50000.5,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=4.5,
                data_freshness_ms=100,
                feature_values=features,
            )
        priority_decision = evaluate_snapshot(
            make("DOGEUSDT"),
            settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=settings.cash_reserve.when_futures_enabled,
        )
        non_priority_decision = evaluate_snapshot(
            make("BCHUSDT"),
            settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=settings.cash_reserve.when_futures_enabled,
        )
        self.assertEqual(priority_decision.final_mode, "spot")
        self.assertNotEqual(non_priority_decision.final_mode, "spot")

    def test_active_profile_routes_near_threshold_futures_setup_to_spot_when_edge_is_thin(self) -> None:
        os.environ["STRATEGY_PROFILE"] = "active"
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.78,
            ret_rank_4h=0.76,
            breakout_norm=0.78,
            ema_stack_score=0.95,
            vol_z_5m_norm=0.68,
            vol_z_1h_norm=0.69,
            taker_imbalance_norm=0.66,
            spread_bps_norm=0.22,
            probe_slippage_bps_norm=0.25,
            depth_10bps_norm=0.8,
            book_stability_norm=0.88,
            realized_vol_1h_norm=0.32,
            realized_vol_4h_norm=0.31,
            vol_shock_norm=0.34,
            funding_abs_percentile=0.22,
            oi_surge_percentile=0.18,
            basis_stretch_percentile=0.2,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.68,
            volume_confirmation=0.72,
            liquidity_score=0.6,
            volatility_penalty=0.48,
            overheat_penalty=0.39,
            support_alignment=0.48,
            resistance_penalty=0.18,
            sentiment_regime="neutral",
            sentiment_support_score=0.62,
            gross_expected_edge_bps=20.0,
            estimated_round_trip_cost_bps=17.0,
        )
        snapshot = MarketSnapshot(
            snapshot_id="snap-active-futures",
            config_version=settings.config_version,
            snapshot_schema_version=settings.snapshot_schema_version,
            symbol="BTCUSDT",
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
        self.assertIn("EDGE_TOO_THIN", decision.rejection_reasons)

    def test_active_profile_softens_borderline_futures_setup_to_reduced_size_entry(self) -> None:
        os.environ["STRATEGY_PROFILE"] = "active"
        settings = Settings.load(CONFIG_PATH)
        strong_features = FeatureVector(
            ret_rank_1h=0.78,
            ret_rank_4h=0.76,
            breakout_norm=0.82,
            ema_stack_score=0.95,
            vol_z_5m_norm=0.68,
            vol_z_1h_norm=0.69,
            taker_imbalance_norm=0.66,
            spread_bps_norm=0.22,
            probe_slippage_bps_norm=0.25,
            depth_10bps_norm=0.92,
            book_stability_norm=0.92,
            realized_vol_1h_norm=1.2,
            realized_vol_4h_norm=1.1,
            vol_shock_norm=0.3,
            funding_abs_percentile=0.22,
            oi_surge_percentile=0.18,
            basis_stretch_percentile=0.2,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.72,
            volume_confirmation=0.72,
            liquidity_score=0.92,
            volatility_penalty=0.24,
            overheat_penalty=0.18,
            support_alignment=0.28,
            resistance_penalty=0.12,
            macro_regime="supportive",
            macro_risk_penalty=0.2,
            macro_liquidity_support_score=0.66,
            macro_event_risk_score=0.2,
            sentiment_regime="neutral",
            sentiment_support_score=0.62,
            gross_expected_edge_bps=42.0,
            estimated_round_trip_cost_bps=20.0,
            net_expected_edge_bps=22.0,
        )
        soft_features = FeatureVector(
            **{
                **strong_features.as_dict(),
                "trend_strength": 0.6,
                "volume_confirmation": 0.36,
                "volatility_penalty": 0.71,
                "overheat_penalty": 0.52,
                "sentiment_regime": "caution",
            }
        )
        def make(snapshot_id: str, features: FeatureVector) -> MarketSnapshot:
            return MarketSnapshot(
                snapshot_id=snapshot_id,
                config_version=settings.config_version,
                snapshot_schema_version=settings.snapshot_schema_version,
                symbol="BTCUSDT",
                decision_time=datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc),
                last_trade_price=50000.0,
                best_bid=49999.5,
                best_ask=50000.5,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=4.5,
                data_freshness_ms=100,
                feature_values=features,
            )
        strong_decision = evaluate_snapshot(
            make("snap-strong-futures", strong_features),
            settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=settings.cash_reserve.when_futures_enabled,
        )
        soft_decision = evaluate_snapshot(
            make("snap-soft-futures", soft_features),
            settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=settings.cash_reserve.when_futures_enabled,
        )
        self.assertEqual(strong_decision.final_mode, "futures")
        self.assertEqual(soft_decision.final_mode, "futures")
        self.assertGreater(strong_decision.order_intent_notional_usd, soft_decision.order_intent_notional_usd)

    def test_live_ultra_aggressive_major_symbol_gets_larger_futures_notional_than_alt_peer(self) -> None:
        os.environ["STRATEGY_PROFILE"] = "live-ultra-aggressive"
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.72,
            ret_rank_4h=0.68,
            breakout_norm=0.8,
            ema_stack_score=0.96,
            vol_z_5m_norm=0.66,
            vol_z_1h_norm=0.64,
            taker_imbalance_norm=0.58,
            spread_bps_norm=0.18,
            probe_slippage_bps_norm=0.2,
            depth_10bps_norm=0.84,
            book_stability_norm=0.9,
            realized_vol_1h_norm=0.32,
            realized_vol_4h_norm=0.28,
            vol_shock_norm=0.16,
            funding_abs_percentile=0.18,
            oi_surge_percentile=0.14,
            basis_stretch_percentile=0.16,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.8,
            volume_confirmation=0.78,
            liquidity_score=0.78,
            volatility_penalty=0.22,
            overheat_penalty=0.18,
            support_alignment=0.24,
            resistance_penalty=0.12,
            macro_regime="neutral",
            macro_risk_penalty=0.3,
            macro_liquidity_support_score=0.35,
            macro_event_risk_score=0.3,
            sentiment_regime="neutral",
            sentiment_support_score=0.55,
            alt_market_regime="neutral",
            alt_breadth_score=0.55,
            alt_liquidity_support_score=0.8,
            alt_fundamental_score=0.55,
            alt_smart_money_score=0.55,
            alt_rotation_penalty=0.1,
            gross_expected_edge_bps=26.0,
            estimated_round_trip_cost_bps=10.0,
            net_expected_edge_bps=16.0,
        )

        def make(symbol: str) -> MarketSnapshot:
            return MarketSnapshot(
                snapshot_id=f"snap-{symbol}",
                config_version=settings.config_version,
                snapshot_schema_version=settings.snapshot_schema_version,
                symbol=symbol,
                decision_time=datetime(2026, 3, 14, 0, 0, tzinfo=timezone.utc),
                last_trade_price=50000.0 if symbol == "BTCUSDT" else 0.25,
                best_bid=49999.5 if symbol == "BTCUSDT" else 0.2499,
                best_ask=50000.5 if symbol == "BTCUSDT" else 0.2501,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=4.5,
                data_freshness_ms=100,
                feature_values=features,
            )

        major_decision = evaluate_snapshot(
            make("BTCUSDT"),
            settings,
            equity_usd=1000.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=settings.cash_reserve.when_futures_enabled,
        )
        alt_decision = evaluate_snapshot(
            make("DOGEUSDT"),
            settings,
            equity_usd=1000.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=settings.cash_reserve.when_futures_enabled,
        )

        self.assertEqual(major_decision.final_mode, "futures")
        self.assertEqual(alt_decision.final_mode, "futures")
        self.assertGreater(major_decision.order_intent_notional_usd, alt_decision.order_intent_notional_usd)

    def test_live_ultra_aggressive_alt_symbol_is_not_favored_over_major_without_supportive_macro(self) -> None:
        os.environ["STRATEGY_PROFILE"] = "live-ultra-aggressive"
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.62,
            ret_rank_4h=0.6,
            breakout_norm=0.68,
            ema_stack_score=0.9,
            vol_z_5m_norm=0.6,
            vol_z_1h_norm=0.58,
            taker_imbalance_norm=0.5,
            spread_bps_norm=0.2,
            probe_slippage_bps_norm=0.22,
            depth_10bps_norm=0.72,
            book_stability_norm=0.84,
            realized_vol_1h_norm=0.38,
            realized_vol_4h_norm=0.34,
            vol_shock_norm=0.18,
            funding_abs_percentile=0.18,
            oi_surge_percentile=0.14,
            basis_stretch_percentile=0.16,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.66,
            volume_confirmation=0.62,
            liquidity_score=0.34,
            volatility_penalty=0.34,
            overheat_penalty=0.22,
            support_alignment=0.2,
            resistance_penalty=0.12,
            macro_regime="neutral",
            macro_risk_penalty=0.35,
            macro_liquidity_support_score=0.35,
            macro_event_risk_score=0.3,
            sentiment_regime="neutral",
            sentiment_support_score=0.55,
            alt_market_regime="neutral",
            alt_breadth_score=0.55,
            alt_liquidity_support_score=0.7,
            alt_fundamental_score=0.55,
            alt_smart_money_score=0.55,
            alt_rotation_penalty=0.1,
            gross_expected_edge_bps=18.0,
            estimated_round_trip_cost_bps=12.0,
            net_expected_edge_bps=3.0,
        )

        def make(symbol: str) -> MarketSnapshot:
            return MarketSnapshot(
                snapshot_id=f"snap-{symbol}",
                config_version=settings.config_version,
                snapshot_schema_version=settings.snapshot_schema_version,
                symbol=symbol,
                decision_time=datetime(2026, 3, 14, 0, 0, tzinfo=timezone.utc),
                last_trade_price=50000.0 if symbol == "BTCUSDT" else 0.25,
                best_bid=49999.5 if symbol == "BTCUSDT" else 0.2499,
                best_ask=50000.5 if symbol == "BTCUSDT" else 0.2501,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=4.5,
                data_freshness_ms=100,
                feature_values=features,
            )

        major_decision = evaluate_snapshot(
            make("BTCUSDT"),
            settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=settings.cash_reserve.when_futures_enabled,
        )
        alt_decision = evaluate_snapshot(
            make("DOGEUSDT"),
            settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=settings.cash_reserve.when_futures_enabled,
        )

        self.assertEqual(major_decision.final_mode, "futures")
        if alt_decision.final_mode == "futures":
            self.assertLessEqual(alt_decision.order_intent_notional_usd, major_decision.order_intent_notional_usd)


    def test_macro_event_window_restrains_majors_and_blocks_risk_off_alts(self) -> None:
        settings = Settings.load(CONFIG_PATH)
        base_features = FeatureVector(
            ret_rank_1h=0.8, ret_rank_4h=0.82, breakout_norm=0.78, ema_stack_score=1.0,
            vol_z_5m_norm=0.7, vol_z_1h_norm=0.68, taker_imbalance_norm=0.64,
            spread_bps_norm=0.18, probe_slippage_bps_norm=0.18, depth_10bps_norm=0.84,
            book_stability_norm=0.84, realized_vol_1h_norm=0.28, realized_vol_4h_norm=0.26,
            vol_shock_norm=0.12, funding_abs_percentile=0.12, oi_surge_percentile=0.18,
            basis_stretch_percentile=0.16, regime_alignment=1.0, trend_direction=1,
            trend_strength=0.82, volume_confirmation=0.76, liquidity_score=0.86,
            volatility_penalty=0.2, overheat_penalty=0.16, support_alignment=0.42,
            resistance_penalty=0.08, macro_regime="high_risk", macro_risk_penalty=0.72,
            macro_liquidity_support_score=0.22, macro_event_risk_score=0.92,
            macro_trade_restraint="halt_high_impact_window", macro_size_multiplier=0.0,
            macro_leverage_cap=1, macro_symbol_bias="majors_only",
            sentiment_regime="risk_on", sentiment_support_score=0.68,
            alt_market_regime="neutral", alt_breadth_score=0.62, alt_liquidity_support_score=0.82,
            alt_fundamental_score=0.58, alt_smart_money_score=0.58, alt_rotation_penalty=0.08,
            gross_expected_edge_bps=28.0, estimated_round_trip_cost_bps=8.0, net_expected_edge_bps=20.0,
        )

        def make(symbol: str, features: FeatureVector) -> MarketSnapshot:
            return MarketSnapshot(
                snapshot_id=f"snap-{symbol}",
                config_version=settings.config_version,
                snapshot_schema_version=settings.snapshot_schema_version,
                symbol=symbol,
                decision_time=datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc),
                last_trade_price=50000.0 if symbol == "BTCUSDT" else 0.25,
                best_bid=49999.5 if symbol == "BTCUSDT" else 0.2499,
                best_ask=50000.5 if symbol == "BTCUSDT" else 0.2501,
                funding_rate=0.0001, open_interest=1000000.0, basis_bps=4.0, data_freshness_ms=100,
                feature_values=features,
            )

        restrained_major = evaluate_snapshot(make("BTCUSDT", base_features), settings, 10000.0, 5000.0, cash_reserve_fraction=settings.cash_reserve.when_futures_enabled)
        neutral_major = evaluate_snapshot(make("BTCUSDT", replace(base_features, macro_regime="neutral", macro_risk_penalty=0.2, macro_event_risk_score=0.1, macro_trade_restraint="none", macro_size_multiplier=1.0, macro_leverage_cap=0, macro_symbol_bias="neutral", macro_liquidity_support_score=0.55)), settings, 10000.0, 5000.0, cash_reserve_fraction=settings.cash_reserve.when_futures_enabled)
        alt_decision = evaluate_snapshot(make("DOGEUSDT", base_features), settings, 10000.0, 5000.0, cash_reserve_fraction=settings.cash_reserve.when_futures_enabled)

        self.assertIn(restrained_major.final_mode, {"spot", "futures"})
        self.assertEqual(restrained_major.macro_trade_restraint, "halt_high_impact_window")
        self.assertLess(restrained_major.order_intent_notional_usd, neutral_major.order_intent_notional_usd)
        self.assertEqual(alt_decision.final_mode, "cash")
        self.assertIn("MACRO_EVENT_WINDOW", alt_decision.rejection_reasons)
        self.assertIn("MACRO_MAJORS_ONLY", alt_decision.rejection_reasons)

    def test_macro_risk_off_bias_keeps_major_futures_larger_than_alt(self) -> None:
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.74, ret_rank_4h=0.74, breakout_norm=0.72, ema_stack_score=1.0,
            vol_z_5m_norm=0.62, vol_z_1h_norm=0.62, taker_imbalance_norm=0.58,
            spread_bps_norm=0.2, probe_slippage_bps_norm=0.2, depth_10bps_norm=0.8,
            book_stability_norm=0.82, realized_vol_1h_norm=0.3, realized_vol_4h_norm=0.3,
            vol_shock_norm=0.14, funding_abs_percentile=0.16, oi_surge_percentile=0.18,
            basis_stretch_percentile=0.16, regime_alignment=1.0, trend_direction=1,
            trend_strength=0.76, volume_confirmation=0.7, liquidity_score=0.78,
            volatility_penalty=0.24, overheat_penalty=0.18, support_alignment=0.36,
            resistance_penalty=0.1, macro_regime="high_risk", macro_risk_penalty=0.58,
            macro_liquidity_support_score=0.28, macro_event_risk_score=0.5,
            macro_trade_restraint="risk_off_reduce", macro_size_multiplier=0.7,
            macro_leverage_cap=2, macro_symbol_bias="majors_only",
            sentiment_regime="neutral", sentiment_support_score=0.58,
            alt_market_regime="neutral", alt_breadth_score=0.64, alt_liquidity_support_score=0.82,
            alt_fundamental_score=0.6, alt_smart_money_score=0.6, alt_rotation_penalty=0.08,
            gross_expected_edge_bps=24.0, estimated_round_trip_cost_bps=8.0, net_expected_edge_bps=16.0,
        )

        def make(symbol: str) -> MarketSnapshot:
            return MarketSnapshot(
                snapshot_id=f"snap-{symbol}", config_version=settings.config_version, snapshot_schema_version=settings.snapshot_schema_version,
                symbol=symbol, decision_time=datetime(2026, 3, 16, 12, 5, tzinfo=timezone.utc),
                last_trade_price=50000.0 if symbol == "BTCUSDT" else 0.25, best_bid=49999.5 if symbol == "BTCUSDT" else 0.2499,
                best_ask=50000.5 if symbol == "BTCUSDT" else 0.2501, funding_rate=0.0001, open_interest=1000000.0, basis_bps=4.0, data_freshness_ms=100, feature_values=features,
            )

        major_decision = evaluate_snapshot(make("BTCUSDT"), settings, 10000.0, 5000.0, cash_reserve_fraction=settings.cash_reserve.when_futures_enabled)
        alt_decision = evaluate_snapshot(make("DOGEUSDT"), settings, 10000.0, 5000.0, cash_reserve_fraction=settings.cash_reserve.when_futures_enabled)

        self.assertEqual(major_decision.final_mode, "futures")
        self.assertEqual(major_decision.macro_symbol_bias, "majors_only")
        self.assertEqual(alt_decision.final_mode, "cash")
        self.assertIn("MACRO_MAJORS_ONLY", alt_decision.rejection_reasons)

    def test_btc_eth_spot_can_relax_slight_support_and_sentiment_miss(self) -> None:
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.62,
            ret_rank_4h=0.6,
            breakout_norm=0.72,
            ema_stack_score=0.95,
            vol_z_5m_norm=0.62,
            vol_z_1h_norm=0.6,
            taker_imbalance_norm=0.58,
            spread_bps_norm=0.16,
            probe_slippage_bps_norm=0.18,
            depth_10bps_norm=0.82,
            book_stability_norm=0.9,
            realized_vol_1h_norm=0.24,
            realized_vol_4h_norm=0.22,
            vol_shock_norm=0.14,
            funding_abs_percentile=0.12,
            oi_surge_percentile=0.12,
            basis_stretch_percentile=0.14,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.64,
            volume_confirmation=0.76,
            liquidity_score=0.72,
            volatility_penalty=0.22,
            overheat_penalty=0.16,
            support_alignment=0.29,
            resistance_penalty=0.14,
            sentiment_regime="neutral",
            sentiment_support_score=0.21,
            gross_expected_edge_bps=24.0,
            estimated_round_trip_cost_bps=10.0,
            net_expected_edge_bps=14.0,
        )
        snapshot = MarketSnapshot(
            snapshot_id="snap-eth-spot-relax",
            config_version=settings.config_version,
            snapshot_schema_version=settings.snapshot_schema_version,
            symbol="ETHUSDT",
            decision_time=datetime(2026, 3, 16, 13, 0, tzinfo=timezone.utc),
            last_trade_price=3000.0,
            best_bid=2999.5,
            best_ask=3000.5,
            funding_rate=0.0001,
            open_interest=1000000.0,
            basis_bps=3.0,
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
        self.assertEqual(
            decision.entry_relaxation_reasons,
            ("SUPPORT_NOT_CONFIRMED", "SENTIMENT_TOO_WEAK"),
        )

    def test_alt_spot_does_not_get_btc_eth_relaxation(self) -> None:
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.62,
            ret_rank_4h=0.6,
            breakout_norm=0.72,
            ema_stack_score=0.95,
            vol_z_5m_norm=0.62,
            vol_z_1h_norm=0.6,
            taker_imbalance_norm=0.58,
            spread_bps_norm=0.16,
            probe_slippage_bps_norm=0.18,
            depth_10bps_norm=0.82,
            book_stability_norm=0.9,
            realized_vol_1h_norm=0.24,
            realized_vol_4h_norm=0.22,
            vol_shock_norm=0.14,
            funding_abs_percentile=0.12,
            oi_surge_percentile=0.12,
            basis_stretch_percentile=0.14,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.64,
            volume_confirmation=0.76,
            liquidity_score=0.72,
            volatility_penalty=0.22,
            overheat_penalty=0.16,
            support_alignment=0.29,
            resistance_penalty=0.14,
            sentiment_regime="neutral",
            sentiment_support_score=0.21,
            alt_market_regime="neutral",
            alt_breadth_score=0.62,
            alt_liquidity_support_score=0.82,
            alt_fundamental_score=0.58,
            alt_smart_money_score=0.58,
            alt_rotation_penalty=0.08,
            gross_expected_edge_bps=24.0,
            estimated_round_trip_cost_bps=10.0,
            net_expected_edge_bps=14.0,
        )
        snapshot = MarketSnapshot(
            snapshot_id="snap-doge-spot-relax",
            config_version=settings.config_version,
            snapshot_schema_version=settings.snapshot_schema_version,
            symbol="DOGEUSDT",
            decision_time=datetime(2026, 3, 16, 13, 1, tzinfo=timezone.utc),
            last_trade_price=0.25,
            best_bid=0.2499,
            best_ask=0.2501,
            funding_rate=0.0001,
            open_interest=1000000.0,
            basis_bps=3.0,
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

        self.assertNotEqual(decision.final_mode, "spot")
        self.assertEqual(decision.entry_relaxation_reasons, ())
        self.assertIn("SUPPORT_NOT_CONFIRMED", decision.rejection_reasons)
        self.assertIn("SENTIMENT_TOO_WEAK", decision.rejection_reasons)

    def test_btc_futures_can_relax_caution_when_trend_and_edge_are_strong(self) -> None:
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.74,
            ret_rank_4h=0.72,
            breakout_norm=0.84,
            ema_stack_score=1.0,
            vol_z_5m_norm=0.72,
            vol_z_1h_norm=0.7,
            taker_imbalance_norm=0.64,
            spread_bps_norm=0.16,
            probe_slippage_bps_norm=0.18,
            depth_10bps_norm=0.88,
            book_stability_norm=0.92,
            realized_vol_1h_norm=0.24,
            realized_vol_4h_norm=0.22,
            vol_shock_norm=0.14,
            funding_abs_percentile=0.14,
            oi_surge_percentile=0.12,
            basis_stretch_percentile=0.12,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.86,
            volume_confirmation=0.82,
            liquidity_score=0.84,
            volatility_penalty=0.22,
            overheat_penalty=0.18,
            support_alignment=0.2,
            resistance_penalty=0.12,
            sentiment_regime="caution",
            sentiment_support_score=0.18,
            gross_expected_edge_bps=36.0,
            estimated_round_trip_cost_bps=12.0,
            net_expected_edge_bps=24.0,
        )
        snapshot = MarketSnapshot(
            snapshot_id="snap-btc-futures-caution-relax",
            config_version=settings.config_version,
            snapshot_schema_version=settings.snapshot_schema_version,
            symbol="BTCUSDT",
            decision_time=datetime(2026, 3, 16, 13, 2, tzinfo=timezone.utc),
            last_trade_price=50000.0,
            best_bid=49999.5,
            best_ask=50000.5,
            funding_rate=0.0001,
            open_interest=1000000.0,
            basis_bps=4.0,
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

        self.assertEqual(decision.final_mode, "futures")
        self.assertEqual(decision.entry_relaxation_reasons, ("SENTIMENT_CAUTION",))

    def test_btc_eth_relaxation_does_not_override_hard_guards(self) -> None:
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.62,
            ret_rank_4h=0.6,
            breakout_norm=0.62,
            ema_stack_score=0.95,
            vol_z_5m_norm=0.62,
            vol_z_1h_norm=0.6,
            taker_imbalance_norm=0.58,
            spread_bps_norm=0.16,
            probe_slippage_bps_norm=0.18,
            depth_10bps_norm=0.82,
            book_stability_norm=0.9,
            realized_vol_1h_norm=0.24,
            realized_vol_4h_norm=0.22,
            vol_shock_norm=0.14,
            funding_abs_percentile=0.12,
            oi_surge_percentile=0.12,
            basis_stretch_percentile=0.14,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.62,
            volume_confirmation=0.72,
            liquidity_score=0.68,
            volatility_penalty=0.22,
            overheat_penalty=0.16,
            support_alignment=0.29,
            resistance_penalty=0.72,
            sentiment_regime="neutral",
            sentiment_support_score=0.21,
            gross_expected_edge_bps=22.0,
            estimated_round_trip_cost_bps=10.0,
            net_expected_edge_bps=12.0,
        )
        snapshot = MarketSnapshot(
            snapshot_id="snap-eth-hard-guard",
            config_version=settings.config_version,
            snapshot_schema_version=settings.snapshot_schema_version,
            symbol="ETHUSDT",
            decision_time=datetime(2026, 3, 16, 13, 3, tzinfo=timezone.utc),
            last_trade_price=3000.0,
            best_bid=2999.5,
            best_ask=3000.5,
            funding_rate=0.0001,
            open_interest=1000000.0,
            basis_bps=3.0,
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

        self.assertEqual(decision.final_mode, "cash")
        self.assertIn("BUYING_INTO_RESISTANCE", decision.rejection_reasons)

    def test_btc_strong_futures_gets_capped_size_boost_but_alt_does_not(self) -> None:
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.76,
            ret_rank_4h=0.74,
            breakout_norm=0.86,
            ema_stack_score=1.0,
            vol_z_5m_norm=0.72,
            vol_z_1h_norm=0.7,
            taker_imbalance_norm=0.66,
            spread_bps_norm=0.16,
            probe_slippage_bps_norm=0.18,
            depth_10bps_norm=0.9,
            book_stability_norm=0.94,
            realized_vol_1h_norm=0.22,
            realized_vol_4h_norm=0.2,
            vol_shock_norm=0.12,
            funding_abs_percentile=0.12,
            oi_surge_percentile=0.12,
            basis_stretch_percentile=0.12,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.88,
            volume_confirmation=0.84,
            liquidity_score=0.86,
            volatility_penalty=0.2,
            overheat_penalty=0.16,
            support_alignment=0.24,
            resistance_penalty=0.12,
            sentiment_regime="neutral",
            sentiment_support_score=0.3,
            alt_market_regime="neutral",
            alt_breadth_score=0.7,
            alt_liquidity_support_score=0.9,
            alt_fundamental_score=0.64,
            alt_smart_money_score=0.64,
            alt_rotation_penalty=0.08,
            gross_expected_edge_bps=40.0,
            estimated_round_trip_cost_bps=12.0,
            net_expected_edge_bps=28.0,
        )

        def make(symbol: str) -> MarketSnapshot:
            return MarketSnapshot(
                snapshot_id=f"snap-{symbol}-boost",
                config_version=settings.config_version,
                snapshot_schema_version=settings.snapshot_schema_version,
                symbol=symbol,
                decision_time=datetime(2026, 3, 16, 13, 4, tzinfo=timezone.utc),
                last_trade_price=50000.0 if symbol == "BTCUSDT" else 120.0,
                best_bid=49999.5 if symbol == "BTCUSDT" else 119.95,
                best_ask=50000.5 if symbol == "BTCUSDT" else 120.05,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=4.0,
                data_freshness_ms=100,
                feature_values=features,
            )

        btc_decision = evaluate_snapshot(
            make("BTCUSDT"),
            settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=settings.cash_reserve.when_futures_enabled,
        )
        sol_decision = evaluate_snapshot(
            make("SOLUSDT"),
            settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=settings.cash_reserve.when_futures_enabled,
        )

        self.assertEqual(btc_decision.final_mode, "futures")
        self.assertEqual(sol_decision.final_mode, "futures")
        self.assertEqual(btc_decision.size_boost_reasons, ("BTC_ETH_STRONG_EDGE_SIZE_BOOST",))
        self.assertEqual(sol_decision.size_boost_reasons, ())
        self.assertGreater(btc_decision.strategy_size_multiplier, sol_decision.strategy_size_multiplier)
        self.assertGreater(btc_decision.order_intent_notional_usd, sol_decision.order_intent_notional_usd)

    def test_fee_thin_btc_futures_setup_does_not_get_size_boost(self) -> None:
        settings = Settings.load(CONFIG_PATH)
        features = FeatureVector(
            ret_rank_1h=0.76,
            ret_rank_4h=0.74,
            breakout_norm=0.86,
            ema_stack_score=1.0,
            vol_z_5m_norm=0.72,
            vol_z_1h_norm=0.7,
            taker_imbalance_norm=0.66,
            spread_bps_norm=0.16,
            probe_slippage_bps_norm=0.18,
            depth_10bps_norm=0.9,
            book_stability_norm=0.94,
            realized_vol_1h_norm=0.22,
            realized_vol_4h_norm=0.2,
            vol_shock_norm=0.12,
            funding_abs_percentile=0.12,
            oi_surge_percentile=0.12,
            basis_stretch_percentile=0.12,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.88,
            volume_confirmation=0.84,
            liquidity_score=0.86,
            volatility_penalty=0.2,
            overheat_penalty=0.16,
            support_alignment=0.24,
            resistance_penalty=0.12,
            sentiment_regime="neutral",
            sentiment_support_score=0.3,
            gross_expected_edge_bps=24.0,
            estimated_round_trip_cost_bps=16.0,
            net_expected_edge_bps=8.0,
        )
        snapshot = MarketSnapshot(
            snapshot_id="snap-btc-no-boost",
            config_version=settings.config_version,
            snapshot_schema_version=settings.snapshot_schema_version,
            symbol="BTCUSDT",
            decision_time=datetime(2026, 3, 16, 13, 5, tzinfo=timezone.utc),
            last_trade_price=50000.0,
            best_bid=49999.5,
            best_ask=50000.5,
            funding_rate=0.0001,
            open_interest=1000000.0,
            basis_bps=4.0,
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

        self.assertEqual(decision.final_mode, "futures")
        self.assertEqual(decision.size_boost_reasons, ())
        self.assertEqual(decision.strategy_size_multiplier, 1.0)

if __name__ == "__main__":
    unittest.main()
