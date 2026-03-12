from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from quant_binance.data.bitget_polling_ws import BitgetPollingWebSocketClient


class _DummyRestClient:
    def get_klines(self, *, market, symbol, interval, limit):  # type: ignore[no-untyped-def]
        return []


class QuantBinanceBitgetPollingWsTests(unittest.TestCase):
    def test_symbol_poll_interval_enforces_spacing(self) -> None:
        client = BitgetPollingWebSocketClient(
            rest_client=_DummyRestClient(),
            symbols=("BTCUSDT", "ETHUSDT"),
            decision_interval_minutes=5,
            poll_interval_seconds=1.0,
            symbol_poll_interval_seconds=20.0,
        )
        now = datetime(2026, 3, 12, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(client._can_poll_symbol(symbol="BTCUSDT", now=now))
        client._record_symbol_polled(symbol="BTCUSDT", now=now)
        self.assertFalse(client._can_poll_symbol(symbol="BTCUSDT", now=now + timedelta(seconds=10)))
        self.assertTrue(client._can_poll_symbol(symbol="BTCUSDT", now=now + timedelta(seconds=20)))

    def test_rate_limit_backoff_escalates_exponentially(self) -> None:
        client = BitgetPollingWebSocketClient(
            rest_client=_DummyRestClient(),
            symbols=("BTCUSDT",),
            decision_interval_minutes=5,
            poll_interval_seconds=1.0,
            symbol_poll_interval_seconds=5.0,
            rate_limit_backoff_initial_seconds=5.0,
            rate_limit_backoff_max_seconds=60.0,
        )
        now = datetime(2026, 3, 12, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(
            client._record_rate_limit(
                now=now,
                error=RuntimeError("Bitget HTTP 429 Too Many Requests: code=429 msg=Too Many Requests"),
            )
        )
        self.assertEqual(client._rate_limit_backoff_until, now + timedelta(seconds=5.0))
        self.assertEqual(client._next_rate_limit_backoff_seconds, 10.0)

        second_now = now + timedelta(seconds=1)
        self.assertTrue(
            client._record_rate_limit(
                now=second_now,
                error=RuntimeError("Bitget HTTP 429 Too Many Requests: code=429 msg=Too Many Requests"),
            )
        )
        self.assertEqual(client._rate_limit_backoff_until, second_now + timedelta(seconds=10.0))
        self.assertEqual(client._next_rate_limit_backoff_seconds, 20.0)

    def test_non_rate_limit_error_does_not_start_backoff(self) -> None:
        client = BitgetPollingWebSocketClient(
            rest_client=_DummyRestClient(),
            symbols=("BTCUSDT",),
            decision_interval_minutes=5,
            poll_interval_seconds=1.0,
            symbol_poll_interval_seconds=5.0,
        )
        now = datetime(2026, 3, 12, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(
            client._record_rate_limit(
                now=now,
                error=RuntimeError("Bitget HTTP 400 Bad Request: code=40762 msg=The order amount exceeds the balance"),
            )
        )
        self.assertIsNone(client._rate_limit_backoff_until)

    def test_select_latest_closed_candle_ignores_open_candle(self) -> None:
        client = BitgetPollingWebSocketClient(
            rest_client=_DummyRestClient(),
            symbols=("BTCUSDT",),
            decision_interval_minutes=5,
            poll_interval_seconds=1.0,
            symbol_poll_interval_seconds=5.0,
        )
        # 00:55 candle is still open at 00:57; 00:50 candle is the latest closed.
        candles = [
            {"open_time": 1741737000000, "open_price": 1, "high_price": 1, "low_price": 1, "close_price": 1, "base_volume": 1, "quote_volume": 1},  # 00:50
            {"open_time": 1741737300000, "open_price": 1, "high_price": 1, "low_price": 1, "close_price": 1, "base_volume": 1, "quote_volume": 1},  # 00:55
        ]
        now_ms = 1741737420000  # 00:57:00
        selected = client._select_latest_closed_candle(candles=candles, now_ms=now_ms)
        self.assertIsNotNone(selected)
        assert selected is not None
        candle, close_time_ms = selected
        self.assertEqual(int(candle["open_time"]), 1741737000000)
        self.assertEqual(close_time_ms, 1741737299999)


if __name__ == "__main__":
    unittest.main()
