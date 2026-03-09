from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_binance.backtest.metrics import virtual_performance_from_decisions
from quant_binance.backtest.replay import run_replay
from quant_binance.data.snapshot_builder import SnapshotBuilder
from quant_binance.data.state import KlineBar, SymbolMarketState, TopOfBook
from quant_binance.execution.router import ExecutionRouter
from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs, build_feature_vector_from_primitives
from quant_binance.models import FeatureVector
from quant_binance.service import PaperTradingService
from quant_binance.settings import Settings
from quant_binance.strategy.edge import ConditionalEdgeLookup
from quant_binance.strategy.scorer import apply_score_and_costs, estimate_live_fallback_edge_bps


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


def make_history() -> FeatureHistoryContext:
    return FeatureHistoryContext(
        returns_1h=(0.01, 0.02, 0.03, 0.04, 0.05),
        returns_4h=(0.02, 0.03, 0.04, 0.05, 0.06),
        quote_volume_5m=(1000, 1100, 1200, 1300, 1400),
        quote_volume_1h=(10000, 10500, 11000, 11500, 12000),
        realized_vol_1h=(0.1, 0.12, 0.14, 0.16, 0.18),
        realized_vol_4h=(0.15, 0.17, 0.19, 0.21, 0.23),
        funding_abs=(0.0001, 0.0002, 0.0003, 0.0004, 0.0005),
        basis_abs=(2.0, 3.0, 4.0, 5.0, 6.0),
        oi_surge=(0.05, 0.1, 0.15, 0.2, 0.25),
    )


def make_primitives() -> PrimitiveInputs:
    return PrimitiveInputs(
        ret_1h=0.05,
        ret_4h=0.06,
        trend_direction=1,
        ema_stack_score=1.0,
        breakout_reference_price=49500.0,
        last_trade_price=50000.0,
        atr_14_1h_price=200.0,
        quote_volume_5m=1600.0,
        quote_volume_1h=13000.0,
        buy_taker_volume=70.0,
        sell_taker_volume=30.0,
        spread_bps=2.0,
        probe_slippage_bps=3.0,
        depth_usd_within_10bps=300000.0,
        order_book_imbalance_std=0.1,
        realized_vol_1h=0.18,
        realized_vol_4h=0.23,
        median_realized_vol_1h_30d=0.12,
        funding_rate=0.0002,
        open_interest=1200000.0,
        open_interest_ema=1000000.0,
        basis_bps=5.5,
        gross_expected_edge_bps=24.0,
    )


class QuantBinanceFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def _make_state(self, decision_time: datetime) -> SymbolMarketState:
        return SymbolMarketState(
            symbol="BTCUSDT",
            top_of_book=TopOfBook(49999.5, 1.0, 50000.5, 1.2, decision_time),
            last_trade_price=50000.0,
            funding_rate=0.0002,
            open_interest=1200000.0,
            basis_bps=5.5,
            last_update_time=decision_time,
        )

    def test_build_feature_vector_from_primitives(self) -> None:
        features = build_feature_vector_from_primitives(
            inputs=make_primitives(),
            history=make_history(),
            settings=self.settings,
        )
        self.assertGreater(features.trend_strength, 0.7)
        self.assertGreater(features.volume_confirmation, 0.6)
        self.assertGreater(features.liquidity_score, 0.7)

    def test_enriched_features_include_support_and_resistance(self) -> None:
        decision_time = datetime(2026, 3, 8, 12, 5, 0, tzinfo=timezone.utc)
        service = PaperTradingService(self.settings, router=ExecutionRouter())
        state = self._make_state(decision_time)
        for idx in range(130):
            close_time = decision_time - timedelta(hours=130 - idx)
            state.klines.setdefault("1h", []).append(
                KlineBar(
                    symbol="BTCUSDT",
                    interval="1h",
                    start_time=close_time - timedelta(hours=1),
                    close_time=close_time,
                    open_price=48000 + idx * 10,
                    high_price=48100 + idx * 10,
                    low_price=47950 + idx * 10,
                    close_price=48020 + idx * 10,
                    volume=10 + idx,
                    quote_volume=500000 + idx * 1000,
                    is_closed=True,
                )
            )
        features = build_feature_vector_from_primitives(
            inputs=make_primitives(),
            history=make_history(),
            settings=self.settings,
        )
        enriched = service.feature_extractor.enrich_feature_vector(state=state, features=features)
        self.assertGreaterEqual(enriched.support_alignment, 0.0)
        self.assertGreaterEqual(enriched.resistance_penalty, 0.0)

    def test_edge_lookup_uses_symbol_then_pooled_fallback(self) -> None:
        lookup = ConditionalEdgeLookup(min_observations=2)
        lookup.add_observation(symbol="BTCUSDT", mode="futures", predictability_score=82.0, trend_direction=1, forward_return_bps=25.0)
        lookup.add_observation(symbol="BTCUSDT", mode="futures", predictability_score=84.0, trend_direction=1, forward_return_bps=27.0)
        lookup.add_observation(symbol="ETHUSDT", mode="futures", predictability_score=81.0, trend_direction=1, forward_return_bps=23.0)
        lookup.add_observation(symbol="ETHUSDT", mode="futures", predictability_score=85.0, trend_direction=1, forward_return_bps=21.0)
        self.assertEqual(lookup.expected_edge_bps(symbol="BTCUSDT", mode="futures", predictability_score=83.0, trend_direction=1), 26.0)
        self.assertEqual(lookup.expected_edge_bps(symbol="SOLUSDT", mode="futures", predictability_score=82.0, trend_direction=1), 24.0)

    def test_replay_runner_produces_decisions_and_orders(self) -> None:
        base_time = datetime(2026, 3, 8, 12, 5, 0, tzinfo=timezone.utc)
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
        builder = SnapshotBuilder(self.settings)
        snapshots = [
            builder.build(self._make_state(base_time + timedelta(minutes=5 * index)), features, base_time + timedelta(minutes=5 * index))
            for index in range(2)
        ]
        result = run_replay(
            snapshots=snapshots,
            settings=self.settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        self.assertEqual(len(result.decisions), 2)
        self.assertEqual(result.order_count, 2)

    def test_live_fallback_edge_positive_for_strong_spot_setup(self) -> None:
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
            support_alignment=0.8,
            resistance_penalty=0.0,
            macro_regime="supportive",
            macro_risk_penalty=0.1,
            sentiment_regime="risk_on",
            sentiment_support_score=0.8,
        )
        edge = estimate_live_fallback_edge_bps(
            features=features,
            settings=self.settings,
            mode="spot",
        )
        self.assertGreater(edge, 10.0)

    def test_apply_score_and_costs_prefers_stronger_fallback_edge(self) -> None:
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
            support_alignment=0.8,
            resistance_penalty=0.0,
            macro_regime="supportive",
            macro_risk_penalty=0.1,
            sentiment_regime="risk_on",
            sentiment_support_score=0.8,
            gross_expected_edge_bps=12.0,
        )
        scored = apply_score_and_costs(features, settings=self.settings, mode="spot")
        self.assertGreater(scored.gross_expected_edge_bps, 12.0)

    def test_virtual_performance_from_replay_decisions(self) -> None:
        base_time = datetime(2026, 3, 8, 12, 5, 0, tzinfo=timezone.utc)
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
        builder = SnapshotBuilder(self.settings)
        snapshots = [
            builder.build(self._make_state(base_time + timedelta(minutes=5 * index)), features, base_time + timedelta(minutes=5 * index))
            for index in range(2)
        ]
        result = run_replay(
            snapshots=snapshots,
            settings=self.settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        performance = virtual_performance_from_decisions(
            decisions=result.decisions,
            starting_equity_usd=10000.0,
        )
        self.assertEqual(performance.executed_decision_count, 2)
        self.assertGreater(performance.total_pnl_usd, 0.0)

    def test_paper_trading_service_runs_single_cycle(self) -> None:
        decision_time = datetime(2026, 3, 8, 12, 5, 0, tzinfo=timezone.utc)
        service = PaperTradingService(self.settings, router=ExecutionRouter())
        decision = service.run_cycle(
            state=self._make_state(decision_time),
            primitive_inputs=make_primitives(),
            history=make_history(),
            decision_time=decision_time,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        self.assertIn(decision.final_mode, {"futures", "spot", "cash"})
        self.assertEqual(decision.symbol, "BTCUSDT")


if __name__ == "__main__":
    unittest.main()
