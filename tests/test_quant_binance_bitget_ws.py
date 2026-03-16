from __future__ import annotations

import unittest
from datetime import datetime, timezone

from quant_binance.data.bitget_ws import (
    BITGET_MAX_CHANNELS_PER_SUBSCRIBE,
    BitgetWebSocketClient,
    translate_bitget_ws_payload,
)


class QuantBinanceBitgetWebSocketTests(unittest.TestCase):
    def test_translate_spot_trade_payload(self) -> None:
        payload = {
            "arg": {"channel": "trade", "instId": "BTCUSDT"},
            "data": [["1770000000000", "50010.5", "0.25", "sell"]],
        }

        normalized = translate_bitget_ws_payload(payload, market="spot")

        self.assertEqual(
            normalized,
            [
                {
                    "stream": "btcusdt@trade",
                    "data": {
                        "s": "BTCUSDT",
                        "p": "50010.5",
                        "q": "0.25",
                        "E": 1770000000000,
                        "m": True,
                    },
                }
            ],
        )

    def test_translate_spot_ticker_payload_to_book_ticker(self) -> None:
        payload = {
            "arg": {"channel": "ticker", "instId": "BTCUSDT"},
            "data": [
                {
                    "bidPr": "50000.0",
                    "bidSz": "2.0",
                    "askPr": "50001.0",
                    "askSz": "1.5",
                    "ts": "1770000001000",
                }
            ],
        }

        normalized = translate_bitget_ws_payload(payload, market="spot")

        self.assertEqual(
            normalized,
            [
                {
                    "stream": "btcusdt@bookTicker",
                    "data": {
                        "s": "BTCUSDT",
                        "b": "50000.0",
                        "B": "2.0",
                        "a": "50001.0",
                        "A": "1.5",
                        "E": 1770000001000,
                    },
                }
            ],
        )

    def test_translate_futures_ticker_payload_to_runtime_events(self) -> None:
        payload = {
            "arg": {"channel": "ticker", "instId": "BTCUSDT"},
            "data": [
                {
                    "bidPr": "50000.0",
                    "bidSz": "2.0",
                    "askPr": "50001.0",
                    "askSz": "1.5",
                    "markPrice": "50002.0",
                    "indexPrice": "49998.0",
                    "fundingRate": "0.0001",
                    "openInterest": "1080000.0",
                    "ts": "1770000002000",
                }
            ],
        }

        normalized = translate_bitget_ws_payload(payload, market="futures")

        self.assertEqual(
            normalized,
            [
                {
                    "stream": "btcusdt@bookTicker",
                    "data": {
                        "s": "BTCUSDT",
                        "b": "50000.0",
                        "B": "2.0",
                        "a": "50001.0",
                        "A": "1.5",
                        "E": 1770000002000,
                        "ps": "BTCUSDT",
                    },
                },
                {
                    "stream": "btcusdt@markPrice",
                    "data": {
                        "s": "BTCUSDT",
                        "p": "50002.0",
                        "i": "49998.0",
                        "r": "0.0001",
                        "E": 1770000002000,
                    },
                },
                {
                    "stream": "btcusdt@openInterest",
                    "data": {
                        "symbol": "BTCUSDT",
                        "openInterest": "1080000.0",
                        "time": 1770000002000,
                    },
                },
            ],
        )

    def test_translate_closed_spot_candle_payload(self) -> None:
        payload = {
            "arg": {"channel": "candle5m", "instId": "BTCUSDT"},
            "data": [["1770000000000", "49900", "50100", "49850", "50050", "12", "600000"]],
        }
        received_at = datetime.fromtimestamp(1770000300, tz=timezone.utc)

        normalized = translate_bitget_ws_payload(payload, market="spot", received_at=received_at)

        self.assertEqual(
            normalized,
            [
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
                }
            ],
        )

    def test_translate_closed_futures_candle_marks_futures_shape(self) -> None:
        payload = {
            "arg": {"channel": "candle5m", "instId": "BTCUSDT"},
            "data": [["1770000000000", "49900", "50100", "49850", "50050", "12", "600000"]],
        }
        received_at = datetime.fromtimestamp(1770000300, tz=timezone.utc)

        normalized = translate_bitget_ws_payload(payload, market="futures", received_at=received_at)

        self.assertEqual(normalized[0]["data"]["ps"], "BTCUSDT")
        self.assertTrue(normalized[0]["data"]["k"]["x"])

    def test_client_suppresses_duplicate_closed_candles(self) -> None:
        client = BitgetWebSocketClient(
            market="spot",
            symbols=("BTCUSDT",),
            intervals=("5m",),
        )
        payload = {
            "arg": {"channel": "candle5m", "instId": "BTCUSDT"},
            "data": [["1770000000000", "49900", "50100", "49850", "50050", "12", "600000"]],
        }
        received_at = datetime.fromtimestamp(1770000300, tz=timezone.utc)

        first = client.normalize_payload(payload, received_at=received_at)
        second = client.normalize_payload(payload, received_at=received_at)

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

    def test_client_uses_stall_watchdog_friendly_connect_kwargs(self) -> None:
        client = BitgetWebSocketClient(
            market="spot",
            symbols=("BTCUSDT",),
            intervals=("5m",),
        )

        kwargs = client._connect_kwargs(ssl_context=None)

        self.assertEqual(kwargs["ssl"], None)
        self.assertEqual(kwargs["ping_interval"], 20)
        self.assertIsNone(kwargs["ping_timeout"])

    def test_client_splits_large_subscribe_payloads_into_safe_batches(self) -> None:
        symbols = tuple(f"SYM{index}USDT" for index in range(12))
        client = BitgetWebSocketClient(
            market="spot",
            symbols=symbols,
            intervals=("5m", "1h", "4h"),
        )

        messages = client.build_subscribe_messages()

        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(message["args"]) <= BITGET_MAX_CHANNELS_PER_SUBSCRIBE for message in messages))


if __name__ == "__main__":
    unittest.main()
