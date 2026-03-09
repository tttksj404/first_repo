from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from quant_binance.data.futures_stream import (
    build_futures_streams,
    parse_futures_book_ticker_event,
    parse_mark_price_event,
)
from quant_binance.data.snapshot_builder import SnapshotBuilder
from quant_binance.data.spot_stream import (
    build_spot_streams,
    build_subscribe_message as build_spot_subscribe_message,
    parse_book_ticker_event,
    parse_kline_event,
    parse_spot_trade_event,
)
from quant_binance.data.state import KlineBar, SymbolMarketState, TopOfBook
from quant_binance.execution.router import ExecutionRouter
from quant_binance.models import FeatureVector
from quant_binance.settings import Settings
from quant_binance.strategy.regime import evaluate_snapshot


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


def make_features() -> FeatureVector:
    return FeatureVector(
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


class QuantBinanceDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def test_build_spot_streams_and_subscribe_message(self) -> None:
        streams = build_spot_streams("BTCUSDT", ("1m", "5m"))
        self.assertEqual(
            streams,
            ["btcusdt@trade", "btcusdt@bookTicker", "btcusdt@kline_1m", "btcusdt@kline_5m"],
        )
        message = build_spot_subscribe_message(streams, request_id=7)
        self.assertEqual(message["method"], "SUBSCRIBE")
        self.assertEqual(message["id"], 7)

    def test_parse_spot_events(self) -> None:
        trade = parse_spot_trade_event({"s": "BTCUSDT", "p": "50000.1", "q": "0.12", "E": 1710000000000, "m": True})
        self.assertEqual(trade.symbol, "BTCUSDT")
        self.assertTrue(trade.is_buyer_maker)

        book = parse_book_ticker_event({"b": "49999.5", "B": "1.2", "a": "50000.5", "A": "1.8", "u": 1710000000000})
        self.assertEqual(book.bid_price, 49999.5)
        self.assertEqual(book.ask_qty, 1.8)

        kline = parse_kline_event(
            {
                "s": "BTCUSDT",
                "k": {
                    "i": "5m",
                    "t": 1710000000000,
                    "T": 1710000299999,
                    "o": "50000.0",
                    "h": "50100.0",
                    "l": "49950.0",
                    "c": "50050.0",
                    "v": "12.3",
                    "q": "615000.0",
                    "x": True,
                },
            }
        )
        self.assertEqual(kline.interval, "5m")
        self.assertTrue(kline.is_closed)

    def test_parse_futures_events(self) -> None:
        streams = build_futures_streams("ETHUSDT", ("1m",))
        self.assertIn("ethusdt@markPrice", streams)
        book = parse_futures_book_ticker_event({"b": "3000", "B": "5", "a": "3000.5", "A": "6", "E": 1710000000000})
        self.assertEqual(book.ask_price, 3000.5)
        mark = parse_mark_price_event({"s": "ETHUSDT", "p": "3000.1", "i": "2999.9", "r": "0.0002", "E": 1710000000000})
        self.assertEqual(mark["symbol"], "ETHUSDT")
        self.assertEqual(mark["funding_rate"], 0.0002)

    def test_snapshot_builder_enforces_5m_boundary(self) -> None:
        decision_time = datetime(2026, 3, 8, 12, 5, 0, tzinfo=timezone.utc)
        state = SymbolMarketState(
            symbol="BTCUSDT",
            top_of_book=TopOfBook(49999.5, 1.0, 50000.5, 1.1, decision_time),
            last_trade_price=50000.0,
            funding_rate=0.0001,
            open_interest=1000000.0,
            basis_bps=4.5,
            last_update_time=decision_time,
        )
        builder = SnapshotBuilder(self.settings)
        snapshot = builder.build(state, make_features(), decision_time)
        self.assertEqual(snapshot.symbol, "BTCUSDT")
        self.assertEqual(snapshot.config_version, self.settings.config_version)

    def test_execution_router_routes_by_mode(self) -> None:
        decision_time = datetime(2026, 3, 8, 12, 5, 0, tzinfo=timezone.utc)
        state = SymbolMarketState(
            symbol="BTCUSDT",
            top_of_book=TopOfBook(49999.5, 1.0, 50000.5, 1.1, decision_time),
            last_trade_price=50000.0,
            funding_rate=0.0001,
            open_interest=1000000.0,
            basis_bps=4.5,
            last_update_time=decision_time,
        )
        snapshot = SnapshotBuilder(self.settings).build(state, make_features(), decision_time)
        decision = evaluate_snapshot(
            snapshot,
            self.settings,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            expected_funding_drag_bps=2.0,
        )
        router = ExecutionRouter()
        order = router.route(decision)
        self.assertIsNotNone(order)
        self.assertEqual(order.mode, "futures")


if __name__ == "__main__":
    unittest.main()
