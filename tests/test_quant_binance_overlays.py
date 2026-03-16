from __future__ import annotations

import os
import unittest
from pathlib import Path

from quant_binance.models import FeatureVector
from quant_binance.overlays import MacroInputs, apply_macro_overlay, apply_sentiment_overlay
from quant_binance.settings import Settings
from quant_binance.strategy.regime import evaluate_snapshot
from quant_binance.models import MarketSnapshot
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


def make_snapshot(features: FeatureVector) -> MarketSnapshot:
    return MarketSnapshot(
        snapshot_id="snap-overlay",
        config_version="2026-03-08.v1",
        snapshot_schema_version="1.0.0",
        symbol="BTCUSDT",
        decision_time=datetime(2026, 3, 9, 0, 0, tzinfo=timezone.utc),
        last_trade_price=50000.0,
        best_bid=49999.5,
        best_ask=50000.5,
        funding_rate=0.0001,
        open_interest=1000000.0,
        basis_bps=3.0,
        data_freshness_ms=100,
        feature_values=features,
    )


class QuantBinanceOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def test_macro_overlay_marks_high_risk(self) -> None:
        features = FeatureVector(
            ret_rank_1h=0.8, ret_rank_4h=0.8, breakout_norm=0.8, ema_stack_score=1.0,
            vol_z_5m_norm=0.7, vol_z_1h_norm=0.7, taker_imbalance_norm=0.7,
            spread_bps_norm=0.2, probe_slippage_bps_norm=0.2, depth_10bps_norm=0.8,
            book_stability_norm=0.8, realized_vol_1h_norm=0.3, realized_vol_4h_norm=0.3,
            vol_shock_norm=0.3, funding_abs_percentile=0.2, oi_surge_percentile=0.2,
            basis_stretch_percentile=0.2, regime_alignment=1.0, trend_direction=1,
            trend_strength=0.8, volume_confirmation=0.7, liquidity_score=0.8,
            volatility_penalty=0.3, overheat_penalty=0.2, gross_expected_edge_bps=30.0,
            estimated_round_trip_cost_bps=10.0
        )
        macro = MacroInputs(
            truflation_yoy=3.0,
            us10y_yield=4.8,
            oil_momentum_pct=15.0,
            tga_drain_score=0.1,
            fed_balance_sheet_30d_pct=-0.1,
            mmf_30d_pct=0.2,
            labor_stress_score=0.8,
            event_risk_score=1.0,
            btc_safe_haven_score=0.0,
        )
        enriched = apply_macro_overlay(features, macro)
        self.assertEqual(enriched.macro_regime, "high_risk")
        self.assertGreaterEqual(enriched.macro_risk_penalty, 0.65)
        self.assertEqual(enriched.macro_trade_restraint, "halt_high_impact_window")
        self.assertEqual(enriched.macro_symbol_bias, "majors_only")
        self.assertEqual(enriched.macro_leverage_cap, 1)

    def test_macro_overlay_marks_supportive_when_dollar_and_rates_fall(self) -> None:
        features = FeatureVector(
            ret_rank_1h=0.8, ret_rank_4h=0.8, breakout_norm=0.8, ema_stack_score=1.0,
            vol_z_5m_norm=0.7, vol_z_1h_norm=0.7, taker_imbalance_norm=0.7,
            spread_bps_norm=0.2, probe_slippage_bps_norm=0.2, depth_10bps_norm=0.8,
            book_stability_norm=0.8, realized_vol_1h_norm=0.3, realized_vol_4h_norm=0.3,
            vol_shock_norm=0.3, funding_abs_percentile=0.2, oi_surge_percentile=0.2,
            basis_stretch_percentile=0.2, regime_alignment=1.0, trend_direction=1,
            trend_strength=0.8, volume_confirmation=0.7, liquidity_score=0.8,
            volatility_penalty=0.3, overheat_penalty=0.2, gross_expected_edge_bps=30.0,
            estimated_round_trip_cost_bps=10.0
        )
        macro = MacroInputs(
            truflation_yoy=1.9,
            us10y_yield=4.1,
            oil_momentum_pct=1.0,
            tga_drain_score=0.7,
            fed_balance_sheet_30d_pct=0.4,
            mmf_30d_pct=-0.2,
            labor_stress_score=0.3,
            us10y_change_30d_bps=-35.0,
            dxy_change_30d_pct=-2.0,
            fed_liquidity_score=0.8,
            policy_easing_score=0.75,
            event_risk_score=0.2,
            btc_safe_haven_score=0.65,
        )
        enriched = apply_macro_overlay(features, macro)
        self.assertEqual(enriched.macro_regime, "supportive")
        self.assertGreater(enriched.macro_liquidity_support_score, 0.7)
        self.assertEqual(enriched.macro_trade_restraint, "none")
        self.assertEqual(enriched.macro_symbol_bias, "neutral")

    def test_sentiment_overlay_marks_bottoming(self) -> None:
        features = FeatureVector(
            ret_rank_1h=0.8, ret_rank_4h=0.8, breakout_norm=0.8, ema_stack_score=1.0,
            vol_z_5m_norm=0.7, vol_z_1h_norm=0.7, taker_imbalance_norm=0.7,
            spread_bps_norm=0.2, probe_slippage_bps_norm=0.2, depth_10bps_norm=0.8,
            book_stability_norm=0.8, realized_vol_1h_norm=0.3, realized_vol_4h_norm=0.3,
            vol_shock_norm=0.3, funding_abs_percentile=0.2, oi_surge_percentile=0.2,
            basis_stretch_percentile=0.2, regime_alignment=1.0, trend_direction=1,
            trend_strength=0.8, volume_confirmation=0.7, liquidity_score=0.8,
            volatility_penalty=0.3, overheat_penalty=0.2, support_alignment=0.8,
            resistance_penalty=0.0, gross_expected_edge_bps=30.0, estimated_round_trip_cost_bps=10.0
        )
        enriched = apply_sentiment_overlay(features)
        self.assertIn(enriched.sentiment_regime, {"bottoming", "risk_on"})
        self.assertGreater(enriched.sentiment_support_score, 0.5)

    def test_macro_high_risk_blocks_futures(self) -> None:
        features = FeatureVector(
            ret_rank_1h=0.8, ret_rank_4h=0.8, breakout_norm=0.8, ema_stack_score=1.0,
            vol_z_5m_norm=0.7, vol_z_1h_norm=0.7, taker_imbalance_norm=0.7,
            spread_bps_norm=0.2, probe_slippage_bps_norm=0.2, depth_10bps_norm=0.8,
            book_stability_norm=0.8, realized_vol_1h_norm=0.3, realized_vol_4h_norm=0.3,
            vol_shock_norm=0.3, funding_abs_percentile=0.2, oi_surge_percentile=0.2,
            basis_stretch_percentile=0.2, regime_alignment=1.0, trend_direction=1,
            trend_strength=0.8, volume_confirmation=0.7, liquidity_score=0.8,
            volatility_penalty=0.3, overheat_penalty=0.2, macro_regime="high_risk",
            macro_risk_penalty=0.8, sentiment_regime="risk_on", sentiment_support_score=0.8,
            support_alignment=0.8, resistance_penalty=0.0,
            gross_expected_edge_bps=30.0, estimated_round_trip_cost_bps=10.0
        )
        decision = evaluate_snapshot(
            make_snapshot(features),
            settings=self.settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            cash_reserve_fraction=0.15,
        )
        self.assertNotEqual(decision.final_mode, "futures")


if __name__ == "__main__":
    unittest.main()
