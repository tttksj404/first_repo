from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from quant_binance.exchange import ExchangeCredentials, resolve_exchange_id, runtime_readiness
from quant_binance.execution.bitget_rest import BitgetRestClient, sign_bitget_request
from quant_binance.execution.live_order_adapter import DecisionLiveOrderAdapter
from quant_binance.execution.order_test_adapter import DecisionOrderTestAdapter
from quant_binance.models import DecisionIntent
from quant_binance.runtime import run_paper_live_test_order_mode
from quant_binance.session import LivePaperSession
from quant_binance.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class FakeBitgetLiveClient:
    exchange_id = "bitget"

    def __init__(self) -> None:
        self.leverage_calls: list[tuple[str, int]] = []
        self.orders: list[tuple[str, dict[str, object]]] = []
        self.protection_orders: list[tuple[str, dict[str, object]]] = []

    def set_futures_leverage(self, *, symbol, leverage):  # type: ignore[no-untyped-def]
        self.leverage_calls.append((symbol, leverage))
        return {"symbol": symbol, "leverage": leverage}

    def place_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        self.orders.append((market, order_params))
        return {"status": "SUCCESS", "orderId": "bitget-1"}

    def place_futures_position_tpsl(self, *, order_params):  # type: ignore[no-untyped-def]
        self.protection_orders.append(("futures", order_params))
        return {"status": "SUCCESS", "orderId": "bitget-tpsl-1"}

    def place_spot_plan_order(self, *, order_params):  # type: ignore[no-untyped-def]
        self.protection_orders.append(("spot", order_params))
        return {"status": "SUCCESS", "orderId": "bitget-plan-1"}


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
        with patch("quant_binance.exchange._resolve_env_value") as mock_resolve:
            values = {
                "BITGET_API_KEY": "key",
                "BITGET_API_SECRET": "secret",
                "BITGET_API_PASSPHRASE": "",
            }
            mock_resolve.side_effect = lambda name: values.get(name, "")
            readiness = runtime_readiness("bitget")
            self.assertFalse(readiness.is_ready)
            values["BITGET_API_PASSPHRASE"] = "passphrase"
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
        self.assertEqual(live_client.orders[0][1]["side"], "buy")
        self.assertEqual(live_client.orders[0][1]["tradeSide"], "open")
        self.assertNotIn("holdSide", live_client.orders[0][1])
        self.assertEqual(live_client.protection_orders[0][0], "futures")
        self.assertIn("stopLossTriggerPrice", live_client.protection_orders[0][1])
        self.assertIn("stopSurplusTriggerPrice", live_client.protection_orders[0][1])

    def test_bitget_live_order_ignores_margin_leverage_update_error(self) -> None:
        class FlakyLeverageClient(FakeBitgetLiveClient):
            def set_futures_leverage(self, *, symbol, leverage):  # type: ignore[no-untyped-def]
                raise RuntimeError(
                    'Bitget HTTP 400: {"code":"40893","msg":"Unable to update the leverage factor of this position, there is not enough margin!"}'
                )

        live_client = FlakyLeverageClient()
        live_adapter = DecisionLiveOrderAdapter(live_client, self.settings)  # type: ignore[arg-type]

        result = live_adapter.execute_decision(
            decision=self._decision(final_mode="futures"),
            reference_price=50000.0,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.market, "futures")
        self.assertEqual(len(live_client.orders), 1)

    def test_bitget_live_order_still_returns_success_when_protection_order_fails(self) -> None:
        class FlakyProtectionClient(FakeBitgetLiveClient):
            def place_futures_position_tpsl(self, *, order_params):  # type: ignore[no-untyped-def]
                raise RuntimeError('Bitget HTTP 400: {"code":"40774","msg":"The order type for unilateral position must also be the unilateral position type."}')

        live_client = FlakyProtectionClient()
        live_adapter = DecisionLiveOrderAdapter(live_client, self.settings)  # type: ignore[arg-type]

        result = live_adapter.execute_decision(
            decision=self._decision(final_mode="futures"),
            reference_price=50000.0,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.accepted)
        self.assertEqual(result.market, "futures")
        self.assertEqual(len(live_client.orders), 1)
        self.assertIn("40774", result.protection_error)

    def test_bitget_live_order_retries_with_alternate_position_mode_payload_on_40774(self) -> None:
        class RetryClient(FakeBitgetLiveClient):
            def place_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
                self.orders.append((market, dict(order_params)))
                if len(self.orders) == 1:
                    raise RuntimeError('Bitget HTTP 400: {"code":"40774","msg":"The order type for unilateral position must also be the unilateral position type."}')
                return {"status": "SUCCESS", "orderId": "bitget-2"}

        live_client = RetryClient()
        live_adapter = DecisionLiveOrderAdapter(live_client, self.settings)  # type: ignore[arg-type]

        result = live_adapter.execute_decision(
            decision=self._decision(final_mode="futures"),
            reference_price=50000.0,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.accepted)
        self.assertEqual(len(live_client.orders), 2)
        self.assertIn("tradeSide", live_client.orders[0][1])
        self.assertIn("reduceOnly", live_client.orders[1][1])

    def test_bitget_exchange_info_exposes_min_quantity(self) -> None:
        client = BitgetRestClient(credentials=None)
        with patch.object(
            client,
            "send",
            return_value={
                "data": [
                    {
                        "symbol": "ETHUSDT",
                        "minTradeUSDT": "5",
                        "minTradeNum": "0.01",
                        "sizeMultiplier": "0.01",
                    }
                ]
            },
        ):
            info = client.get_exchange_info(market="futures")
        row = info["symbols"][0]
        lot = next(item for item in row["filters"] if item["filterType"] == "LOT_SIZE")
        self.assertEqual(lot["minQty"], "0.01")

    def test_bitget_positions_request_builder(self) -> None:
        client = BitgetRestClient(
            credentials=ExchangeCredentials(
                exchange_id="bitget",
                api_key="key",
                api_secret="secret",
                api_passphrase="passphrase",
            )
        )
        request = client.build_positions_request()
        self.assertIn("/api/v2/mix/position/all-position", request.full_url)

    def test_bitget_futures_order_params_follow_one_way_mode_contract(self) -> None:
        client = BitgetRestClient(credentials=None)

        open_params = client.build_order_params(
            market="futures",
            symbol="BTCUSDT",
            side="BUY",
            order_type="MARKET",
            quantity=0.04,
            reduce_only=False,
            client_oid="open-1",
        )
        self.assertEqual(open_params["side"], "buy")
        self.assertEqual(open_params["tradeSide"], "open")
        self.assertNotIn("holdSide", open_params)

        close_params = client.build_order_params(
            market="futures",
            symbol="BTCUSDT",
            side="SELL",
            order_type="MARKET",
            quantity=0.04,
            reduce_only=True,
            client_oid="close-1",
        )
        self.assertEqual(close_params["side"], "sell")
        self.assertEqual(close_params["tradeSide"], "close")
        self.assertNotIn("holdSide", close_params)

    def test_bitget_futures_account_prefers_crossed_executable_balance_when_available(self) -> None:
        client = BitgetRestClient(
            credentials=ExchangeCredentials(
                exchange_id="bitget",
                api_key="key",
                api_secret="secret",
                api_passphrase="passphrase",
            )
        )
        payload = {
            "code": "00000",
            "msg": "success",
            "data": [
                {
                    "marginCoin": "USDT",
                    "available": "37.96533289",
                    "crossedMaxAvailable": "4.93305789",
                    "crossedMargin": "37.489375",
                    "usdtEquity": "42.422432895899",
                }
            ],
        }

        with patch.object(client, "send", return_value=payload):
            account = client.get_account(market="futures")

        self.assertEqual(float(account["accounts"][0]["crossedMaxAvailable"]), 4.93305789)
        self.assertEqual(float(account["availableBalance"]), 37.96533289)
        self.assertEqual(float(account["executionAvailableBalance"]), 4.93305789)
        self.assertEqual(float(account["crossedMaxAvailable"]), 4.93305789)


    def test_bitget_futures_account_falls_back_to_available_when_crossed_executable_balance_is_zero(self) -> None:
        client = BitgetRestClient(
            credentials=ExchangeCredentials(
                exchange_id="bitget",
                api_key="key",
                api_secret="secret",
                api_passphrase="passphrase",
            )
        )
        payload = {
            "code": "00000",
            "msg": "success",
            "data": [
                {
                    "marginCoin": "USDT",
                    "available": "147.50760642",
                    "crossedMaxAvailable": "0",
                    "unionAvailable": "18.17050274",
                    "crossedMargin": "150.45935428",
                    "usdtEquity": "149.237136425496",
                }
            ],
        }

        with patch.object(client, "send", return_value=payload):
            account = client.get_account(market="futures")

        self.assertEqual(float(account["availableBalance"]), 147.50760642)
        self.assertEqual(float(account["executionAvailableBalance"]), 147.50760642)
        self.assertEqual(float(account["unionAvailable"]), 18.17050274)

    def test_crossed_executable_balance_assumption_reduces_bitget_futures_payload_size(self) -> None:
        decision = self._decision(final_mode="futures")
        live_adapter = DecisionLiveOrderAdapter(FakeBitgetLiveClient(), self.settings)  # type: ignore[arg-type]

        uncapped_market, uncapped_params = live_adapter.build_order_params(
            decision=decision,
            reference_price=50000.0,
        ) or (None, None)
        self.assertEqual(uncapped_market, "futures")
        self.assertIsNotNone(uncapped_params)
        assert uncapped_params is not None
        self.assertEqual(uncapped_params["size"], "0.04000000")

        session = LivePaperSession(
            runtime=SimpleNamespace(paper_service=SimpleNamespace(settings=self.settings)),
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_available_balance_usd": 37.96533289,
            "futures_execution_balance_usd": 4.93305789,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0}],
        }

        capped_decision = session._cap_live_order_decision(decision)
        capped_market, capped_params = live_adapter.build_order_params(
            decision=capped_decision,
            reference_price=50000.0,
        ) or (None, None)

        self.assertEqual(capped_market, "futures")
        self.assertIsNotNone(capped_params)
        assert capped_params is not None
        self.assertEqual(capped_decision.order_intent_notional_usd, 8.386198)
        self.assertEqual(capped_params["marginMode"], "crossed")
        self.assertEqual(capped_params["size"], "0.00016772")
        self.assertLess(float(capped_params["size"]), float(uncapped_params["size"]))

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


    def test_bitget_cancel_order_builder(self) -> None:
        request = BitgetRestClient(credentials=ExchangeCredentials(exchange_id="bitget", api_key="key", api_secret="secret", api_passphrase="pass")).build_cancel_order_request(market="futures", symbol="BTCUSDT", order_id="123")
        self.assertIn("/api/v2/mix/order/cancel-order", request.full_url)


if __name__ == "__main__":
    unittest.main()
