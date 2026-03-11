from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quant_binance.daemon import _build_live_ws_client, run_live_paper_daemon
from quant_binance.data.bitget_ws import BitgetWebSocketClient
from quant_binance.data.rest_seed import seed_market_store_from_rest
from quant_binance.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class FakeRestClient:
    exchange_id = "binance"

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


class FakeBitgetDaemonClient(FakeRestClient):
    exchange_id = "bitget"
    supports_private_reads = False

    def test_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        return {"status": "PREVIEW", "market": market, "request": dict(order_params)}


class FakeShell:
    def __init__(self, *, ws_client_factory, session, backoff_policy, summary_path, state_path):  # type: ignore[no-untyped-def]
        self.ws_client_factory = ws_client_factory
        self.session = session
        self.backoff_policy = backoff_policy
        self.summary_path = summary_path
        self.state_path = state_path

    async def run(self) -> dict[str, object]:
        client = self.ws_client_factory()
        return {
            "status": "ok",
            "client_types": [type(item).__name__ for item in client.clients],
            "rest_sync_enabled": self.session.rest_client is not None,
        }


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

    def test_build_live_ws_client_uses_bitget_adapter(self) -> None:
        client = _build_live_ws_client(
            exchange_id="bitget",
            symbols=("BTCUSDT",),
            allow_insecure_ssl=True,
        )

        self.assertEqual(len(client.clients), 2)
        self.assertTrue(all(isinstance(item, BitgetWebSocketClient) for item in client.clients))
        self.assertEqual(client.clients[0].subscription_args()[0], {"instType": "SPOT", "channel": "trade", "instId": "BTCUSDT"})

    def test_run_live_paper_daemon_starts_bitget_without_private_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            with patch("quant_binance.daemon.build_exchange_rest_client", return_value=FakeBitgetDaemonClient()):
                with patch("quant_binance.daemon.LivePaperShell", FakeShell):
                    result = run_live_paper_daemon(
                        config_path=CONFIG_PATH,
                        output_base_dir=output_dir,
                        exchange="bitget",
                        max_retries=1,
                    )

        self.assertEqual(result["summary"]["status"], "ok")
        self.assertEqual(
            result["summary"]["client_types"],
            ["BitgetWebSocketClient", "BitgetWebSocketClient"],
        )
        self.assertFalse(result["summary"]["rest_sync_enabled"])

    def test_run_live_paper_daemon_requires_credentials_for_bitget_live_orders(self) -> None:
        with tempfile.TemporaryDirectory() as output_dir:
            with patch("quant_binance.daemon.build_exchange_rest_client", return_value=FakeBitgetDaemonClient()):
                with self.assertRaisesRegex(RuntimeError, "BITGET_API_KEY"):
                    run_live_paper_daemon(
                        config_path=CONFIG_PATH,
                        output_base_dir=output_dir,
                        exchange="bitget",
                        execute_live_orders=True,
                    )


if __name__ == "__main__":
    unittest.main()
