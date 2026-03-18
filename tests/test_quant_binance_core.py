from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from quant_binance.models import FeatureVector, MarketSnapshot
from quant_binance.execution.paper_broker import PaperBroker
from quant_binance.observability.decision_log import hash_decision_payload, render_audit_report, render_outcome_audit_report, render_prediction_report
from quant_binance.observability.manifest import build_manifest_entry, write_manifest
from quant_binance.observability.report import build_auto_tune_policy, build_persisted_policy_state, build_policy_validation, build_promotion_verdict, build_runtime_summary
from quant_binance.policy.portfolio import build_portfolio_intent, decision_from_portfolio_intent
from quant_binance.risk.sizing import position_notional_and_stop_bps, quantity_from_notional
from quant_binance.snapshots import validate_snapshot
from quant_binance.settings import Settings
from quant_binance.strategy.regime import build_strategy_prediction, evaluate_snapshot
from quant_binance.strategy.scorer import apply_score_and_costs, compute_predictability_score


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


def make_snapshot(symbol: str, features: FeatureVector) -> MarketSnapshot:
    return MarketSnapshot(
        snapshot_id=f"snapshot-{symbol}",
        config_version="2026-03-10.v1",
        snapshot_schema_version="1.0.0",
        symbol=symbol,
        decision_time=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
        last_trade_price=50000.0,
        best_bid=49999.5,
        best_ask=50000.5,
        funding_rate=0.0001,
        open_interest=1000000.0,
        basis_bps=4.5,
        data_freshness_ms=250,
        feature_values=features,
    )


class QuantBinanceCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def test_settings_load_versions_and_fees(self) -> None:
        self.assertEqual(self.settings.config_version, "2026-03-10.v1")
        self.assertEqual(self.settings.snapshot_schema_version, "1.0.0")
        self.assertEqual(self.settings.decision_engine.decision_interval_minutes, 5)
        self.assertEqual(self.settings.fees.futures_taker_fee_bps, 4)

    def test_predictability_score_matches_expected_formula(self) -> None:
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
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.74,
            liquidity_score=0.86,
            volatility_penalty=0.28,
            overheat_penalty=0.14,
            gross_expected_edge_bps=24.0,
        )
        score = compute_predictability_score(features, self.settings)
        self.assertAlmostEqual(score, 82.2, places=6)

    def test_apply_score_and_costs_uses_empirical_cost_overrides(self) -> None:
        features = FeatureVector(
            ret_rank_1h=0.8,
            ret_rank_4h=0.78,
            breakout_norm=0.82,
            ema_stack_score=1.0,
            vol_z_5m_norm=0.7,
            vol_z_1h_norm=0.72,
            taker_imbalance_norm=0.69,
            spread_bps_norm=0.2,
            probe_slippage_bps_norm=0.05,
            depth_10bps_norm=0.86,
            book_stability_norm=0.9,
            realized_vol_1h_norm=0.3,
            realized_vol_4h_norm=0.28,
            vol_shock_norm=0.35,
            funding_abs_percentile=0.14,
            oi_surge_percentile=0.1,
            basis_stretch_percentile=0.18,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.74,
            liquidity_score=0.86,
            volatility_penalty=0.28,
            overheat_penalty=0.14,
            gross_expected_edge_bps=24.0,
            empirical_fee_bps=5.0,
            empirical_entry_slippage_bps=7.5,
            empirical_exit_slippage_bps=7.5,
        )
        adjusted = apply_score_and_costs(features, self.settings, "futures")
        self.assertGreaterEqual(adjusted.estimated_round_trip_cost_bps, 25.0)

    def test_futures_mode_for_high_confidence_long(self) -> None:
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
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.74,
            liquidity_score=0.86,
            volatility_penalty=0.28,
            overheat_penalty=0.14,
            gross_expected_edge_bps=24.0,
            estimated_round_trip_cost_bps=10.0,
        )
        decision = evaluate_snapshot(
            make_snapshot("BTCUSDT", features),
            self.settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            expected_funding_drag_bps=2.0,
        )
        self.assertEqual(decision.final_mode, "futures")
        self.assertEqual(decision.side, "long")
        self.assertEqual(decision.candidate_mode, "futures")

    def test_overheat_downgrades_to_spot(self) -> None:
        features = FeatureVector(
            ret_rank_1h=0.78,
            ret_rank_4h=0.77,
            breakout_norm=0.8,
            ema_stack_score=1.0,
            vol_z_5m_norm=0.73,
            vol_z_1h_norm=0.7,
            taker_imbalance_norm=0.7,
            spread_bps_norm=0.25,
            probe_slippage_bps_norm=0.26,
            depth_10bps_norm=0.76,
            book_stability_norm=0.85,
            realized_vol_1h_norm=0.34,
            realized_vol_4h_norm=0.33,
            vol_shock_norm=0.35,
            funding_abs_percentile=0.9,
            oi_surge_percentile=0.7,
            basis_stretch_percentile=0.4,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.81,
            volume_confirmation=0.72,
            liquidity_score=0.76,
            volatility_penalty=0.34,
            overheat_penalty=0.67,
            support_alignment=0.8,
            resistance_penalty=0.0,
            sentiment_regime="bottoming",
            sentiment_support_score=0.8,
            gross_expected_edge_bps=22.0,
            estimated_round_trip_cost_bps=10.0,
        )
        decision = evaluate_snapshot(
            make_snapshot("ETHUSDT", features),
            self.settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            expected_funding_drag_bps=5.0,
        )
        self.assertEqual(decision.candidate_mode, "futures")
        self.assertEqual(decision.final_mode, "spot")
        self.assertIn("FUTURES_OVERHEAT", decision.rejection_reasons)

    def test_cash_for_low_confidence_signal(self) -> None:
        features = FeatureVector(
            ret_rank_1h=0.41,
            ret_rank_4h=0.4,
            breakout_norm=0.38,
            ema_stack_score=0.0,
            vol_z_5m_norm=0.47,
            vol_z_1h_norm=0.46,
            taker_imbalance_norm=0.48,
            spread_bps_norm=0.5,
            probe_slippage_bps_norm=0.55,
            depth_10bps_norm=0.52,
            book_stability_norm=0.5,
            realized_vol_1h_norm=0.72,
            realized_vol_4h_norm=0.7,
            vol_shock_norm=0.73,
            funding_abs_percentile=0.44,
            oi_surge_percentile=0.42,
            basis_stretch_percentile=0.41,
            regime_alignment=0.0,
            trend_direction=0,
            trend_strength=0.41,
            volume_confirmation=0.47,
            liquidity_score=0.52,
            volatility_penalty=0.72,
            overheat_penalty=0.44,
            gross_expected_edge_bps=11.0,
            estimated_round_trip_cost_bps=10.0,
        )
        decision = evaluate_snapshot(
            make_snapshot("SOLUSDT", features),
            self.settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        self.assertEqual(decision.final_mode, "cash")
        self.assertEqual(decision.side, "flat")

    def test_low_liquidity_alt_becomes_observe_only(self) -> None:
        features = FeatureVector(
            ret_rank_1h=0.5,
            ret_rank_4h=0.48,
            breakout_norm=0.4,
            ema_stack_score=0.5,
            vol_z_5m_norm=0.45,
            vol_z_1h_norm=0.44,
            taker_imbalance_norm=0.5,
            spread_bps_norm=0.9,
            probe_slippage_bps_norm=0.95,
            depth_10bps_norm=0.1,
            book_stability_norm=0.3,
            realized_vol_1h_norm=0.45,
            realized_vol_4h_norm=0.4,
            vol_shock_norm=0.3,
            funding_abs_percentile=0.2,
            oi_surge_percentile=0.2,
            basis_stretch_percentile=0.2,
            regime_alignment=0.5,
            trend_direction=0,
            trend_strength=0.45,
            volume_confirmation=0.45,
            liquidity_score=0.2,
            volatility_penalty=0.4,
            overheat_penalty=0.2,
            alt_liquidity_support_score=0.2,
            gross_expected_edge_bps=8.0,
            estimated_round_trip_cost_bps=56.0,
        )
        decision = evaluate_snapshot(
            make_snapshot("SIGNUSDT", features),
            self.settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        self.assertEqual(decision.final_mode, "cash")
        self.assertIn("OBSERVE_ONLY_SYMBOL", decision.rejection_reasons)

    def test_sizing_respects_symbol_cap(self) -> None:
        notional, stop_distance_bps = position_notional_and_stop_bps(
            last_trade_price=50000.0,
            atr_14_1h_bps=25.0,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=1500.0,
            settings=self.settings,
        )
        self.assertEqual(stop_distance_bps, 45.0)
        self.assertEqual(notional, 1500.0)
        self.assertAlmostEqual(quantity_from_notional(notional, 50000.0), 0.03)

    def test_decision_hash_stable_for_same_payload(self) -> None:
        payload = {"final_mode": "spot", "predictability_score": 61.2, "snapshot_id": "snap-1"}
        self.assertEqual(hash_decision_payload(payload), hash_decision_payload(payload))

    def test_audit_report_contains_required_keys(self) -> None:
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
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.74,
            liquidity_score=0.86,
            volatility_penalty=0.28,
            overheat_penalty=0.14,
            gross_expected_edge_bps=24.0,
            estimated_round_trip_cost_bps=10.0,
        )
        decision = evaluate_snapshot(
            make_snapshot("BTCUSDT", features),
            self.settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            expected_funding_drag_bps=2.0,
        )
        report = render_audit_report(decision)
        self.assertIn("decision_hash", report)
        self.assertIn("gross_expected_edge_bps", report)
        self.assertIn("linked_order_ids", report)

    def test_major_candidate_mode_prefers_futures_for_btc_eth_edge_advantage(self) -> None:
        features = FeatureVector(
            ret_rank_1h=0.7,
            ret_rank_4h=0.68,
            breakout_norm=0.75,
            ema_stack_score=1.0,
            vol_z_5m_norm=0.65,
            vol_z_1h_norm=0.66,
            taker_imbalance_norm=0.63,
            spread_bps_norm=0.22,
            probe_slippage_bps_norm=0.24,
            depth_10bps_norm=0.84,
            book_stability_norm=0.87,
            realized_vol_1h_norm=0.29,
            realized_vol_4h_norm=0.27,
            vol_shock_norm=0.24,
            funding_abs_percentile=0.12,
            oi_surge_percentile=0.1,
            basis_stretch_percentile=0.16,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.76,
            volume_confirmation=0.71,
            liquidity_score=0.83,
            volatility_penalty=0.26,
            overheat_penalty=0.16,
            gross_expected_edge_bps=16.0,
            estimated_round_trip_cost_bps=8.0,
            macro_regime="supportive",
            macro_trade_restraint="none",
            macro_symbol_bias="majors_only",
        )
        prediction = build_strategy_prediction(make_snapshot("ETHUSDT", features), self.settings, expected_funding_drag_bps=2.0)
        self.assertEqual(prediction.candidate_mode, "futures")
        self.assertEqual(prediction.selected_mode_hint, "futures")

    def test_major_prediction_bias_prefers_btc_eth_when_macro_is_majors_only(self) -> None:
        major_features = FeatureVector(
            ret_rank_1h=0.74,
            ret_rank_4h=0.72,
            breakout_norm=0.76,
            ema_stack_score=1.0,
            vol_z_5m_norm=0.68,
            vol_z_1h_norm=0.7,
            taker_imbalance_norm=0.66,
            spread_bps_norm=0.2,
            probe_slippage_bps_norm=0.22,
            depth_10bps_norm=0.84,
            book_stability_norm=0.88,
            realized_vol_1h_norm=0.3,
            realized_vol_4h_norm=0.28,
            vol_shock_norm=0.24,
            funding_abs_percentile=0.14,
            oi_surge_percentile=0.1,
            basis_stretch_percentile=0.18,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.78,
            volume_confirmation=0.72,
            liquidity_score=0.82,
            volatility_penalty=0.28,
            overheat_penalty=0.18,
            gross_expected_edge_bps=20.0,
            estimated_round_trip_cost_bps=8.0,
            macro_regime="supportive",
            macro_trade_restraint="none",
            macro_symbol_bias="majors_only",
        )
        alt_features = replace(major_features)
        major_prediction = build_strategy_prediction(make_snapshot("BTCUSDT", major_features), self.settings, expected_funding_drag_bps=2.0)
        alt_prediction = build_strategy_prediction(make_snapshot("SOLUSDT", alt_features), self.settings, expected_funding_drag_bps=2.0)
        self.assertGreater(major_prediction.futures.predictability_score, alt_prediction.futures.predictability_score)
        self.assertGreater(major_prediction.futures.net_expected_edge_bps, alt_prediction.futures.net_expected_edge_bps)

    def test_strategy_prediction_builds_per_mode_view(self) -> None:
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
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.74,
            liquidity_score=0.86,
            volatility_penalty=0.28,
            overheat_penalty=0.14,
            gross_expected_edge_bps=24.0,
            estimated_round_trip_cost_bps=10.0,
        )
        prediction = build_strategy_prediction(
            make_snapshot("BTCUSDT", features),
            self.settings,
            expected_funding_drag_bps=2.0,
        )
        self.assertEqual(prediction.symbol, "BTCUSDT")
        self.assertEqual(prediction.candidate_mode, "futures")
        self.assertEqual(prediction.futures.mode, "futures")
        self.assertEqual(prediction.spot.mode, "spot")
        self.assertGreaterEqual(prediction.futures.predictability_score, prediction.spot.predictability_score)
        self.assertEqual(prediction.futures.side, "long")
        self.assertEqual(prediction.spot.side, "long")

    def test_major_prediction_specialist_adjustment_boosts_btc_eth_futures_over_alt(self) -> None:
        major_features = FeatureVector(
            ret_rank_1h=0.82, ret_rank_4h=0.8, breakout_norm=0.84, ema_stack_score=1.0,
            vol_z_5m_norm=0.72, vol_z_1h_norm=0.74, taker_imbalance_norm=0.7,
            spread_bps_norm=0.18, probe_slippage_bps_norm=0.22, depth_10bps_norm=0.9, book_stability_norm=0.92,
            realized_vol_1h_norm=0.28, realized_vol_4h_norm=0.26, vol_shock_norm=0.22,
            funding_abs_percentile=0.12, oi_surge_percentile=0.1, basis_stretch_percentile=0.14, regime_alignment=1.0,
            trend_direction=1, trend_strength=0.8, volume_confirmation=0.72, liquidity_score=0.86, volatility_penalty=0.24, overheat_penalty=0.12,
            gross_expected_edge_bps=22.0, estimated_round_trip_cost_bps=9.0, macro_regime="supportive", macro_trade_restraint="none", macro_symbol_bias="majors_only",
        )
        alt_features = replace(major_features, macro_symbol_bias="neutral")
        major_prediction = build_strategy_prediction(make_snapshot("BTCUSDT", major_features), self.settings, expected_funding_drag_bps=2.0)
        alt_prediction = build_strategy_prediction(make_snapshot("SOLUSDT", alt_features), self.settings, expected_funding_drag_bps=2.0)
        self.assertGreater(major_prediction.futures.net_expected_edge_bps, alt_prediction.futures.net_expected_edge_bps)
        self.assertGreater(major_prediction.futures.predictability_score, alt_prediction.futures.predictability_score)

    def test_render_prediction_report_includes_mode_edges(self) -> None:
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
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.74,
            liquidity_score=0.86,
            volatility_penalty=0.28,
            overheat_penalty=0.14,
            gross_expected_edge_bps=24.0,
            estimated_round_trip_cost_bps=10.0,
        )
        prediction = build_strategy_prediction(make_snapshot("BTCUSDT", features), self.settings, expected_funding_drag_bps=2.0)
        report = render_prediction_report(prediction)
        self.assertIn("futures_net_expected_edge_bps", report)
        self.assertIn("spot_net_expected_edge_bps", report)

    def test_render_outcome_audit_report_includes_edge_gap(self) -> None:
        report = render_outcome_audit_report(
            {
                "timestamp": datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
                "symbol": "BTCUSDT",
                "market": "futures",
                "side": "long",
                "accepted": True,
                "fill_ratio": 0.95,
                "fill_status": "partial",
                "avg_fill_price": 50100.0,
                "slippage_bps": 3.0,
                "expected_net_edge_bps": 18.5,
                "realized_edge_bps": 11.0,
            }
        )
        self.assertIn("expected_net_edge_bps", report)
        self.assertIn("realized_vs_expected_edge_gap_bps", report)

    def test_runtime_summary_aggregates_execution_outcomes(self) -> None:
        decision = evaluate_snapshot(
            make_snapshot(
                "BTCUSDT",
                FeatureVector(
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
                    trend_direction=1,
                    trend_strength=0.82,
                    volume_confirmation=0.74,
                    liquidity_score=0.86,
                    volatility_penalty=0.28,
                    overheat_penalty=0.14,
                    gross_expected_edge_bps=24.0,
                    estimated_round_trip_cost_bps=10.0,
                ),
            ),
            self.settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            expected_funding_drag_bps=2.0,
        )
        summary = build_runtime_summary(
            decisions=[decision],
            live_orders=[
                {
                    "symbol": "BTCUSDT",
                    "accepted": True,
                    "fill_status": "filled",
                    "fill_ratio": 1.0,
                    "slippage_bps": 2.0,
                    "expected_net_edge_bps": 18.0,
                    "realized_edge_bps": 12.0,
                },
                {
                    "symbol": "ETHUSDT",
                    "accepted": False,
                    "fill_status": "reject",
                    "fill_ratio": 0.0,
                    "slippage_bps": 0.0,
                    "expected_net_edge_bps": 9.0,
                    "realized_edge_bps": 0.0,
                    "protection_error": "timeout",
                },
            ],
        )
        self.assertEqual(summary["accepted_live_order_count"], 1)
        self.assertEqual(summary["rejected_live_order_count"], 1)
        self.assertIn("filled", summary["execution_outcome_counts"])
        self.assertIn("reject", summary["execution_outcome_counts"])
        self.assertIn("avg_edge_retention_ratio", summary)
        self.assertEqual(summary["protection_degraded_count"], 1)
        self.assertIn("realized_vs_expected_edge_gap_bps", summary)
        self.assertEqual(len(summary["execution_audit_by_symbol"]), 2)

    def test_runtime_summary_includes_attribution_candidate_policy_and_promotion_verdict(self) -> None:
        summary = build_runtime_summary(
            decisions=[],
            live_orders=[
                {"symbol": "BTCUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.96, "expected_net_edge_bps": 15.0, "realized_edge_bps": 13.0},
                {"symbol": "BTCUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.95, "expected_net_edge_bps": 16.0, "realized_edge_bps": 13.2},
                {"symbol": "BTCUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.97, "expected_net_edge_bps": 15.0, "realized_edge_bps": 12.0},
                {"symbol": "ETHUSDT", "side": "short", "accepted": False, "fill_status": "reject", "fill_ratio": 0.0, "expected_net_edge_bps": 12.0, "realized_edge_bps": 0.0, "protection_error": "timeout"},
                {"symbol": "ETHUSDT", "side": "short", "accepted": False, "fill_status": "reject", "fill_ratio": 0.0, "expected_net_edge_bps": 11.0, "realized_edge_bps": 0.0, "protection_error": "timeout"},
                {"symbol": "ETHUSDT", "side": "short", "accepted": True, "fill_status": "filled", "fill_ratio": 0.7, "expected_net_edge_bps": 10.0, "realized_edge_bps": 2.0, "protection_error": "timeout"},
            ],
        )
        self.assertTrue(summary["performance_attribution"])
        self.assertEqual(summary["candidate_policy"]["status"], "candidate_ready")
        actions = {item["symbol"] + ":" + item["action"] for item in summary["candidate_policy"]["adjustments"]}
        self.assertIn("BTCUSDT:promote", actions)
        promoted = next(item for item in summary["candidate_policy"]["adjustments"] if item["symbol"] == "BTCUSDT")
        self.assertEqual(promoted["symbol_bias"], "majors_only")
        self.assertIn("ETHUSDT:demote", actions)
        self.assertEqual(summary["promotion_verdict"]["status"], "keep")
        self.assertEqual(summary["policy_state"]["status"], "keep")
        self.assertIn(summary["policy_validation"]["status"], {"pass", "pending", "fail"})

    def test_build_promotion_verdict_blocks_promotion_when_candidate_underperforms_current(self) -> None:
        verdict = build_promotion_verdict(
            {
                "adjustments": [
                    {"symbol": "BTCUSDT", "action": "promote"},
                ]
            },
            {
                "comparison_verdict": "candidate_worse",
                "candidate_vs_current_score_delta": -0.35,
            },
        )
        self.assertEqual(verdict["status"], "keep")
        self.assertIn("PROMOTION_BLOCKED_BY_POLICY_COMPARISON", verdict["reasons"])
        self.assertEqual(verdict["comparison_verdict"], "candidate_worse")

    def test_build_promotion_verdict_blocks_promotion_when_micro_live_gate_is_pending(self) -> None:
        verdict = build_promotion_verdict(
            {
                "adjustments": [
                    {"symbol": "BTCUSDT", "action": "promote"},
                ]
            },
            {
                "comparison_verdict": "candidate_better",
                "candidate_vs_current_score_delta": 0.2,
                "runner_total_realized_pnl_usd": 5.0,
                "runner_drawdown_to_pnl_ratio": 0.2,
                "runner_reject_rate": 0.01,
                "runner_avg_slippage_bps": 2.0,
                "runner_avg_edge_retention_ratio": 0.8,
                "micro_live_gate": {"available": True, "status": "pending"},
            },
        )
        self.assertEqual(verdict["status"], "keep")
        self.assertIn("PROMOTION_BLOCKED_BY_MICRO_LIVE_GATE", verdict["reasons"])

    def test_build_policy_validation_marks_warmup_as_pending_instead_of_fail(self) -> None:
        validation = build_policy_validation(
            {"adjustments": [{"symbol": "BTCUSDT", "action": "promote"}]},
            {"status": "keep", "requested_status": "promote", "rollout_stage": "staged_rollout"},
            {"status": "hold", "reasons": ["INSUFFICIENT_SAMPLE"]},
            (),
            {
                "candidate_vs_current_score_delta": 0.2,
                "runner_total_realized_pnl_usd": 5.0,
                "runner_max_drawdown_pct": 20.0,
                "runner_shadow_alignment_score": 0.8,
                "runner_drawdown_to_pnl_ratio": 0.2,
                "runner_reject_rate": 0.01,
                "runner_avg_slippage_bps": 2.0,
                "runner_avg_edge_retention_ratio": 0.8,
                "micro_live_gate": {"available": True, "status": "pending", "reason": "MICRO_LIVE_THRESHOLD_NOT_MET"},
            },
        )
        self.assertEqual(validation["status"], "pending")
        self.assertIn("PROMOTION_STAGED_PENDING_MICRO_LIVE", validation["reasons"])
        self.assertIn("CANDIDATE_OUTPERFORMS_CURRENT_POLICY", validation["reasons"])

    def test_build_promotion_verdict_blocks_promotion_when_walk_forward_is_weak(self) -> None:
        verdict = build_promotion_verdict(
            {
                "adjustments": [
                    {"symbol": "BTCUSDT", "action": "promote"},
                ]
            },
            {
                "comparison_verdict": "candidate_better",
                "candidate_vs_current_score_delta": 0.2,
                "runner_total_realized_pnl_usd": 5.0,
                "runner_drawdown_to_pnl_ratio": 0.2,
                "runner_reject_rate": 0.01,
                "runner_avg_slippage_bps": 2.0,
                "runner_avg_edge_retention_ratio": 0.8,
                "runner_walk_forward_window_count": 3,
                "runner_positive_walk_forward_ratio": 0.333333,
                "micro_live_gate": {"available": True, "status": "pass"},
            },
        )
        self.assertEqual(verdict["status"], "keep")
        self.assertIn("PROMOTION_BLOCKED_BY_WALK_FORWARD", verdict["reasons"])

    def test_build_persisted_policy_state_persists_disable_verdict(self) -> None:
        state = build_persisted_policy_state(
            {
                "version": 2,
                "active_policy": {
                    "status": "promote",
                    "adjustments": [{"symbol": "ETHUSDT", "action": "promote", "size_multiplier": 1.1}],
                },
            },
            {
                "adjustments": [
                    {"symbol": "BTCUSDT", "action": "demote", "size_multiplier": 0.75, "leverage_multiplier": 0.75},
                ],
            },
            {"status": "disable", "reasons": ["CANDIDATE_POLICY_UNSTABLE"]},
            {"status": "hold", "reasons": []},
            {"status": "pass", "evidence": {"comparison_verdict": "keep"}},
        )
        self.assertEqual(state["status"], "disabled")
        self.assertEqual(state["version"], 3)
        self.assertEqual(state["active_policy"]["status"], "disabled")
        self.assertEqual(state["active_policy"]["adjustments"][0]["action"], "disabled")
        self.assertEqual(state["active_policy"]["adjustments"][0]["size_multiplier"], 0.0)

    def test_build_persisted_policy_state_marks_staged_when_micro_live_gate_pending(self) -> None:
        state = build_persisted_policy_state(
            {"version": 1, "active_policy": {"status": "baseline", "adjustments": []}},
            {"adjustments": [{"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.1}]},
            {"status": "promote", "reasons": ["CANDIDATE_POLICY_STRONG", "PROMOTION_BLOCKED_BY_MICRO_LIVE_GATE"]},
            {"status": "pass", "reasons": []},
            {"status": "pass", "evidence": {"micro_live_gate": {"available": True, "status": "pending", "reason": "MICRO_LIVE_THRESHOLD_NOT_MET", "live_order_count": 2, "closed_trade_count": 0, "required_live_order_count": 2, "required_closed_trade_count": 1}}},
        )
        self.assertEqual(state["status"], "staged_rollout")
        self.assertEqual(state["rollout_status"], "micro_live_pending")
        self.assertEqual(state["retention_monitor"]["status"], "armed")
        self.assertEqual(state["rollout_progression"]["phase"], "staged_rollout")
        self.assertEqual(state["rollout_progression"]["status"], "collecting_micro_live_outcomes")
        self.assertEqual(state["rollout_progression"]["execution_phase"], "partial")

    def test_build_persisted_policy_state_rolls_back_after_post_promotion_retention_degrades(self) -> None:
        previous_active = {"status": "promote", "adjustments": [{"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.1}]}
        state = build_persisted_policy_state(
            {"version": 3, "active_policy": previous_active, "rollout_status": "ready"},
            {"adjustments": [{"symbol": "BTCUSDT", "action": "keep", "size_multiplier": 1.0}]},
            {"status": "keep", "reasons": ["CANDIDATE_POLICY_MIXED"]},
            {"status": "pass", "reasons": []},
            {"status": "fail", "evidence": {"runner_avg_edge_retention_ratio": 0.3, "runner_drawdown_to_pnl_ratio": 0.9, "runner_reject_rate": 0.25}},
        )
        self.assertEqual(state["status"], "rolled_back")
        self.assertEqual(state["rollout_reason"], "POST_PROMOTION_RETENTION_DEGRADED")
        self.assertEqual(state["retention_monitor"]["status"], "rollback")
        self.assertEqual(state["active_policy"]["status"], "baseline")
        self.assertEqual(state["rollout_progression"]["status"], "rollback_triggered")
        self.assertEqual(state["rollout_progression"]["execution_phase"], "rollback")

    def test_build_persisted_policy_state_demotes_on_walk_forward_weakness(self) -> None:
        previous_active = {"status": "promote", "adjustments": [{"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.1}]}
        state = build_persisted_policy_state(
            {"version": 3, "active_policy": previous_active, "rollout_status": "ready"},
            {"adjustments": [{"symbol": "BTCUSDT", "action": "keep", "size_multiplier": 1.0}]},
            {"status": "keep", "reasons": ["CANDIDATE_POLICY_MIXED"]},
            {"status": "pass", "reasons": []},
            {
                "status": "fail",
                "evidence": {
                    "runner_total_realized_pnl_usd": 3.0,
                    "runner_avg_edge_retention_ratio": 0.7,
                    "runner_drawdown_to_pnl_ratio": 0.2,
                    "runner_reject_rate": 0.03,
                    "runner_avg_slippage_bps": 4.0,
                    "runner_walk_forward_window_count": 3,
                    "runner_positive_walk_forward_ratio": 0.45,
                },
            },
        )
        self.assertEqual(state["status"], "retention_demoted")
        self.assertEqual(state["retention_monitor"]["status"], "demote")
        self.assertIn("RETENTION_MONITOR_WALK_FORWARD_WEAK", state["retention_monitor"]["reasons"])
        self.assertEqual(state["rollout_progression"]["status"], "demotion_watch")
        self.assertEqual(state["rollout_progression"]["execution_phase"], "watch")

    def test_build_persisted_policy_state_promotes_rollout_phase_to_full_when_evidence_is_broad(self) -> None:
        previous_active = {"status": "promote", "adjustments": [{"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.1}]}
        state = build_persisted_policy_state(
            {
                "version": 3,
                "rollout_status": "ready",
                "active_policy": previous_active,
                "rollout_progression": {"execution_phase": "partial"},
            },
            {"adjustments": [{"symbol": "BTCUSDT", "action": "keep", "size_multiplier": 1.0}]},
            {"status": "keep", "reasons": ["CANDIDATE_POLICY_MIXED"]},
            {"status": "pass", "reasons": []},
            {
                "status": "pass",
                "evidence": {
                    "runner_total_realized_pnl_usd": 9.0,
                    "runner_avg_edge_retention_ratio": 0.82,
                    "runner_drawdown_to_pnl_ratio": 0.22,
                    "runner_reject_rate": 0.02,
                    "micro_live_gate": {"available": True, "status": "pass", "live_order_count": 9, "closed_trade_count": 3, "required_live_order_count": 2, "required_closed_trade_count": 1},
                    "runner_walk_forward_window_count": 3,
                    "runner_positive_walk_forward_ratio": 1.0,
                },
            },
        )
        self.assertEqual(state["status"], "kept")
        self.assertEqual(state["rollout_progression"]["execution_phase"], "full")
        self.assertEqual(state["rollout_progression"]["execution_phase_reason"], "ROLLOUT_READY_FOR_FULL_COVERAGE")

    def test_build_persisted_policy_state_demotes_on_recent_windowed_retention_weakness(self) -> None:
        previous_active = {"status": "promote", "adjustments": [{"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.1}]}
        state = build_persisted_policy_state(
            {
                "version": 3,
                "rollout_status": "ready",
                "active_policy": previous_active,
                "retention_monitor": {
                    "status": "stable",
                    "metrics": {"recent_window": {"avg_edge_retention_ratio": 0.78, "drawdown_to_pnl_ratio": 0.18, "reject_rate": 0.02}},
                },
                "rollout_progression": {"execution_phase": "broad"},
            },
            {"adjustments": [{"symbol": "BTCUSDT", "action": "keep", "size_multiplier": 1.0}]},
            {"status": "keep", "reasons": ["CANDIDATE_POLICY_MIXED"]},
            {"status": "fail", "reasons": []},
            {
                "status": "fail",
                "evidence": {
                    "runner_total_realized_pnl_usd": 6.0,
                    "runner_avg_edge_retention_ratio": 0.72,
                    "runner_drawdown_to_pnl_ratio": 0.25,
                    "runner_reject_rate": 0.03,
                    "runner_avg_slippage_bps": 4.0,
                    "runner_walk_forward_window_count": 3,
                    "runner_positive_walk_forward_ratio": 0.67,
                    "micro_live_gate": {"available": True, "status": "pass", "live_order_count": 9, "closed_trade_count": 3, "required_live_order_count": 2, "required_closed_trade_count": 1},
                    "validation_runs": [
                        {"realized_pnl_usd": 2.0, "live_order_count": 3, "accepted_live_order_count": 3, "rejected_live_order_count": 0, "closed_trade_count": 1, "avg_edge_retention_ratio": 0.84, "avg_slippage_bps": 3.5},
                        {"realized_pnl_usd": 2.0, "live_order_count": 3, "accepted_live_order_count": 3, "rejected_live_order_count": 0, "closed_trade_count": 1, "avg_edge_retention_ratio": 0.39, "avg_slippage_bps": 4.2},
                        {"realized_pnl_usd": 1.0, "live_order_count": 3, "accepted_live_order_count": 2, "rejected_live_order_count": 1, "closed_trade_count": 1, "avg_edge_retention_ratio": 0.49, "avg_slippage_bps": 4.4},
                    ],
                    "walk_forward_windows": [
                        {"avg_net_edge_bps": 4.0, "avg_score": 60.0},
                        {"avg_net_edge_bps": -1.0, "avg_score": 45.0},
                        {"avg_net_edge_bps": 0.5, "avg_score": 47.0},
                    ],
                },
            },
        )
        self.assertEqual(state["status"], "retention_demoted")
        self.assertIn("RETENTION_MONITOR_RECENT_WINDOW_EDGE_WEAK", state["retention_monitor"]["reasons"])
        self.assertIn("RETENTION_MONITOR_RETENTION_TREND_NEGATIVE", state["retention_monitor"]["reasons"])
        self.assertEqual(state["retention_monitor"]["metrics"]["recent_window"]["run_count"], 3)
        self.assertEqual(state["rollout_progression"]["execution_phase"], "watch")

    def test_build_persisted_policy_state_rolls_back_on_candidate_underperformance(self) -> None:
        previous_active = {
            "status": "promote_aggressive",
            "adjustments": [{"symbol": "ETHUSDT", "action": "aggressive_promote", "size_multiplier": 1.25}],
        }
        state = build_persisted_policy_state(
            {
                "version": 4,
                "active_policy": previous_active,
            },
            {
                "adjustments": [
                    {"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.1, "leverage_multiplier": 1.1},
                ],
            },
            {"status": "promote", "reasons": ["CANDIDATE_POLICY_STRONG"]},
            {"status": "pass", "reasons": []},
            {
                "status": "fail",
                "evidence": {
                    "comparison_verdict": "candidate_worse",
                    "candidate_vs_current_score_delta": -0.25,
                    "replay_like_drawdown_ratio": 0.1,
                },
            },
        )
        self.assertEqual(state["status"], "rolled_back")
        self.assertEqual(state["version"], 5)
        self.assertEqual(state["active_policy"]["status"], "baseline")

    def test_build_auto_tune_policy_uses_runtime_symbol_and_regime_decomposition(self) -> None:
        policy = build_auto_tune_policy(
            [
                {
                    "symbol": "XRPUSDT",
                    "regime": "alt",
                    "setup_class": "standard_edge",
                    "side": "long",
                    "execution_quality_state": "healthy",
                    "sample_count": 3,
                    "avg_realized_edge_bps": 6.0,
                    "avg_edge_retention_ratio": 0.85,
                    "reject_rate": 0.0,
                    "protection_degraded_rate": 0.0,
                }
            ],
            {
                "symbol_summary": [
                    {"symbol": "BTCUSDT", "trade_count": 3, "expectancy_usd": 4.5, "recommendation": "promote"},
                    {"symbol": "SOLUSDT", "trade_count": 3, "expectancy_usd": -2.5, "recommendation": "prune"},
                ],
                "regime_summary": [
                    {"mode": "futures", "decision_count": 6, "avg_score": 70.0, "avg_net_edge_bps": 12.0, "avg_cost_bps": 8.0},
                ],
                "pruning_recommendations": [
                    {"symbol": "SOLUSDT", "recommendation": "prune", "decision_count": 4, "trade_count": 3, "avg_net_edge_bps": -1.5, "expectancy_usd": -2.5},
                ],
            },
        )
        adjustments = {item["symbol"]: item for item in policy["adjustments"]}
        self.assertEqual(policy["status"], "candidate_ready")
        self.assertEqual(adjustments["BTCUSDT"]["action"], "aggressive_promote")
        self.assertEqual(adjustments["BTCUSDT"]["symbol_bias"], "majors_only")
        self.assertEqual(adjustments["SOLUSDT"]["action"], "demote")
        self.assertEqual(adjustments["XRPUSDT"]["action"], "promote")
        self.assertIn("runtime_symbol_summary", adjustments["BTCUSDT"]["signal_sources"])
        self.assertIn("runtime_pruning_recommendation", adjustments["SOLUSDT"]["signal_sources"])
        self.assertGreater(adjustments["BTCUSDT"]["score_delta"], adjustments["XRPUSDT"]["score_delta"])
        self.assertEqual(adjustments["BTCUSDT"]["signal_contexts"]["runtime_symbol_summary"]["dominant_regime_mode"], "futures")
        self.assertEqual(policy["decomposition_summary"]["dominant_regime_mode"], "futures")
        self.assertNotEqual(policy["decomposition_summary"]["score_delta_total"], 0.0)

    def test_load_validation_runner_evidence_reads_report_metrics(self) -> None:
        import json
        import tempfile
        from quant_binance.observability.report import load_validation_runner_evidence, merge_policy_validation_evidence
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "policy_comparison.json"
            path.write_text(json.dumps({"evidence": {"runner_max_drawdown_pct": 12.5, "runner_shadow_alignment_score": 0.88, "runner_total_return_pct": 4.2, "candidate_vs_current_score_delta": 0.3}}), encoding="utf-8")
            evidence = load_validation_runner_evidence(Path(tmpdir))
            self.assertEqual(evidence["runner_max_drawdown_pct"], 12.5)
            merged = merge_policy_validation_evidence([], evidence)
            self.assertEqual(merged["runner_total_return_pct"], 4.2)
            self.assertEqual(merged["shadow_alignment_score"], 0.88)
            self.assertEqual(merged["candidate_vs_current_score_delta"], 0.3)

    def test_runtime_summary_operational_verdict_can_emit_aggressive_pass(self) -> None:
        summary = build_runtime_summary(
            decisions=[],
            live_orders=[
                {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 15.0, "realized_edge_bps": 15.0},
                {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.98, "expected_net_edge_bps": 16.0, "realized_edge_bps": 16.0},
                {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 17.0, "realized_edge_bps": 17.0},
                {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.98, "expected_net_edge_bps": 18.0, "realized_edge_bps": 18.0},
                {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 19.0, "realized_edge_bps": 19.0},
                {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.98, "expected_net_edge_bps": 20.0, "realized_edge_bps": 20.0},
                {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 21.0, "realized_edge_bps": 21.0},
                {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.98, "expected_net_edge_bps": 22.0, "realized_edge_bps": 22.0},
                {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 23.0, "realized_edge_bps": 23.0},
                {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.98, "expected_net_edge_bps": 24.0, "realized_edge_bps": 24.0},
            ],
        )
        self.assertEqual(summary["operational_verdict"]["status"], "aggressive_pass")
        self.assertIn("OPERATING_WITH_ELITE_EDGE", summary["operational_verdict"]["reasons"])
        self.assertEqual(summary["promotion_verdict"]["status"], "promote_aggressive")
        self.assertEqual(summary["policy_validation"]["status"], "pass")
        self.assertIn("evidence", summary["policy_validation"])

    def test_runtime_summary_operational_verdict_can_emit_strong_pass(self) -> None:
        summary = build_runtime_summary(
            decisions=[],
            live_orders=[
                {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.96, "expected_net_edge_bps": 15.0, "realized_edge_bps": 13.0},
                {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.95, "expected_net_edge_bps": 14.0, "realized_edge_bps": 12.0},
                {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.97, "expected_net_edge_bps": 16.0, "realized_edge_bps": 13.6},
                {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.95, "expected_net_edge_bps": 15.0, "realized_edge_bps": 12.5},
                {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.96, "expected_net_edge_bps": 17.0, "realized_edge_bps": 14.4},
                {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.95, "expected_net_edge_bps": 13.0, "realized_edge_bps": 11.0},
                {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.97, "expected_net_edge_bps": 18.0, "realized_edge_bps": 15.0},
                {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.96, "expected_net_edge_bps": 16.0, "realized_edge_bps": 13.4},
            ],
        )
        self.assertEqual(summary["operational_verdict"]["status"], "strong_pass")
        self.assertIn("OPERATING_WITH_STRONG_EDGE", summary["operational_verdict"]["reasons"])

    def test_runtime_summary_operational_verdict_holds_for_small_sample(self) -> None:
        decision = evaluate_snapshot(
            make_snapshot("BTCUSDT", FeatureVector(
                ret_rank_1h=0.8, ret_rank_4h=0.78, breakout_norm=0.82, ema_stack_score=1.0,
                vol_z_5m_norm=0.7, vol_z_1h_norm=0.72, taker_imbalance_norm=0.69, spread_bps_norm=0.2, probe_slippage_bps_norm=0.25,
                depth_10bps_norm=0.86, book_stability_norm=0.9, realized_vol_1h_norm=0.3, realized_vol_4h_norm=0.28, vol_shock_norm=0.35,
                funding_abs_percentile=0.14, oi_surge_percentile=0.1, basis_stretch_percentile=0.18, regime_alignment=1.0,
                trend_direction=1, trend_strength=0.82, volume_confirmation=0.74, liquidity_score=0.86, volatility_penalty=0.28, overheat_penalty=0.14,
                gross_expected_edge_bps=24.0, estimated_round_trip_cost_bps=10.0,
            )),
            self.settings, equity_usd=10000.0, remaining_portfolio_capacity_usd=5000.0, expected_funding_drag_bps=2.0,
        )
        summary = build_runtime_summary(
            decisions=[decision],
            live_orders=[
                {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 1.0, "expected_net_edge_bps": 18.0, "realized_edge_bps": 15.0},
                {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 1.0, "expected_net_edge_bps": 16.0, "realized_edge_bps": 13.0},
            ],
        )
        self.assertEqual(summary["operational_verdict"]["status"], "hold")
        self.assertIn("INSUFFICIENT_SAMPLE", summary["operational_verdict"]["reasons"])

    def test_runtime_summary_operational_verdict_stops_on_retention_failure(self) -> None:
        summary = build_runtime_summary(
            decisions=[],
            live_orders=[
                {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.9, "expected_net_edge_bps": 20.0, "realized_edge_bps": 3.0},
                {"symbol": "ETHUSDT", "accepted": False, "fill_status": "reject", "fill_ratio": 0.0, "expected_net_edge_bps": 12.0, "realized_edge_bps": 0.0, "protection_error": "timeout"},
                {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.8, "expected_net_edge_bps": 18.0, "realized_edge_bps": 4.0},
                {"symbol": "ETHUSDT", "accepted": False, "fill_status": "reject", "fill_ratio": 0.0, "expected_net_edge_bps": 10.0, "realized_edge_bps": 0.0, "protection_error": "timeout"},
                {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.8, "expected_net_edge_bps": 16.0, "realized_edge_bps": 2.0},
            ],
        )
        self.assertEqual(summary["operational_verdict"]["status"], "stop")
        self.assertIn("EDGE_RETENTION_TOO_LOW", summary["operational_verdict"]["reasons"])

    def test_auto_tune_policy_demotes_observe_only_alt_and_blocks_promote(self) -> None:
        policy = build_auto_tune_policy(
            [],
            {
                "observe_only_symbols": ["XRPUSDT"],
                "symbol_summary": [
                    {"symbol": "XRPUSDT", "trade_count": 3, "expectancy_usd": 1.5, "recommendation": "promote"},
                    {"symbol": "BTCUSDT", "trade_count": 3, "expectancy_usd": 4.0, "recommendation": "promote"},
                ],
                "regime_summary": [
                    {"mode": "futures", "decision_count": 6, "avg_score": 70.0, "avg_net_edge_bps": 12.0, "avg_cost_bps": 8.0},
                ],
            },
        )
        adjustments = {item["symbol"]: item for item in policy["adjustments"]}
        self.assertEqual(adjustments["XRPUSDT"]["action"], "demote")
        self.assertIn("runtime_observe_only", adjustments["XRPUSDT"]["signal_sources"])
        self.assertEqual(adjustments["BTCUSDT"]["action"], "aggressive_promote")

    def test_runtime_summary_lists_observe_only_symbols(self) -> None:
        features = FeatureVector(
            ret_rank_1h=0.5,
            ret_rank_4h=0.48,
            breakout_norm=0.4,
            ema_stack_score=0.5,
            vol_z_5m_norm=0.45,
            vol_z_1h_norm=0.44,
            taker_imbalance_norm=0.5,
            spread_bps_norm=0.9,
            probe_slippage_bps_norm=0.95,
            depth_10bps_norm=0.1,
            book_stability_norm=0.3,
            realized_vol_1h_norm=0.45,
            realized_vol_4h_norm=0.4,
            vol_shock_norm=0.3,
            funding_abs_percentile=0.2,
            oi_surge_percentile=0.2,
            basis_stretch_percentile=0.2,
            regime_alignment=0.5,
            trend_direction=0,
            trend_strength=0.45,
            volume_confirmation=0.45,
            liquidity_score=0.2,
            volatility_penalty=0.4,
            overheat_penalty=0.2,
            alt_liquidity_support_score=0.2,
            gross_expected_edge_bps=8.0,
            estimated_round_trip_cost_bps=56.0,
        )
        decision = evaluate_snapshot(
            make_snapshot("SIGNUSDT", features),
            self.settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        summary = build_runtime_summary(decisions=[decision])
        self.assertEqual(summary["observe_only_symbols"], ["SIGNUSDT"])
        self.assertIn("candidate_mode", summary["recent_decisions"][0])
        self.assertIn("net_expected_edge_bps", summary["recent_decisions"][0])

    def test_snapshot_validator_accepts_fixed_schema(self) -> None:
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
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.74,
            liquidity_score=0.86,
            volatility_penalty=0.28,
            overheat_penalty=0.14,
            gross_expected_edge_bps=24.0,
            estimated_round_trip_cost_bps=10.0,
        )
        validate_snapshot(make_snapshot("BTCUSDT", features))

    def test_paper_broker_submits_non_cash_decision(self) -> None:
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
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.74,
            liquidity_score=0.86,
            volatility_penalty=0.28,
            overheat_penalty=0.14,
            gross_expected_edge_bps=24.0,
            estimated_round_trip_cost_bps=10.0,
        )
        decision = evaluate_snapshot(
            make_snapshot("BTCUSDT", features),
            self.settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            expected_funding_drag_bps=2.0,
        )
        broker = PaperBroker()
        order = broker.submit(decision)
        self.assertIsNotNone(order)
        self.assertEqual(order.symbol, "BTCUSDT")
        self.assertEqual(order.decision_hash, decision.decision_hash)

    def test_portfolio_intent_compiles_back_to_decision(self) -> None:
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
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.74,
            liquidity_score=0.86,
            volatility_penalty=0.28,
            overheat_penalty=0.14,
            gross_expected_edge_bps=24.0,
            estimated_round_trip_cost_bps=10.0,
        )
        prediction = build_strategy_prediction(make_snapshot("BTCUSDT", features), self.settings, expected_funding_drag_bps=2.0)
        intent = build_portfolio_intent(
            prediction=prediction,
            selected_mode="futures",
            side="long",
            target_notional_usd=1234.0,
            stop_distance_bps=45.0,
            target_leverage=4.0,
            strategy_size_multiplier=1.2,
        )
        decision = decision_from_portfolio_intent(intent=intent)
        self.assertEqual(decision.final_mode, "futures")
        self.assertEqual(decision.side, "long")
        self.assertEqual(decision.order_intent_notional_usd, 1234.0)
        self.assertEqual(decision.stop_distance_bps, 45.0)
        self.assertEqual(decision.candidate_mode, prediction.candidate_mode)

    def test_manifest_writer_produces_machine_readable_output(self) -> None:
        sample = ROOT / "quant_binance" / "config.example.json"
        entry = build_manifest_entry(sample, schema_version="1.0.0")
        manifest_path = ROOT / "tests" / "tmp_manifest.json"
        try:
            write_manifest(manifest_path, [entry])
            self.assertTrue(manifest_path.exists())
            content = manifest_path.read_text(encoding="utf-8")
            self.assertIn('"entries"', content)
            self.assertIn('"sha256"', content)
            self.assertIn(sample.name, content)
        finally:
            if manifest_path.exists():
                manifest_path.unlink()


if __name__ == "__main__":
    unittest.main()
