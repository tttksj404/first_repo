from __future__ import annotations

import json
import socket
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

from quant_binance.execution.binance_rest import BinanceCredentials, BinanceRestClient
from quant_binance.execution.bitget_rest import BitgetRestClient


class QuantBinanceRestTransportTests(unittest.TestCase):
    def test_bitget_send_surfaces_dns_resolution_target(self) -> None:
        client = BitgetRestClient()
        request = client.build_public_request(path="/api/v2/spot/public/symbols")

        with patch(
            "quant_binance.execution.bitget_rest.urlopen",
            side_effect=URLError(socket.gaierror(8, "nodename nor servname provided, or not known")),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                r"Bitget transport error .*api\.bitget\.com.*DNS resolution failed",
            ):
                client.send(request)

    def test_binance_send_surfaces_dns_resolution_target(self) -> None:
        client = BinanceRestClient(
            credentials=BinanceCredentials(api_key="key", api_secret="secret"),
        )
        request = client.build_public_request(market="spot", path="/api/v3/exchangeInfo")

        with patch(
            "quant_binance.execution.binance_rest.urlopen",
            side_effect=URLError(socket.gaierror(8, "nodename nor servname provided, or not known")),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                r"Binance transport error .*api\.binance\.com.*DNS resolution failed",
            ):
                client.send(request)

    def test_binance_builds_universal_transfer_request(self) -> None:
        client = BinanceRestClient(
            credentials=BinanceCredentials(api_key="key", api_secret="secret"),
        )

        request = client.build_asset_transfer_request(
            source_market="spot",
            target_market="futures",
            asset="USDT",
            amount=12.5,
        )

        parsed = parse_qs(urlparse(request.full_url).query)
        self.assertEqual(parsed["type"], ["MAIN_UMFUTURE"])
        self.assertEqual(parsed["asset"], ["USDT"])
        self.assertEqual(parsed["amount"], ["12.50000000"])

    def test_bitget_builds_wallet_transfer_request(self) -> None:
        client = BitgetRestClient(
            credentials=type(
                "Creds",
                (),
                {"api_key": "key", "api_secret": "secret", "api_passphrase": "pass"},
            )(),
        )

        with patch("quant_binance.execution.bitget_rest.time.time", return_value=1770000000.0):
            request = client.build_wallet_transfer_request(
                source_market="spot",
                target_market="futures",
                asset="USDT",
                amount=7.5,
                client_oid="transfer-1",
            )

        self.assertEqual(request.full_url, "https://api.bitget.com/api/v2/spot/wallet/transfer")
        assert request.data is not None
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["fromType"], "spot")
        self.assertEqual(payload["toType"], "usdt_futures")
        self.assertEqual(payload["coin"], "USDT")
        self.assertEqual(payload["amount"], "7.50000000")
        self.assertEqual(payload["clientOid"], "transfer-1")


if __name__ == "__main__":
    unittest.main()
