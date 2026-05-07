from __future__ import annotations

import unittest
from pathlib import Path

from quant_binance.data.rest_seed import seed_market_store_from_rest
from quant_binance.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class FakeRestClient:
    def get_exchange_info(self, *, market):  # type: ignore[no-untyped-def]
        return {
            "symbols": [
                {"symbol": "BTCUSDT"},
            ]
        }

    def get_book_ticker(self, *, market, symbol):  # type: ignore[no-untyped-def]
        return {"bidPrice": "49999.5", "bidQty": "1.0", "askPrice": "50000.5", "askQty": "1.2"}

    def get_mark_price(self, *, symbol):  # type: ignore[no-untyped-def]
        return {"markPrice": "50000.0", "indexPrice": "49995.0", "lastFundingRate": "0.0001"}

    def get_open_interest(self, *, symbol):  # type: ignore[no-untyped-def]
        return {"openInterest": "1080000.0"}

    def get_klines(self, *, market, symbol, interval, limit):  # type: ignore[no-untyped-def]
        base = 1700000000000
        rows = []
        for idx in range(limit):
            open_time = base + idx * 300000
            close_time = open_time + 299999
            rows.append(
                [
                    open_time,
                    "50000.0",
                    "50100.0",
                    "49900.0",
                    "50050.0",
                    "10.0",
                    close_time,
                    "500000.0",
                ]
            )
        return rows


class QuantBinanceDaemonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def test_seed_market_store_from_rest(self) -> None:
        store = seed_market_store_from_rest(
            client=FakeRestClient(),  # type: ignore[arg-type]
            symbols=("BTCUSDT",),
            intervals=("5m", "1h", "4h"),
        )
        state = store.get("BTCUSDT")
        assert state is not None
        self.assertEqual(state.last_trade_price, 50000.0)
        self.assertEqual(len(state.klines["5m"]), 100)
        self.assertEqual(len(state.klines["1h"]), 140)
        self.assertEqual(len(state.funding_rate_samples), 1)


if __name__ == "__main__":
    unittest.main()
