from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.state import KlineBar, SpotTrade, SymbolMarketState, TopOfBook
from quant_binance.execution.binance_rest import BinanceCredentials, BinanceRestClient
from quant_binance.features.extractor import MarketFeatureExtractor
from quant_binance.settings import Settings
from quant_binance.strategy.edge import ConditionalEdgeLookup


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class QuantBinanceExchangeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def _build_state(self) -> SymbolMarketState:
        now = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
        state = SymbolMarketState(
            symbol="BTCUSDT",
            top_of_book=TopOfBook(49999.5, 3.0, 50000.5, 2.0, now),
            last_trade_price=50000.0,
            funding_rate=0.0001,
            open_interest=1100000.0,
            basis_bps=3.0,
            last_update_time=now,
        )
        for idx in range(130):
            close_time = now - timedelta(hours=130 - idx)
            state.klines.setdefault("1h", []).append(
                KlineBar(
                    symbol="BTCUSDT",
                    interval="1h",
                    start_time=close_time - timedelta(hours=1),
                    close_time=close_time,
                    open_price=48000.0 + idx * 5,
                    high_price=48100.0 + idx * 5,
                    low_price=47950.0 + idx * 5,
                    close_price=48020.0 + idx * 5,
                    volume=10 + idx,
                    quote_volume=500000 + idx * 1000,
                    is_closed=True,
                )
            )
        for idx in range(130):
            close_time = now - timedelta(hours=4 * (130 - idx))
            state.klines.setdefault("4h", []).append(
                KlineBar(
                    symbol="BTCUSDT",
                    interval="4h",
                    start_time=close_time - timedelta(hours=4),
                    close_time=close_time,
                    open_price=47000.0 + idx * 10,
                    high_price=47200.0 + idx * 10,
                    low_price=46900.0 + idx * 10,
                    close_price=47150.0 + idx * 10,
                    volume=40 + idx,
                    quote_volume=2000000 + idx * 3000,
                    is_closed=True,
                )
            )
        for idx in range(50):
            close_time = now - timedelta(minutes=5 * (50 - idx))
            state.klines.setdefault("5m", []).append(
                KlineBar(
                    symbol="BTCUSDT",
                    interval="5m",
                    start_time=close_time - timedelta(minutes=5),
                    close_time=close_time,
                    open_price=49900.0 + idx,
                    high_price=50020.0 + idx,
                    low_price=49880.0 + idx,
                    close_price=49950.0 + idx,
                    volume=2 + idx * 0.1,
                    quote_volume=100000 + idx * 500,
                    is_closed=True,
                )
            )
        for idx in range(90):
            close_time = now - timedelta(minutes=90 - idx)
            state.klines.setdefault("1m", []).append(
                KlineBar(
                    symbol="BTCUSDT",
                    interval="1m",
                    start_time=close_time - timedelta(minutes=1),
                    close_time=close_time,
                    open_price=49980.0 + idx * 0.6,
                    high_price=50010.0 + idx * 0.6,
                    low_price=49960.0 + idx * 0.6,
                    close_price=49990.0 + idx * 0.6,
                    volume=0.5 + idx * 0.02,
                    quote_volume=15000 + idx * 120,
                    is_closed=True,
                )
            )
        for idx in range(40):
            trade_time = now - timedelta(minutes=40 - idx)
            state.trades.append(
                SpotTrade(
                    symbol="BTCUSDT",
                    price=49950.0 + idx,
                    quantity=0.1 + idx * 0.01,
                    event_time=trade_time,
                    is_buyer_maker=bool(idx % 2),
                )
            )
        state.order_book_imbalance_samples = [0.1, 0.12, 0.08, 0.11, 0.09]
        state.funding_rate_samples = [0.0001, 0.00012, 0.00011, 0.00009]
        state.basis_bps_samples = [2.5, 2.8, 3.1, 3.0]
        state.open_interest_samples = [1000000.0, 1020000.0, 1050000.0, 1080000.0, 1100000.0]
        return state

    def test_market_feature_extractor_builds_history_and_primitives(self) -> None:
        state = self._build_state()
        lookup = ConditionalEdgeLookup(min_observations=1)
        lookup.add_observation(
            symbol="BTCUSDT",
            mode="futures",
            predictability_score=80.0,
            trend_direction=1,
            forward_return_bps=28.0,
        )
        extractor = MarketFeatureExtractor(self.settings, edge_lookup=lookup)
        history = extractor.build_history_context(state)
        primitive = extractor.build_primitive_inputs(state)
        self.assertGreater(len(history.returns_1h), 10)
        self.assertEqual(primitive.trend_direction, 1)
        self.assertGreater(primitive.gross_expected_edge_bps, 0.0)
        self.assertGreater(primitive.open_interest_ema, 0.0)

    def test_market_feature_extractor_uses_intraday_bias_when_hourly_stack_is_ambiguous(self) -> None:
        state = self._build_state()
        now = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
        state.klines["1h"] = []
        for idx in range(130):
            close_time = now - timedelta(hours=130 - idx)
            price = 50000.0
            state.klines["1h"].append(
                KlineBar(
                    symbol="BTCUSDT",
                    interval="1h",
                    start_time=close_time - timedelta(hours=1),
                    close_time=close_time,
                    open_price=price,
                    high_price=price + 20.0,
                    low_price=price - 20.0,
                    close_price=price,
                    volume=10 + idx,
                    quote_volume=500000 + idx * 1000,
                    is_closed=True,
                )
            )
        state.klines["5m"] = []
        for idx in range(50):
            close_time = now - timedelta(minutes=5 * (50 - idx))
            price = 50000.0 - idx * 8.0
            state.klines["5m"].append(
                KlineBar(
                    symbol="BTCUSDT",
                    interval="5m",
                    start_time=close_time - timedelta(minutes=5),
                    close_time=close_time,
                    open_price=price + 5.0,
                    high_price=price + 8.0,
                    low_price=price - 6.0,
                    close_price=price,
                    volume=3 + idx * 0.1,
                    quote_volume=120000 + idx * 400,
                    is_closed=True,
                )
            )
        state.klines["1m"] = []
        for idx in range(90):
            close_time = now - timedelta(minutes=90 - idx)
            price = 49800.0 - idx * 1.5
            state.klines["1m"].append(
                KlineBar(
                    symbol="BTCUSDT",
                    interval="1m",
                    start_time=close_time - timedelta(minutes=1),
                    close_time=close_time,
                    open_price=price + 1.0,
                    high_price=price + 2.0,
                    low_price=price - 2.0,
                    close_price=price,
                    volume=1.0 + idx * 0.01,
                    quote_volume=10000 + idx * 80,
                    is_closed=True,
                )
            )

        extractor = MarketFeatureExtractor(self.settings)
        primitive = extractor.build_primitive_inputs(state)

        self.assertEqual(primitive.trend_direction, -1)
        self.assertGreaterEqual(primitive.ema_stack_score, 0.35)

    def test_rest_client_builds_account_open_orders_and_test_order_requests(self) -> None:
        client = BinanceRestClient(
            credentials=BinanceCredentials(api_key="key", api_secret="secret")
        )
        account_request = client.build_account_request(market="spot")
        self.assertIn("/api/v3/account", account_request.full_url)

        open_orders_request = client.build_open_orders_request(market="futures", symbol="BTCUSDT")
        parsed_open = parse_qs(urlparse(open_orders_request.full_url).query)
        self.assertEqual(parsed_open["symbol"], ["BTCUSDT"])

        order_params = client.build_order_params(
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            quantity=0.01,
        )
        test_order_request = client.build_test_order_request(market="futures", order_params=order_params)
        self.assertIn("/fapi/v1/order/test", test_order_request.full_url)
        parsed_order = parse_qs(urlparse(test_order_request.full_url).query)
        self.assertEqual(parsed_order["symbol"], ["BTCUSDT"])
        self.assertEqual(parsed_order["side"], ["BUY"])

    def test_market_store_accumulates_histories_for_extractor(self) -> None:
        store = MarketStateStore()
        now = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
        store.put(
            SymbolMarketState(
                symbol="BTCUSDT",
                top_of_book=TopOfBook(49999.0, 1.0, 50001.0, 1.2, now),
                last_trade_price=50000.0,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=2.0,
                last_update_time=now,
            )
        )
        store.apply_mark_price(
            symbol="BTCUSDT",
            funding_rate=0.0002,
            mark_price=50010.0,
            index_price=50000.0,
            event_time=now,
        )
        store.apply_open_interest(symbol="BTCUSDT", open_interest=1050000.0, event_time=now)
        state = store.get("BTCUSDT")
        assert state is not None
        self.assertEqual(len(state.funding_rate_samples), 1)
        self.assertEqual(len(state.basis_bps_samples), 1)
        self.assertEqual(len(state.open_interest_samples), 1)


if __name__ == "__main__":
    unittest.main()
