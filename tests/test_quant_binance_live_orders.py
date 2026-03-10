from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from quant_binance.execution.live_order_adapter import DecisionLiveOrderAdapter
from quant_binance.learning import OnlineEdgeLearner
from quant_binance.live import EventDispatcher, LivePaperRuntime
from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.state import SymbolMarketState, TopOfBook
from quant_binance.execution.router import ExecutionRouter
from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs
from quant_binance.service import PaperTradingService
from quant_binance.session import LivePaperSession
from quant_binance.settings import Settings


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


class QuantBinanceLiveOrdersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

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
