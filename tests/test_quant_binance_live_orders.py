from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from pathlib import Path

from quant_binance.execution.live_order_adapter import DecisionLiveOrderAdapter
from quant_binance.execution.order_test_adapter import DecisionOrderTestAdapter
from quant_binance.learning import OnlineEdgeLearner
from quant_binance.live import EventDispatcher, LivePaperRuntime
from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.state import SymbolMarketState, TopOfBook
from quant_binance.execution.router import ExecutionRouter
from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs
from quant_binance.service import PaperTradingService
from quant_binance.session import LivePaperSession
from quant_binance.risk.sizing import select_futures_leverage
from quant_binance.settings import Settings
from quant_binance.observability.log_store import JsonlLogStore


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


def make_primitive() -> PrimitiveInputs:
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
        realized_vol_1h=0.12,
        realized_vol_4h=0.17,
        median_realized_vol_1h_30d=0.12,
        funding_rate=0.0001,
        open_interest=1080000.0,
        open_interest_ema=1000000.0,
        basis_bps=3.0,
        gross_expected_edge_bps=30.0,
    )


class FakeLiveOrderClient:
    def __init__(self) -> None:
        self.calls = 0
        self.leverage_calls: list[tuple[str, int]] = []
        self.protection_calls: list[tuple[str, dict[str, object]]] = []
        self.max_openable_quantity: float | None = None

    def set_futures_leverage(self, *, symbol, leverage):  # type: ignore[no-untyped-def]
        self.leverage_calls.append((symbol, leverage))
        return {"symbol": symbol, "leverage": leverage}

    def place_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        self.calls += 1
        return {"status": "FILLED", "market": market, "orderId": self.calls}

    def place_futures_position_tpsl(self, *, order_params):  # type: ignore[no-untyped-def]
        self.protection_calls.append(("futures", order_params))
        return {"status": "SUCCESS", "orderId": "tp-sl"}

    def place_spot_plan_order(self, *, order_params):  # type: ignore[no-untyped-def]
        self.protection_calls.append(("spot", order_params))
        return {"status": "SUCCESS", "orderId": "spot-plan"}

    def get_max_openable_quantity(self, *, symbol, pos_side, order_type):  # type: ignore[no-untyped-def]
        return self.max_openable_quantity

    def get_exchange_info(self, *, market):  # type: ignore[no-untyped-def]
        return {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "raw": {
                        "minTradeNum": "0.001",
                        "sizeMultiplier": "0.001",
                        "volumePlace": "3",
                    },
                }
            ]
        }


class RaisingLiveOrderClient(FakeLiveOrderClient):
    def place_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise RuntimeError("simulated live order failure")


class RaisingTestOrderClient:
    def test_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated test order failure")


class QuantBinanceLiveOrdersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def _load_settings_for_profile(self, profile: str) -> Settings:
        previous = os.environ.get("STRATEGY_PROFILE")
        os.environ["STRATEGY_PROFILE"] = profile
        try:
            return Settings.load(CONFIG_PATH)
        finally:
            if previous is None:
                os.environ.pop("STRATEGY_PROFILE", None)
            else:
                os.environ["STRATEGY_PROFILE"] = previous

    def test_live_ultra_aggressive_uses_target_leverage_for_merely_strong_setup(self) -> None:
        settings = self._load_settings_for_profile("live-ultra-aggressive")

        leverage = select_futures_leverage(
            predictability_score=66.7,
            trend_strength=0.72,
            volume_confirmation=0.62,
            liquidity_score=0.9,
            volatility_penalty=0.25,
            overheat_penalty=0.2,
            net_expected_edge_bps=25.8,
            estimated_round_trip_cost_bps=8.0,
            settings=settings,
        )

        self.assertEqual(leverage, 8)

    def test_live_ultra_aggressive_reserves_max_leverage_for_exceptional_setup(self) -> None:
        settings = self._load_settings_for_profile("live-ultra-aggressive")

        leverage = select_futures_leverage(
            predictability_score=78.0,
            trend_strength=0.88,
            volume_confirmation=0.82,
            liquidity_score=0.95,
            volatility_penalty=0.18,
            overheat_penalty=0.12,
            net_expected_edge_bps=34.0,
            estimated_round_trip_cost_bps=8.0,
            settings=settings,
        )

        self.assertEqual(leverage, 15)

    def test_live_order_adapter_executes_market_order(self) -> None:
        from quant_binance.models import DecisionIntent

        decision = DecisionIntent(
            decision_id="d1",
            decision_hash="hash-1",
            snapshot_id="s1",
            config_version="2026-03-08.v1",
            timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.8,
            volume_confirmation=0.7,
            liquidity_score=0.8,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=82.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=14.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=2000.0,
            stop_distance_bps=45.0,
        )
        live_client = FakeLiveOrderClient()
        adapter = DecisionLiveOrderAdapter(live_client, self.settings)  # type: ignore[arg-type]
        result = adapter.execute_decision(decision=decision, reference_price=50000.0)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.accepted)
        self.assertEqual(result.market, "futures")
        self.assertEqual(live_client.leverage_calls, [("BTCUSDT", 2)])

    def test_live_order_adapter_uses_active_profile_max_leverage_for_strong_futures_short(self) -> None:
        from quant_binance.models import DecisionIntent

        settings = self._load_settings_for_profile("active")
        decision = DecisionIntent(
            decision_id="d-strong-short",
            decision_hash="hash-strong-short",
            snapshot_id="s-strong-short",
            config_version="2026-03-10.v1",
            timestamp=datetime(2026, 3, 11, 0, 30, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="short",
            trend_direction=-1,
            trend_strength=0.86,
            volume_confirmation=0.8,
            liquidity_score=0.84,
            volatility_penalty=0.24,
            overheat_penalty=0.16,
            predictability_score=87.0,
            gross_expected_edge_bps=40.0,
            net_expected_edge_bps=28.0,
            estimated_round_trip_cost_bps=12.0,
            order_intent_notional_usd=140.0,
            stop_distance_bps=45.0,
        )
        live_client = FakeLiveOrderClient()
        adapter = DecisionLiveOrderAdapter(live_client, settings)  # type: ignore[arg-type]

        result = adapter.execute_decision(decision=decision, reference_price=50000.0)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.market, "futures")
        self.assertEqual(result.side, "SELL")
        self.assertEqual(live_client.leverage_calls, [("BTCUSDT", 10)])

    def test_live_order_adapter_uses_soft_active_leverage_for_borderline_futures_setup(self) -> None:
        from quant_binance.models import DecisionIntent

        settings = self._load_settings_for_profile("active")
        decision = DecisionIntent(
            decision_id="d-soft-short",
            decision_hash="hash-soft-short",
            snapshot_id="s-soft-short",
            config_version="2026-03-10.v1",
            timestamp=datetime(2026, 3, 11, 0, 35, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="short",
            trend_direction=-1,
            trend_strength=0.64,
            volume_confirmation=0.61,
            liquidity_score=0.66,
            volatility_penalty=0.66,
            overheat_penalty=0.3,
            predictability_score=67.0,
            gross_expected_edge_bps=33.0,
            net_expected_edge_bps=12.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=60.0,
            stop_distance_bps=55.0,
        )
        live_client = FakeLiveOrderClient()
        adapter = DecisionLiveOrderAdapter(live_client, settings)  # type: ignore[arg-type]

        adapter.execute_decision(decision=decision, reference_price=50000.0)

        self.assertEqual(live_client.leverage_calls, [("BTCUSDT", 4)])

    def test_live_order_adapter_rejects_bitget_futures_order_below_min_quantity_after_max_open_cap(self) -> None:
        from quant_binance.models import DecisionIntent

        decision = DecisionIntent(
            decision_id="d-min-qty",
            decision_hash="hash-min-qty",
            snapshot_id="s-min-qty",
            config_version="2026-03-16.v1",
            timestamp=datetime(2026, 3, 16, 1, 0, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.85,
            volume_confirmation=0.78,
            liquidity_score=0.88,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=84.0,
            gross_expected_edge_bps=26.0,
            net_expected_edge_bps=16.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=200.0,
            stop_distance_bps=45.0,
        )
        live_client = FakeLiveOrderClient()
        live_client.exchange_id = "bitget"
        live_client.max_openable_quantity = 0.000001
        adapter = DecisionLiveOrderAdapter(live_client, self.settings)  # type: ignore[arg-type]

        built = adapter.build_order_params(decision=decision, reference_price=50000.0)

        self.assertIsNone(built)
        rejection = adapter.pop_last_preflight_rejection()
        self.assertIsNotNone(rejection)
        assert rejection is not None
        self.assertEqual(rejection["reason"], "BITGET_MAX_OPEN_BELOW_MIN_QTY")

    def test_live_order_adapter_uses_quote_order_qty_for_spot_market_buy(self) -> None:
        from quant_binance.models import DecisionIntent

        decision = DecisionIntent(
            decision_id="d2",
            decision_hash="hash-2",
            snapshot_id="s2",
            config_version="2026-03-10.v1",
            timestamp=datetime(2026, 3, 10, 0, 30, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="spot",
            side="long",
            trend_direction=1,
            trend_strength=0.8,
            volume_confirmation=0.7,
            liquidity_score=0.8,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=66.0,
            gross_expected_edge_bps=30.0,
            net_expected_edge_bps=18.0,
            estimated_round_trip_cost_bps=12.0,
            order_intent_notional_usd=2400.0,
            stop_distance_bps=80.0,
        )
        adapter = DecisionLiveOrderAdapter(FakeLiveOrderClient(), self.settings)  # type: ignore[arg-type]
        built = adapter.build_order_params(decision=decision, reference_price=50000.0)
        assert built is not None
        market, params = built
        self.assertEqual(market, "spot")
        self.assertEqual(params["side"], "BUY")
        self.assertEqual(params["quoteOrderQty"], "2400.00")
        self.assertNotIn("quantity", params)

    def test_live_order_adapter_uses_base_quantity_for_routed_spot_market_buy(self) -> None:
        from quant_binance.models import DecisionIntent

        decision = DecisionIntent(
            decision_id="d2-routed",
            decision_hash="hash-2-routed",
            snapshot_id="s2-routed",
            config_version="2026-03-10.v1",
            timestamp=datetime(2026, 3, 10, 0, 35, tzinfo=timezone.utc),
            symbol="ETHUSDT",
            candidate_mode="spot",
            final_mode="spot",
            side="long",
            trend_direction=1,
            trend_strength=0.8,
            volume_confirmation=0.7,
            liquidity_score=0.8,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=66.0,
            gross_expected_edge_bps=30.0,
            net_expected_edge_bps=18.0,
            estimated_round_trip_cost_bps=12.0,
            order_intent_notional_usd=125.0,
            stop_distance_bps=80.0,
            execution_symbol="ETHBTC",
            spot_base_asset="ETH",
            spot_quote_asset="BTC",
            spot_funding_asset="BTC",
        )
        adapter = DecisionLiveOrderAdapter(FakeLiveOrderClient(), self.settings)  # type: ignore[arg-type]
        built = adapter.build_order_params(decision=decision, reference_price=2500.0)
        assert built is not None
        market, params = built
        self.assertEqual(market, "spot")
        self.assertEqual(params["symbol"], "ETHBTC")
        self.assertEqual(params["side"], "BUY")
        self.assertEqual(params["quantity"], "0.05000000")
        self.assertNotIn("quoteOrderQty", params)

    def test_session_caps_futures_notional_to_execution_balance(self) -> None:
        from quant_binance.models import DecisionIntent

        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(MarketStateStore()),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
        )
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        session.capital_report = {
            "futures_available_balance_usd": 37.96533289,
            "futures_execution_balance_usd": 4.85780789,
            "can_trade_futures_any": True,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0}],
        }
        decision = DecisionIntent(
            decision_id="d-exec-cap",
            decision_hash="hash-exec-cap",
            snapshot_id="s-exec-cap",
            config_version="2026-03-12.v1",
            timestamp=now,
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.75,
            liquidity_score=0.84,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=86.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=14.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=95.0,
            stop_distance_bps=45.0,
        )

        capped = session._cap_live_order_decision(decision)

        leverage = select_futures_leverage(
            predictability_score=decision.predictability_score,
            trend_strength=decision.trend_strength,
            volume_confirmation=decision.volume_confirmation,
            liquidity_score=decision.liquidity_score,
            volatility_penalty=decision.volatility_penalty,
            overheat_penalty=decision.overheat_penalty,
            net_expected_edge_bps=decision.net_expected_edge_bps,
            estimated_round_trip_cost_bps=decision.estimated_round_trip_cost_bps,
            settings=self.settings,
        )
        expected = round(
            4.85780789 * leverage * (1.0 - self.settings.cash_reserve.when_futures_enabled),
            6,
        )
        self.assertEqual(capped.order_intent_notional_usd, expected)
        self.assertLess(capped.order_intent_notional_usd, decision.order_intent_notional_usd)

    def test_session_rejects_futures_order_below_min_quantity(self) -> None:
        from quant_binance.models import DecisionIntent

        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(MarketStateStore()),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
        )
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        session.capital_report = {
            "futures_available_balance_usd": 98.0,
            "futures_execution_balance_usd": 6.0,
            "can_trade_futures_any": True,
            "futures_requirements": [{"symbol": "ETHUSDT", "min_notional_usd": 5.0, "min_quantity": 0.01}],
        }
        decision = DecisionIntent(
            decision_id="d-min-qty",
            decision_hash="hash-min-qty",
            snapshot_id="s-min-qty",
            config_version="2026-03-12.v1",
            timestamp=now,
            symbol="ETHUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.75,
            liquidity_score=0.84,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=86.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=14.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=5.1,
            stop_distance_bps=45.0,
        )

        capped = session._cap_live_order_decision(decision, reference_price=2069.58)

        self.assertEqual(capped.final_mode, "cash")
        self.assertIn("MIN_ORDER_QUANTITY", capped.rejection_reasons)

    def test_session_caps_spot_notional_to_usdt_execution_balance_even_with_recognized_coin_assets(self) -> None:
        from quant_binance.models import DecisionIntent

        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(MarketStateStore()),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
        )
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        session.capital_report = {
            "spot_available_balance_usd": 10.0,
            "spot_recognized_balance_usd": 510.0,
            "can_trade_spot_any": True,
            "futures_requirements": [],
            "spot_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0}],
        }
        decision = DecisionIntent(
            decision_id="d-spot-exec-cap",
            decision_hash="hash-spot-exec-cap",
            snapshot_id="s-spot-exec-cap",
            config_version="2026-03-12.v1",
            timestamp=now,
            symbol="BTCUSDT",
            candidate_mode="spot",
            final_mode="spot",
            side="long",
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.75,
            liquidity_score=0.84,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=70.0,
            gross_expected_edge_bps=20.0,
            net_expected_edge_bps=12.0,
            estimated_round_trip_cost_bps=8.0,
            order_intent_notional_usd=95.0,
            stop_distance_bps=45.0,
        )

        capped = session._cap_live_order_decision(decision)

        expected = round(10.0 * (1.0 - self.settings.cash_reserve.when_futures_disabled), 6)
        self.assertEqual(capped.order_intent_notional_usd, expected)
        self.assertLess(capped.order_intent_notional_usd, decision.order_intent_notional_usd)

    def test_session_routes_spot_buy_to_btc_quote_when_usdt_route_cannot_cover_order(self) -> None:
        from quant_binance.models import DecisionIntent

        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(MarketStateStore()),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
        )
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        session.capital_report = {
            "spot_available_balance_usd": 10.0,
            "spot_recognized_balance_usd": 510.0,
            "can_trade_spot_any": True,
            "futures_requirements": [],
            "spot_requirements": [{"symbol": "ETHUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
            "spot_execution_routes": [
                {
                    "target_symbol": "ETHUSDT",
                    "execution_symbol": "ETHUSDT",
                    "base_asset": "ETH",
                    "quote_asset": "USDT",
                    "funding_asset": "USDT",
                    "route_type": "direct",
                    "free_balance": 10.0,
                    "free_balance_usd": 10.0,
                    "min_notional_usd": 5.0,
                    "min_quantity": 0.001,
                },
                {
                    "target_symbol": "ETHUSDT",
                    "execution_symbol": "ETHBTC",
                    "base_asset": "ETH",
                    "quote_asset": "BTC",
                    "funding_asset": "BTC",
                    "route_type": "cross_quote",
                    "free_balance": 0.01,
                    "free_balance_usd": 500.0,
                    "min_notional_usd": 5.0,
                    "min_quantity": 0.001,
                },
            ],
        }
        decision = DecisionIntent(
            decision_id="d-spot-route",
            decision_hash="hash-spot-route",
            snapshot_id="s-spot-route",
            config_version="2026-03-12.v1",
            timestamp=now,
            symbol="ETHUSDT",
            candidate_mode="spot",
            final_mode="spot",
            side="long",
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.75,
            liquidity_score=0.84,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=70.0,
            gross_expected_edge_bps=20.0,
            net_expected_edge_bps=12.0,
            estimated_round_trip_cost_bps=8.0,
            order_intent_notional_usd=95.0,
            stop_distance_bps=45.0,
        )

        capped = session._cap_live_order_decision(decision, reference_price=2500.0)

        self.assertEqual(capped.execution_symbol, "ETHBTC")
        self.assertEqual(capped.spot_funding_asset, "BTC")
        self.assertEqual(capped.spot_quote_asset, "BTC")
        self.assertEqual(capped.order_intent_notional_usd, decision.order_intent_notional_usd)

    def test_session_blocks_new_futures_entry_when_live_position_already_exists(self) -> None:
        from quant_binance.models import DecisionIntent

        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(MarketStateStore()),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
        )
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        session.capital_report = {
            "futures_available_balance_usd": 98.0,
            "futures_execution_balance_usd": 50.0,
            "can_trade_futures_any": True,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        session.live_positions_snapshot = [
            {"symbol": "BTCUSDT", "holdSide": "long", "total": "0.02", "unrealizedPL": "2", "marginSize": "10"}
        ]
        decision = DecisionIntent(
            decision_id="d-existing-live",
            decision_hash="hash-existing-live",
            snapshot_id="s-existing-live",
            config_version="2026-03-12.v1",
            timestamp=now,
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.75,
            liquidity_score=0.84,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=86.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=14.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=95.0,
            stop_distance_bps=45.0,
        )

        capped = session._cap_live_order_decision(decision, reference_price=50000.0)

        self.assertEqual(capped.final_mode, "futures")
        self.assertNotIn("LIVE_POSITION_ALREADY_OPEN", capped.rejection_reasons)

    def test_session_blocks_live_order_during_manual_close_cooldown(self) -> None:
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        store = MarketStateStore()
        store.put(
            SymbolMarketState(
                symbol="BTCUSDT",
                top_of_book=TopOfBook(49999.5, 1.0, 50000.5, 1.2, now),
                last_trade_price=50000.0,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=3.0,
                last_update_time=now,
            )
        )
        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(store),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
        )
        live_client = FakeLiveOrderClient()
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            live_order_executor=DecisionLiveOrderAdapter(live_client),  # type: ignore[arg-type]
        )
        session.manual_symbol_cooldowns["BTCUSDT"] = now.replace(minute=10)
        payload = {
            "stream": "btcusdt@kline_5m",
            "data": {
                "s": "BTCUSDT",
                "k": {
                    "i": "5m",
                    "t": 1772971200000,
                    "T": 1772971500000,
                    "o": "49900",
                    "h": "50100",
                    "l": "49850",
                    "c": "50050",
                    "v": "12",
                    "q": "600000",
                    "x": True,
                },
            },
        }
        session.process_payload(payload, now=now)
        self.assertEqual(live_client.calls, 0)

    def test_session_survives_live_order_exception(self) -> None:
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        store = MarketStateStore()
        store.put(
            SymbolMarketState(
                symbol="BTCUSDT",
                top_of_book=TopOfBook(49999.5, 1.0, 50000.5, 1.2, now),
                last_trade_price=50000.0,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=3.0,
                last_update_time=now,
            )
        )
        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(store),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
        )
        live_client = RaisingLiveOrderClient()
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            live_order_executor=DecisionLiveOrderAdapter(live_client),  # type: ignore[arg-type]
            order_tester=DecisionOrderTestAdapter(RaisingTestOrderClient()),  # type: ignore[arg-type]
            log_store=JsonlLogStore(ROOT / ".tmp-test-logs"),
        )
        payload = {
            "stream": "btcusdt@kline_5m",
            "data": {
                "s": "BTCUSDT",
                "k": {
                    "i": "5m",
                    "t": 1772971200000,
                    "T": 1772971500000,
                    "o": "49900",
                    "h": "50100",
                    "l": "49850",
                    "c": "50050",
                    "v": "12",
                    "q": "600000",
                    "x": True,
                },
            },
        }
        decision = session.process_payload(payload, now=now)
        self.assertIsNotNone(decision)
        self.assertEqual(len(session.decisions), 1)
        self.assertEqual(len(session.live_orders), 0)
        self.assertEqual(len(session.tested_orders), 0)

    def test_session_prevents_duplicate_live_order_hash(self) -> None:
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        store = MarketStateStore()
        store.put(
            SymbolMarketState(
                symbol="BTCUSDT",
                top_of_book=TopOfBook(49999.5, 1.0, 50000.5, 1.2, now),
                last_trade_price=50000.0,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=3.0,
                last_update_time=now,
            )
        )
        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(store),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
        )
        live_client = FakeLiveOrderClient()
        learner = OnlineEdgeLearner(min_observations=1)
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            live_order_executor=DecisionLiveOrderAdapter(live_client),  # type: ignore[arg-type]
            learner=learner,
        )
        payload = {
            "stream": "btcusdt@kline_5m",
            "data": {
                "s": "BTCUSDT",
                "k": {
                    "i": "5m",
                    "t": 1772971200000,
                    "T": 1772971500000,
                    "o": "49900",
                    "h": "50100",
                    "l": "49850",
                    "c": "50050",
                    "v": "12",
                    "q": "600000",
                    "x": True,
                },
            },
        }
        session.process_payload(payload, now=now)
        session.process_payload(payload, now=now)
        self.assertEqual(live_client.calls, 1)


