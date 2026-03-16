from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from quant_binance.models import FeatureVector, MarketSnapshot
from quant_binance.execution.paper_broker import PaperBroker
from quant_binance.observability.decision_log import hash_decision_payload, render_audit_report
from quant_binance.observability.manifest import build_manifest_entry, write_manifest
from quant_binance.observability.report import build_runtime_summary
from quant_binance.risk.sizing import position_notional_and_stop_bps, quantity_from_notional
from quant_binance.snapshots import validate_snapshot
from quant_binance.settings import Settings
from quant_binance.strategy.regime import evaluate_snapshot
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
