from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.state import SymbolMarketState, TopOfBook
from quant_binance.execution.router import ExecutionRouter
from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs
from quant_binance.live import EventDispatcher, LivePaperRuntime
from quant_binance.service import PaperTradingService
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


class QuantBinanceLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def _make_runtime(self) -> tuple[MarketStateStore, LivePaperRuntime]:
        store = MarketStateStore()
        now = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
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
        return store, runtime

    def test_dispatcher_updates_trade_and_book(self) -> None:
        store, runtime = self._make_runtime()
        runtime.on_payload(
            {
                "stream": "btcusdt@trade",
                "data": {"s": "BTCUSDT", "p": "50010", "q": "0.1", "E": 1770000000000, "m": False},
            },
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        runtime.on_payload(
            {
                "stream": "btcusdt@bookTicker",
                "data": {"s": "BTCUSDT", "b": "50009", "B": "2", "a": "50011", "A": "1", "E": 1770000000000},
            },
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        state = store.get("BTCUSDT")
        assert state is not None
        self.assertEqual(state.last_trade_price, 50010.0)
        self.assertEqual(state.top_of_book.bid_price, 50009.0)

    def test_live_runtime_triggers_on_closed_5m_kline(self) -> None:
        _, runtime = self._make_runtime()
        decision = runtime.on_payload(
            {
                "stream": "btcusdt@kline_5m",
                "data": {
                    "s": "BTCUSDT",
                    "k": {
                        "i": "5m",
                        "t": 1770000000000,
                        "T": 1770000300000,
                        "o": "49900",
                        "h": "50100",
                        "l": "49850",
                        "c": "50050",
                        "v": "12",
                        "q": "600000",
                        "x": True,
                    },
                },
            },
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.symbol, "BTCUSDT")
        self.assertIn(decision.final_mode, {"futures", "spot", "cash"})

    def test_live_runtime_triggers_on_real_binance_closed_5m_kline_timestamp(self) -> None:
        _, runtime = self._make_runtime()
        decision = runtime.on_payload(
            {
                "stream": "btcusdt@kline_5m",
                "data": {
                    "s": "BTCUSDT",
                    "k": {
                        "i": "5m",
                        "t": 1770000000000,
                        "T": 1770000299999,
                        "o": "49900",
                        "h": "50100",
                        "l": "49850",
                        "c": "50050",
                        "v": "12",
                        "q": "600000",
                        "x": True,
                    },
                },
            },
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        self.assertIsNotNone(decision)

    def test_live_runtime_ignores_closed_non_decision_interval_kline(self) -> None:
        _, runtime = self._make_runtime()
        decision = runtime.on_payload(
            {
                "stream": "btcusdt@kline_1h",
                "data": {
                    "s": "BTCUSDT",
                    "k": {
                        "i": "1h",
                        "t": 1770000000000,
                        "T": 1770003599999,
                        "o": "49900",
                        "h": "50100",
                        "l": "49850",
                        "c": "50050",
                        "v": "12",
                        "q": "600000",
                        "x": True,
                    },
                },
            },
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        self.assertIsNone(decision)

    def test_live_runtime_skips_ineligible_symbols(self) -> None:
        _, runtime = self._make_runtime()
        runtime.eligible_symbols = {"ETHUSDT"}
        decision = runtime.on_payload(
            {
                "stream": "btcusdt@kline_5m",
                "data": {
                    "s": "BTCUSDT",
                    "k": {
                        "i": "5m",
                        "t": 1770000000000,
                        "T": 1770000300000,
                        "o": "49900",
                        "h": "50100",
                        "l": "49850",
                        "c": "50050",
                        "v": "12",
                        "q": "600000",
                        "x": True,
                    },
                },
            },
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        self.assertIsNone(decision)


if __name__ == "__main__":
    unittest.main()