if __name__ == "__main__":
    unittest.main()

class QuantBinanceCrossQuoteDirectPairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def test_live_order_adapter_sizes_direct_ethbtc_from_quote_usd_price(self) -> None:
        from quant_binance.models import DecisionIntent

        decision = DecisionIntent(
            decision_id="d-ethbtc-direct",
            decision_hash="hash-ethbtc-direct",
            snapshot_id="s-ethbtc-direct",
            config_version="2026-03-16.v1",
            timestamp=datetime(2026, 3, 16, 0, 0, tzinfo=timezone.utc),
            symbol="ETHBTC",
            candidate_mode="spot",
            final_mode="spot",
            side="long",
            trend_direction=1,
            trend_strength=0.8,
            volume_confirmation=0.72,
            liquidity_score=0.8,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=68.0,
            gross_expected_edge_bps=22.0,
            net_expected_edge_bps=14.0,
            estimated_round_trip_cost_bps=8.0,
            order_intent_notional_usd=125.0,
            stop_distance_bps=50.0,
            execution_symbol="ETHBTC",
            spot_base_asset="ETH",
            spot_quote_asset="BTC",
            spot_funding_asset="BTC",
            spot_quote_asset_usd_price=50000.0,
        )
        adapter = DecisionLiveOrderAdapter(FakeLiveOrderClient(), self.settings)  # type: ignore[arg-type]
        built = adapter.build_order_params(decision=decision, reference_price=0.05)
        assert built is not None
        _, params = built
        self.assertEqual(params["symbol"], "ETHBTC")
        self.assertEqual(params["quantity"], "0.05000000")

    def test_session_attempts_wallet_transfer_for_underfunded_futures_entry(self) -> None:
        from quant_binance.models import DecisionIntent

        class TransferCapableRestClient:
            def __init__(self) -> None:
                self.transfer_calls: list[dict[str, object]] = []

            def transfer_wallet_balance(self, *, asset, amount, source_market, target_market, client_oid=None):  # type: ignore[no-untyped-def]
                self.transfer_calls.append({
                    "asset": asset,
                    "amount": amount,
                    "source_market": source_market,
                    "target_market": target_market,
                    "client_oid": client_oid,
                })
                return {"status": "success"}

            def get_account(self, *, market):  # type: ignore[no-untyped-def]
                return {}

            def get_open_orders(self, *, market, symbol=None):  # type: ignore[no-untyped-def]
                return {}

            def build_capital_report(self):  # type: ignore[no-untyped-def]
                raise NotImplementedError

            def get_positions(self):  # type: ignore[no-untyped-def]
                return {}

            def cancel_order(self, *, market, symbol, order_id):  # type: ignore[no-untyped-def]
                return {}

        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(MarketStateStore()),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
        )
        rest_client = TransferCapableRestClient()
        session = LivePaperSession(runtime=runtime, equity_usd=10000.0, remaining_portfolio_capacity_usd=5000.0, rest_client=rest_client)  # type: ignore[arg-type]
        session.capital_report = {
            "futures_available_balance_usd": 0.0,
            "futures_execution_balance_usd": 0.0,
            "spot_available_balance_usd": 0.0,
            "max_spot_to_futures_transfer_usd": 80.0,
            "can_trade_futures_any": False,
            "capital_transfer_routes": [
                {
                    "source_market": "spot",
                    "target_market": "futures",
                    "asset": "USDT",
                    "transferable_usd": 80.0,
                }
            ],
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        session._refresh_account_state_after_live_order_activity = lambda **kwargs: None  # type: ignore[method-assign]
        decision = DecisionIntent(
            decision_id="d-transfer-auto",
            decision_hash="hash-transfer-auto",
            snapshot_id="s-transfer-auto",
            config_version="2026-03-16.v1",
            timestamp=datetime(2026, 3, 16, 0, 15, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.75,
            liquidity_score=0.84,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=86.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=14.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=95.0,
            stop_distance_bps=45.0,
        )

        executable = session._prepare_live_execution_decision(
            decision=decision,
            reference_price=50000.0,
        )

        self.assertEqual(executable.final_mode, "futures")
        self.assertEqual(len(rest_client.transfer_calls), 1)
        self.assertEqual(rest_client.transfer_calls[0]["asset"], "USDT")
        self.assertEqual(rest_client.transfer_calls[0]["source_market"], "spot")
        self.assertEqual(rest_client.transfer_calls[0]["target_market"], "futures")
        self.assertTrue(rest_client.transfer_calls[0]["client_oid"])
        self.assertGreater(float(rest_client.transfer_calls[0]["amount"]), 0.0)

    def test_session_rejects_underfunded_futures_entry_with_transfer_hint(self) -> None:
        from quant_binance.models import DecisionIntent

        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(MarketStateStore()),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
        )
        session = LivePaperSession(runtime=runtime, equity_usd=10000.0, remaining_portfolio_capacity_usd=5000.0)
        session.capital_report = {
            "futures_available_balance_usd": 0.0,
            "futures_execution_balance_usd": 0.0,
            "can_trade_futures_any": False,
            "max_spot_to_futures_transfer_usd": 25.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        decision = DecisionIntent(
            decision_id="d-transfer-hint",
            decision_hash="hash-transfer-hint",
            snapshot_id="s-transfer-hint",
            config_version="2026-03-16.v1",
            timestamp=datetime(2026, 3, 16, 0, 5, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.75,
            liquidity_score=0.84,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=86.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=14.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=95.0,
            stop_distance_bps=45.0,
        )

        capped = session._cap_live_order_decision(decision, reference_price=50000.0)

        self.assertEqual(capped.final_mode, "cash")
        self.assertIn("TRANSFER_REQUIRED_SPOT_TO_FUTURES", capped.rejection_reasons)

    def test_bitget_preflight_rejects_max_open_below_min_quantity(self) -> None:
        from quant_binance.models import DecisionIntent

        class BitgetBelowMinClient(FakeLiveOrderClient):
            exchange_id = "bitget"

            def get_max_openable_quantity(self, *, symbol, pos_side, order_type, open_amount=None):  # type: ignore[no-untyped-def]
                return 0.00005

            def get_exchange_info(self, *, market):  # type: ignore[no-untyped-def]
                return {
                    "symbols": [
                        {
                            "symbol": "BTCUSDT",
                            "raw": {
                                "minTradeNum": "0.0001",
                                "sizeMultiplier": "0.0001",
                                "volumePlace": "4",
                            },
                        }
                    ]
                }

        decision = DecisionIntent(
            decision_id="d-bitget-min-open",
            decision_hash="hash-bitget-min-open",
            snapshot_id="s-bitget-min-open",
            config_version="2026-03-16.v1",
            timestamp=datetime(2026, 3, 16, 0, 5, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.75,
            liquidity_score=0.84,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=86.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=14.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=95.0,
            stop_distance_bps=45.0,
        )
        adapter = DecisionLiveOrderAdapter(BitgetBelowMinClient(), self.settings)  # type: ignore[arg-type]

        built = adapter.build_order_params(decision=decision, reference_price=50000.0)

        self.assertIsNone(built)
        rejection = adapter.pop_last_preflight_rejection()
        assert rejection is not None
        self.assertEqual(rejection["reason"], "BITGET_MAX_OPEN_BELOW_MIN_QTY")

    def test_live_session_auto_transfers_spot_usdt_into_futures_before_entry(self) -> None:
        from quant_binance.models import DecisionIntent

        class TransferRestClient:
            def __init__(self) -> None:
                self.transfers: list[dict[str, object]] = []

            def transfer_wallet_balance(self, **kwargs):  # type: ignore[no-untyped-def]
                self.transfers.append(dict(kwargs))
                return {"status": "SUCCESS", "transferId": "spot-to-futures-1"}

        class AcceptedLiveExecutor:
            def __init__(self) -> None:
                self.calls = 0

            def _exchange_id(self) -> str:
                return "bitget"

            def execute_decision(self, *, decision, reference_price):  # type: ignore[no-untyped-def]
                self.calls += 1
                return type(
                    "LiveOrderResultStub",
                    (),
                    {
                        "symbol": decision.symbol,
                        "market": decision.final_mode,
                        "side": decision.side,
                        "quantity": round(decision.order_intent_notional_usd / reference_price, 8),
                        "accepted": True,
                        "response": {"status": "SUCCESS", "orderId": "live-transfer-futures-1"},
                        "protection_orders": (),
                        "protection_error": "",
                    },
                )()

            def pop_last_preflight_rejection(self):  # type: ignore[no-untyped-def]
                return None

        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(MarketStateStore()),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
        )
        now = datetime(2026, 3, 16, 0, 5, tzinfo=timezone.utc)
        state = SymbolMarketState(
            symbol="BTCUSDT",
            top_of_book=TopOfBook(49999.5, 1.0, 50000.5, 1.2, now),
            last_trade_price=50000.0,
            funding_rate=0.0001,
            open_interest=1000000.0,
            basis_bps=3.0,
            last_update_time=now,
        )
        runtime.dispatcher.store.put(state)
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            rest_client=TransferRestClient(),  # type: ignore[arg-type]
            live_order_executor=AcceptedLiveExecutor(),  # type: ignore[arg-type]
        )
        session.order_tester = None
        session.capital_report = {
            "futures_available_balance_usd": 0.0,
            "futures_execution_balance_usd": 0.0,
            "can_trade_futures_any": False,
            "max_spot_to_futures_transfer_usd": 80.0,
            "capital_transfer_routes": [
                {
                    "source_market": "spot",
                    "target_market": "futures",
                    "asset": "USDT",
                    "transferable_usd": 80.0,
                }
            ],
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        refresh_calls: list[tuple[str, str]] = []

        def fake_refresh(*, symbol, timestamp, stage, reason):  # type: ignore[no-untyped-def]
            refresh_calls.append((stage, reason))
            if reason == "auto_transfer_spot_to_futures":
                session.capital_report = {
                    "futures_available_balance_usd": 60.0,
                    "futures_execution_balance_usd": 60.0,
                    "can_trade_futures_any": True,
                    "max_spot_to_futures_transfer_usd": 0.0,
                    "capital_transfer_routes": [],
                    "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
                }

        session._refresh_account_state_after_live_order_activity = fake_refresh  # type: ignore[method-assign]
        decision = DecisionIntent(
            decision_id="d-auto-transfer-futures",
            decision_hash="hash-auto-transfer-futures",
            snapshot_id="s-auto-transfer-futures",
            config_version="2026-03-16.v1",
            timestamp=now,
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.75,
            liquidity_score=0.84,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=86.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=14.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=95.0,
            stop_distance_bps=45.0,
        )

        session._record_decision(decision=decision, state=state, timestamp=now)

        self.assertEqual(len(session.rest_client.transfers), 1)
        self.assertEqual(session.rest_client.transfers[0]["source_market"], "spot")
        self.assertEqual(session.rest_client.transfers[0]["target_market"], "futures")
        self.assertEqual(session.rest_client.transfers[0]["asset"], "USDT")
        self.assertEqual(len(session.live_orders), 1)
        self.assertIn("BTCUSDT", session.paper_positions)
        self.assertIn(("capital_transfer", "auto_transfer_spot_to_futures"), refresh_calls)

    def test_live_session_auto_transfers_futures_usdt_into_spot_before_entry(self) -> None:
        from quant_binance.models import DecisionIntent

        class TransferRestClient:
            def __init__(self) -> None:
                self.transfers: list[dict[str, object]] = []

            def transfer_wallet_balance(self, **kwargs):  # type: ignore[no-untyped-def]
                self.transfers.append(dict(kwargs))
                return {"status": "SUCCESS", "transferId": "futures-to-spot-1"}

        class AcceptedLiveExecutor:
            def _exchange_id(self) -> str:
                return "binance"

            def execute_decision(self, *, decision, reference_price):  # type: ignore[no-untyped-def]
                return type(
                    "LiveOrderResultStub",
                    (),
                    {
                        "symbol": decision.symbol,
                        "market": decision.final_mode,
                        "side": decision.side,
                        "quantity": round(decision.order_intent_notional_usd / reference_price, 8),
                        "accepted": True,
                        "response": {"status": "SUCCESS", "orderId": "live-transfer-spot-1"},
                        "protection_orders": (),
                        "protection_error": "",
                    },
                )()

            def pop_last_preflight_rejection(self):  # type: ignore[no-untyped-def]
                return None

        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(MarketStateStore()),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
        )
        now = datetime(2026, 3, 16, 0, 10, tzinfo=timezone.utc)
        state = SymbolMarketState(
            symbol="BTCUSDT",
            top_of_book=TopOfBook(49999.5, 1.0, 50000.5, 1.2, now),
            last_trade_price=50000.0,
            funding_rate=0.0001,
            open_interest=1000000.0,
            basis_bps=3.0,
            last_update_time=now,
        )
        runtime.dispatcher.store.put(state)
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            rest_client=TransferRestClient(),  # type: ignore[arg-type]
            live_order_executor=AcceptedLiveExecutor(),  # type: ignore[arg-type]
        )
        session.order_tester = None
        session.capital_report = {
            "spot_available_balance_usd": 0.0,
            "can_trade_spot_any": False,
            "max_futures_to_spot_transfer_usd": 80.0,
            "capital_transfer_routes": [
                {
                    "source_market": "futures",
                    "target_market": "spot",
                    "asset": "USDT",
                    "transferable_usd": 80.0,
                }
            ],
            "spot_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.0001}],
            "spot_execution_routes": [],
        }
        refresh_calls: list[tuple[str, str]] = []

        def fake_refresh(*, symbol, timestamp, stage, reason):  # type: ignore[no-untyped-def]
            refresh_calls.append((stage, reason))
            if reason == "auto_transfer_futures_to_spot":
                session.capital_report = {
                    "spot_available_balance_usd": 40.0,
                    "can_trade_spot_any": True,
                    "max_futures_to_spot_transfer_usd": 0.0,
                    "capital_transfer_routes": [],
                    "spot_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.0001}],
                    "spot_execution_routes": [],
                }

        session._refresh_account_state_after_live_order_activity = fake_refresh  # type: ignore[method-assign]
        decision = DecisionIntent(
            decision_id="d-auto-transfer-spot",
            decision_hash="hash-auto-transfer-spot",
            snapshot_id="s-auto-transfer-spot",
            config_version="2026-03-16.v1",
            timestamp=now,
            symbol="BTCUSDT",
            candidate_mode="spot",
            final_mode="spot",
            side="long",
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.75,
            liquidity_score=0.84,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=86.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=14.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=25.0,
            stop_distance_bps=45.0,
        )

        session._record_decision(decision=decision, state=state, timestamp=now)

        self.assertEqual(len(session.rest_client.transfers), 1)
        self.assertEqual(session.rest_client.transfers[0]["source_market"], "futures")
        self.assertEqual(session.rest_client.transfers[0]["target_market"], "spot")
        self.assertEqual(session.rest_client.transfers[0]["asset"], "USDT")
        self.assertEqual(len(session.live_orders), 1)
        self.assertIn("BTCUSDT", session.paper_positions)
        self.assertIn(("capital_transfer", "auto_transfer_futures_to_spot"), refresh_calls)

    def test_live_session_auto_transfers_futures_btc_into_spot_cross_quote_entry(self) -> None:
        from quant_binance.models import DecisionIntent

        class TransferRestClient:
            def __init__(self) -> None:
                self.transfers: list[dict[str, object]] = []

            def transfer_wallet_balance(self, **kwargs):  # type: ignore[no-untyped-def]
                self.transfers.append(dict(kwargs))
                return {"status": "SUCCESS", "transferId": "futures-btc-to-spot-1"}

        class AcceptedLiveExecutor:
            def _exchange_id(self) -> str:
                return "binance"

            def execute_decision(self, *, decision, reference_price):  # type: ignore[no-untyped-def]
                return type(
                    "LiveOrderResultStub",
                    (),
                    {
                        "symbol": decision.symbol,
                        "market": decision.final_mode,
                        "side": decision.side,
                        "quantity": round(decision.order_intent_notional_usd / reference_price, 8),
                        "accepted": True,
                        "response": {"status": "SUCCESS", "orderId": "live-transfer-ethbtc-1"},
                        "protection_orders": (),
                        "protection_error": "",
                    },
                )()

            def pop_last_preflight_rejection(self):  # type: ignore[no-untyped-def]
                return None

        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(MarketStateStore()),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
        )
        now = datetime(2026, 3, 16, 0, 15, tzinfo=timezone.utc)
        state = SymbolMarketState(
            symbol="ETHUSDT",
            top_of_book=TopOfBook(2999.5, 1.0, 3000.5, 1.2, now),
            last_trade_price=3000.0,
            funding_rate=0.0001,
            open_interest=1000000.0,
            basis_bps=3.0,
            last_update_time=now,
        )
        runtime.dispatcher.store.put(state)
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            rest_client=TransferRestClient(),  # type: ignore[arg-type]
            live_order_executor=AcceptedLiveExecutor(),  # type: ignore[arg-type]
        )
        session.order_tester = None
        session.capital_report = {
            "spot_available_balance_usd": 0.0,
            "can_trade_spot_any": False,
            "max_futures_to_spot_transfer_usd": 500.0,
            "capital_transfer_routes": [
                {
                    "source_market": "futures",
                    "target_market": "spot",
                    "asset": "BTC",
                    "transferable_usd": 500.0,
                    "route_type": "wallet_transfer",
                    "note": "Futures BTC can be transferred to spot and used on direct/cross-quote spot routes when the quote asset matches.",
                }
            ],
            "spot_requirements": [{"symbol": "ETHUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
            "spot_execution_routes": [
                {
                    "target_symbol": "ETHUSDT",
                    "execution_symbol": "ETHBTC",
                    "base_asset": "ETH",
                    "quote_asset": "BTC",
                    "funding_asset": "BTC",
                    "funding_source_market": "futures",
                    "route_type": "transfer_cross_quote",
                    "requires_wallet_transfer": True,
                    "free_balance": 0.01,
                    "free_balance_usd": 500.0,
                    "min_notional_usd": 5.0,
                    "min_quantity": 0.001,
                }
            ],
        }
        refresh_calls: list[tuple[str, str]] = []

        def fake_refresh(*, symbol, timestamp, stage, reason):  # type: ignore[no-untyped-def]
            refresh_calls.append((stage, reason))

        session._refresh_account_state_after_live_order_activity = fake_refresh  # type: ignore[method-assign]
        decision = DecisionIntent(
            decision_id="d-auto-transfer-spot-btc",
            decision_hash="hash-auto-transfer-spot-btc",
            snapshot_id="s-auto-transfer-spot-btc",
            config_version="2026-03-16.v1",
            timestamp=now,
            symbol="ETHUSDT",
            candidate_mode="spot",
            final_mode="spot",
            side="long",
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.75,
            liquidity_score=0.84,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=86.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=14.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=95.0,
            stop_distance_bps=45.0,
        )

        session._record_decision(decision=decision, state=state, timestamp=now)

        self.assertEqual(len(session.rest_client.transfers), 1)
        self.assertEqual(session.rest_client.transfers[0]["source_market"], "futures")
        self.assertEqual(session.rest_client.transfers[0]["target_market"], "spot")
        self.assertEqual(session.rest_client.transfers[0]["asset"], "BTC")
        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["response"]["status"], "SUCCESS")
        self.assertIn(("capital_transfer", "auto_transfer_futures_to_spot"), refresh_calls)
