from __future__ import annotations

import os
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from quant_binance.exchange import ExchangeCredentials, resolve_exchange_id, runtime_readiness
from quant_binance.execution.bitget_rest import BitgetRestClient, sign_bitget_request
from quant_binance.execution.live_order_adapter import DecisionLiveOrderAdapter
from quant_binance.execution.order_test_adapter import DecisionOrderTestAdapter
from quant_binance.models import DecisionIntent
from quant_binance.runtime import run_paper_live_test_order_mode
from quant_binance.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class FakeBitgetLiveClient:
    exchange_id = "bitget"

    def __init__(self) -> None:
        self.leverage_calls: list[tuple[str, int]] = []
        self.orders: list[tuple[str, dict[str, object]]] = []

    def set_futures_leverage(self, *, symbol, leverage):  # type: ignore[no-untyped-def]
        self.leverage_calls.append((symbol, leverage))
        return {"symbol": symbol, "leverage": leverage}

    def place_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        self.orders.append((market, order_params))
        return {"status": "SUCCESS", "orderId": "bitget-1"}


class BackoffBitgetRestClient(BitgetRestClient):
    def __init__(self) -> None:
        super().__init__(
            credentials=ExchangeCredentials(
                exchange_id="bitget",
                api_key="key",
                api_secret="secret",
                api_passphrase="passphrase",
            )
        )
        self.order_sizes: list[float] = []

    def send(self, request):  # type: ignore[no-untyped-def]
        url = request.full_url
        if "/api/v2/mix/account/account" in url:
            return {"code": "00000", "data": {"posMode": "one_way_mode"}}
        if "/api/v2/mix/order/place-order" in url:
            raw = (request.data or b"{}").decode("utf-8")
            payload = json.loads(raw)
            size = float(payload.get("size", 0.0))
            self.order_sizes.append(size)
            if len(self.order_sizes) < 3:
                raise RuntimeError(
                    "Bitget HTTP 400 Bad Request for POST https://api.bitget.com/api/v2/mix/order/place-order: "
                    "code=40762 msg=The order amount exceeds the balance"
                )
            return {"code": "00000", "msg": "success", "data": {"orderId": "bitget-retry-ok"}}
        return {"code": "00000", "data": {}}


class AlwaysFailBalanceBitgetRestClient(BitgetRestClient):
    def __init__(self) -> None:
        super().__init__(
            credentials=ExchangeCredentials(
                exchange_id="bitget",
                api_key="key",
                api_secret="secret",
                api_passphrase="passphrase",
            )
        )
        self.place_order_calls = 0

    def send(self, request):  # type: ignore[no-untyped-def]
        url = request.full_url
        if "/api/v2/mix/account/account" in url:
            return {"code": "00000", "data": {"posMode": "one_way_mode"}}
        if "/api/v2/mix/order/place-order" in url:
            self.place_order_calls += 1
            raise RuntimeError(
                "Bitget HTTP 400 Bad Request for POST https://api.bitget.com/api/v2/mix/order/place-order: "
                "code=40762 msg=The order amount exceeds the balance"
            )
        return {"code": "00000", "data": {}}


class AccountSnapshotBitgetRestClient(BitgetRestClient):
    def __init__(self) -> None:
        super().__init__(
            credentials=ExchangeCredentials(
                exchange_id="bitget",
                api_key="key",
                api_secret="secret",
                api_passphrase="passphrase",
            )
        )

    def send(self, request):  # type: ignore[no-untyped-def]
        url = request.full_url
        if "/api/v2/mix/account/accounts" in url:
            return {
                "code": "00000",
                "data": [
                    {
                        "marginCoin": "USDT",
                        "available": "37.88836272",
                        "crossedMaxAvailable": "0",
                        "unionAvailable": "17.82432174",
                    }
                ],
            }
        return {"code": "00000", "data": {}}


class QuantBitgetMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def setUp(self) -> None:
        self.fixture_path = ROOT / "tests" / "tmp_bitget_paper_live_order_test.json"
        now = "2026-03-08T12:05:00+00:00"
        self.fixture_path.write_text(
            """
{
  "cycles": [
    {
      "decision_time": "%s",
      "symbol": "BTCUSDT",
      "state": {
        "top_of_book": {
          "bid_price": 49999.5,
          "bid_qty": 1.0,
          "ask_price": 50000.5,
          "ask_qty": 1.2,
          "updated_at": "%s"
        },
        "last_trade_price": 50000.0,
        "funding_rate": 0.0001,
        "open_interest": 1080000.0,
        "basis_bps": 3.0,
        "last_update_time": "%s"
      },
      "primitive_inputs": {
        "ret_1h": 0.05,
        "ret_4h": 0.06,
        "trend_direction": 1,
        "ema_stack_score": 1.0,
        "breakout_reference_price": 49500.0,
        "last_trade_price": 50000.0,
        "atr_14_1h_price": 200.0,
        "quote_volume_5m": 1600.0,
        "quote_volume_1h": 13000.0,
        "buy_taker_volume": 70.0,
        "sell_taker_volume": 30.0,
        "spread_bps": 2.0,
        "probe_slippage_bps": 3.0,
        "depth_usd_within_10bps": 300000.0,
        "order_book_imbalance_std": 0.1,
        "realized_vol_1h": 0.12,
        "realized_vol_4h": 0.17,
        "median_realized_vol_1h_30d": 0.12,
        "funding_rate": 0.0001,
        "open_interest": 1080000.0,
        "open_interest_ema": 1000000.0,
        "basis_bps": 3.0,
        "gross_expected_edge_bps": 30.0
      },
      "history": {
        "returns_1h": [0.01, 0.02, 0.03, 0.04, 0.05],
        "returns_4h": [0.02, 0.03, 0.04, 0.05, 0.06],
        "quote_volume_5m": [1000, 1100, 1200, 1300, 1400],
        "quote_volume_1h": [10000, 10500, 11000, 11500, 12000],
        "realized_vol_1h": [0.1, 0.12, 0.14, 0.16, 0.18],
        "realized_vol_4h": [0.15, 0.17, 0.19, 0.21, 0.23],
        "funding_abs": [0.0001, 0.0002, 0.0003, 0.0004, 0.0005],
        "basis_abs": [2.0, 3.0, 4.0, 5.0, 6.0],
        "oi_surge": [0.05, 0.1, 0.15, 0.2, 0.25]
      }
    }
  ]
}
"""
            % (now, now, now),
            encoding="utf-8",
        )
        self._old_exchange = os.environ.get("EXCHANGE")
        self._old_key = os.environ.pop("BITGET_API_KEY", None)
        self._old_secret = os.environ.pop("BITGET_API_SECRET", None)
        self._old_passphrase = os.environ.pop("BITGET_API_PASSPHRASE", None)

    def tearDown(self) -> None:
        if self.fixture_path.exists():
            self.fixture_path.unlink()
        if self._old_exchange is None:
            os.environ.pop("EXCHANGE", None)
        else:
            os.environ["EXCHANGE"] = self._old_exchange
        if self._old_key is None:
            os.environ.pop("BITGET_API_KEY", None)
        else:
            os.environ["BITGET_API_KEY"] = self._old_key
        if self._old_secret is None:
            os.environ.pop("BITGET_API_SECRET", None)
        else:
            os.environ["BITGET_API_SECRET"] = self._old_secret
        if self._old_passphrase is None:
            os.environ.pop("BITGET_API_PASSPHRASE", None)
        else:
            os.environ["BITGET_API_PASSPHRASE"] = self._old_passphrase

    def _decision(self, *, final_mode: str) -> DecisionIntent:
        return DecisionIntent(
            decision_id="bitget-test-decision",
            decision_hash="hash-1",
            snapshot_id="snapshot-1",
            config_version="2026-03-11.v1",
            timestamp=datetime(2026, 3, 11, 0, 30, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode=final_mode,
            side="long",
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.75,
            liquidity_score=0.84,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=86.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=14.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=2000.0,
            stop_distance_bps=45.0,
        )

    def test_exchange_resolution_defaults_to_bitget(self) -> None:
        os.environ.pop("EXCHANGE", None)
        self.assertEqual(resolve_exchange_id(), "bitget")

    def test_runtime_readiness_tracks_bitget_passphrase_requirement(self) -> None:
        os.environ["BITGET_API_KEY"] = "key"
        os.environ["BITGET_API_SECRET"] = "secret"
        readiness = runtime_readiness("bitget")
        self.assertFalse(readiness.is_ready)
        os.environ["BITGET_API_PASSPHRASE"] = "passphrase"
        readiness = runtime_readiness("bitget")
        self.assertTrue(readiness.is_ready)

    def test_sign_and_request_builders_follow_bitget_headers_and_paths(self) -> None:
        signature = sign_bitget_request(
            secret="secret",
            timestamp_ms=1700000000000,
            method="GET",
            request_path="/api/v2/mix/account/accounts",
            query_string="productType=USDT-FUTURES",
        )
        self.assertTrue(signature)
        client = BitgetRestClient(
            credentials=ExchangeCredentials(
                exchange_id="bitget",
                api_key="key",
                api_secret="secret",
                api_passphrase="passphrase",
            )
        )
        request = client.build_account_request(market="futures")
        self.assertIn("/api/v2/mix/account/accounts", request.full_url)
        parsed = parse_qs(urlparse(request.full_url).query)
        self.assertEqual(parsed["productType"], ["USDT-FUTURES"])
        self.assertEqual(request.headers["Access-key"], "key")
        self.assertEqual(request.headers["Access-passphrase"], "passphrase")

    def test_bitget_order_adapters_build_size_based_payloads(self) -> None:
        decision = self._decision(final_mode="spot")
        preview_client = BitgetRestClient(credentials=None)
        test_adapter = DecisionOrderTestAdapter(preview_client)
        built_preview = test_adapter.build_order_params(decision=decision, reference_price=50000.0)
        self.assertIsNotNone(built_preview)
        assert built_preview is not None
        market, params = built_preview
        self.assertEqual(market, "spot")
        self.assertEqual(params["side"], "buy")
        self.assertEqual(params["size"], "2000.00")
        self.assertNotIn("quoteOrderQty", params)

        live_client = FakeBitgetLiveClient()
        live_adapter = DecisionLiveOrderAdapter(live_client, self.settings)  # type: ignore[arg-type]
        futures_result = live_adapter.execute_decision(
            decision=self._decision(final_mode="futures"),
            reference_price=50000.0,
        )
        self.assertIsNotNone(futures_result)
        assert futures_result is not None
        self.assertEqual(futures_result.market, "futures")
        self.assertEqual(live_client.leverage_calls, [("BTCUSDT", 2)])
        self.assertEqual(live_client.orders[0][1]["productType"], "USDT-FUTURES")

    def test_bitget_paper_live_test_order_mode_runs_without_live_credentials(self) -> None:
        summary = run_paper_live_test_order_mode(
            config_path=CONFIG_PATH,
            fixture_path=self.fixture_path,
            equity_usd=10000.0,
            capacity_usd=5000.0,
            client=BitgetRestClient(credentials=None),
            exchange="bitget",
        )
        self.assertEqual(summary["exchange"], "bitget")
        self.assertEqual(summary["cycle_count"], 1)
        self.assertEqual(summary["tested_order_count"], 1)
        self.assertEqual(summary["account_snapshot"], {})

    def test_bitget_place_order_retries_with_smaller_size_on_balance_error(self) -> None:
        client = BackoffBitgetRestClient()
        response = client.place_order(
            market="futures",
            order_params={
                "symbol": "XRPUSDT",
                "productType": "USDT-FUTURES",
                "marginCoin": "USDT",
                "marginMode": "crossed",
                "side": "buy",
                "orderType": "market",
                "size": "120.00000000",
                "reduceOnly": "NO",
                "clientOid": "test-retry",
            },
        )

        self.assertEqual(response["status"], "SUCCESS")
        self.assertGreaterEqual(len(client.order_sizes), 3)
        self.assertLess(client.order_sizes[-1], client.order_sizes[0])
        self.assertAlmostEqual(client.order_sizes[1], round(client.order_sizes[0] * 0.6, 8))

    def test_bitget_place_order_limits_balance_retry_burst(self) -> None:
        client = AlwaysFailBalanceBitgetRestClient()
        with self.assertRaises(RuntimeError):
            client.place_order(
                market="futures",
                order_params={
                    "symbol": "ETHUSDT",
                    "productType": "USDT-FUTURES",
                    "marginCoin": "USDT",
                    "marginMode": "crossed",
                    "side": "buy",
                    "orderType": "market",
                    "size": "0.08000000",
                    "reduceOnly": "NO",
                    "clientOid": "retry-burst-guard",
                },
            )
        self.assertEqual(client.place_order_calls, 3)

    def test_bitget_get_account_includes_effective_available_balance(self) -> None:
        client = AccountSnapshotBitgetRestClient()
        account = client.get_account(market="futures")

        self.assertAlmostEqual(account["availableBalance"], 37.88836272)
        self.assertAlmostEqual(account["unionAvailable"], 17.82432174)
        self.assertAlmostEqual(account["effectiveAvailableBalance"], 17.82432174)


if __name__ == "__main__":
    unittest.main()
