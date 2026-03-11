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

    def set_futures_leverage(self, *, symbol, leverage):  # type: ignore[no-untyped-def]
        self.leverage_calls.append((symbol, leverage))
        return {"symbol": symbol, "leverage": leverage}

    def place_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        self.calls += 1
        return {"status": "FILLED", "market": market, "orderId": self.calls}


class BitgetMarginCapClient(FakeLiveOrderClient):
    exchange_id = "bitget"

    def __init__(
        self,
        *,
        available_balance_usd: float,
        leverage_response: dict[str, object] | None = None,
        leverage_error: RuntimeError | None = None,
    ) -> None:
        super().__init__()
        self.available_balance_usd = available_balance_usd
        self.leverage_response = leverage_response if leverage_response is not None else {"leverage": 7}
        self.leverage_error = leverage_error
        self.last_order_params: dict[str, object] | None = None

    def set_futures_leverage(self, *, symbol, leverage):  # type: ignore[no-untyped-def]
        self.leverage_calls.append((symbol, leverage))
        if self.leverage_error is not None:
            raise self.leverage_error
        return dict(self.leverage_response)

    def get_account(self, *, market):  # type: ignore[no-untyped-def]
        if market != "futures":
            return {}
        return {"availableBalance": self.available_balance_usd}

    def place_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.last_order_params = dict(order_params)
        return {"status": "FILLED", "market": market, "orderId": self.calls}


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

    def test_live_order_adapter_caps_bitget_futures_size_by_available_balance(self) -> None:
        from quant_binance.models import DecisionIntent

        settings = self._load_settings_for_profile("alpha_max")
        decision = DecisionIntent(
            decision_id="d-bitget-cap",
            decision_hash="hash-bitget-cap",
            snapshot_id="s-bitget-cap",
            config_version="2026-03-11.v1",
            timestamp=datetime(2026, 3, 11, 8, 0, tzinfo=timezone.utc),
            symbol="XRPUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.58,
            volume_confirmation=0.57,
            liquidity_score=0.62,
            volatility_penalty=0.72,
            overheat_penalty=0.5,
            predictability_score=59.7,
            gross_expected_edge_bps=11.4,
            net_expected_edge_bps=1.2,
            estimated_round_trip_cost_bps=10.1,
            order_intent_notional_usd=1245.607477,
            stop_distance_bps=134.8,
        )
        client = BitgetMarginCapClient(
            available_balance_usd=40.0,
            leverage_response={"leverage": 7},
        )
        adapter = DecisionLiveOrderAdapter(client, settings)  # type: ignore[arg-type]

        result = adapter.execute_decision(decision=decision, reference_price=8.185)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIsNotNone(client.last_order_params)
        assert client.last_order_params is not None
        capped_size = float(client.last_order_params["size"])
        uncapped_size = decision.order_intent_notional_usd / 8.185
        self.assertLess(capped_size, uncapped_size)
        expected_max_notional = 40.0 * 7.0 * (1.0 - settings.cash_reserve.when_futures_enabled) * 0.9
        self.assertLessEqual(capped_size * 8.185, expected_max_notional + 1e-6)

    def test_live_order_adapter_handles_bitget_leverage_margin_error_with_conservative_cap(self) -> None:
        from quant_binance.models import DecisionIntent

        settings = self._load_settings_for_profile("alpha_max")
        decision = DecisionIntent(
            decision_id="d-bitget-lev-fail",
            decision_hash="hash-bitget-lev-fail",
            snapshot_id="s-bitget-lev-fail",
            config_version="2026-03-11.v1",
            timestamp=datetime(2026, 3, 11, 8, 15, tzinfo=timezone.utc),
            symbol="XRPUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.63,
            volume_confirmation=0.6,
            liquidity_score=0.64,
            volatility_penalty=0.7,
            overheat_penalty=0.45,
            predictability_score=62.6,
            gross_expected_edge_bps=12.0,
            net_expected_edge_bps=2.0,
            estimated_round_trip_cost_bps=10.2,
            order_intent_notional_usd=582.0,
            stop_distance_bps=128.0,
        )
        client = BitgetMarginCapClient(
            available_balance_usd=40.0,
            leverage_error=RuntimeError(
                "Bitget HTTP 400 Bad Request for POST https://api.bitget.com/api/v2/mix/account/set-leverage: "
                "code=40893 msg=Unable to update the leverage factor of this position, there is not enough margin!"
            ),
        )
        adapter = DecisionLiveOrderAdapter(client, settings)  # type: ignore[arg-type]

        result = adapter.execute_decision(decision=decision, reference_price=8.185)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(client.leverage_calls, [("XRPUSDT", 6)])
        assert client.last_order_params is not None
        capped_size = float(client.last_order_params["size"])
        expected_max_notional = 40.0 * 1.0 * (1.0 - settings.cash_reserve.when_futures_enabled) * 0.9
        self.assertLessEqual(capped_size * 8.185, expected_max_notional + 1e-6)

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
