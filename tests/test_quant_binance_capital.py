from __future__ import annotations

import unittest
from pathlib import Path

from quant_binance.risk.capital import (
    FuturesFundingAsset,
    SpotFundingAsset,
    build_capital_adequacy_report,
    extract_account_capital_inputs,
)
from quant_binance.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class FakeRestClient:
    exchange_id = "binance"

    def get_exchange_info(self, *, market):  # type: ignore[no-untyped-def]
        return {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "filters": [{"filterType": "MIN_NOTIONAL", "notional": "100"}],
                },
                {
                    "symbol": "ETHUSDT",
                    "baseAsset": "ETH",
                    "quoteAsset": "USDT",
                    "filters": [{"filterType": "MIN_NOTIONAL", "notional": "20"}],
                },
                {
                    "symbol": "ETHBTC",
                    "baseAsset": "ETH",
                    "quoteAsset": "BTC",
                    "filters": [
                        {"filterType": "MIN_NOTIONAL", "notional": "0.0001"},
                        {"filterType": "LOT_SIZE", "minQty": "0.001"},
                    ],
                },
                {
                    "symbol": "SOLUSDT",
                    "baseAsset": "SOL",
                    "quoteAsset": "USDT",
                    "filters": [{"filterType": "MIN_NOTIONAL", "notional": "5"}],
                },
                {
                    "symbol": "USDCUSDT",
                    "baseAsset": "USDC",
                    "quoteAsset": "USDT",
                    "filters": [{"filterType": "MIN_NOTIONAL", "notional": "5"}],
                },
            ]
        }

    def get_book_ticker(self, *, market, symbol):  # type: ignore[no-untyped-def]
        prices = {
            "BTCUSDT": {"bidPrice": "50000", "askPrice": "50010"},
            "ETHUSDT": {"bidPrice": "3000", "askPrice": "3002"},
            "SOLUSDT": {"bidPrice": "110", "askPrice": "111"},
            "USDCUSDT": {"bidPrice": "0.999", "askPrice": "1.000"},
        }
        return prices[symbol]


class QuantBinanceCapitalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def test_capital_report_matches_symbol_requirements(self) -> None:
        report = build_capital_adequacy_report(
            spot_available_balance_usd=0.0,
            futures_available_balance_usd=0.0,
            settings=self.settings,
            rest_client=FakeRestClient(),  # type: ignore[arg-type]
        )
        self.assertFalse(report.can_trade_any)
        self.assertFalse(report.can_trade_spot_any)
        self.assertFalse(report.can_trade_futures_any)
        self.assertAlmostEqual(report.minimum_operational_balance_usd, 31.25)
        self.assertAlmostEqual(report.minimum_full_universe_balance_usd, 625.0)
        self.assertAlmostEqual(report.recommended_balance_usd, 1000.0)

    def test_spot_only_balance_allows_spot_trading(self) -> None:
        report = build_capital_adequacy_report(
            spot_available_balance_usd=33.8524,
            futures_available_balance_usd=0.0,
            settings=self.settings,
            rest_client=FakeRestClient(),  # type: ignore[arg-type]
        )
        self.assertTrue(report.can_trade_any)
        self.assertTrue(report.can_trade_spot_any)
        self.assertFalse(report.can_trade_futures_any)

    def test_account_capital_inputs_value_non_usdt_spot_assets_and_futures_equity(self) -> None:
        inputs = extract_account_capital_inputs(
            spot_account={
                "balances": [
                    {"asset": "USDT", "free": "12.5", "locked": "0"},
                    {"asset": "BTC", "free": "0.01", "locked": "0.002"},
                    {"asset": "USDC", "free": "3.0", "locked": "1.5"},
                    {"asset": "DUST", "free": "100", "locked": "0"},
                ]
            },
            futures_account={
                "availableBalance": 38.2,
                "executionAvailableBalance": 4.9,
                "assets": [
                    {
                        "asset": "USDT",
                        "walletBalance": "42.422432895899",
                        "availableBalance": "4.9",
                        "maxWithdrawAmount": "4.9",
                        "usdtEquity": "42.422432895899",
                    },
                    {
                        "asset": "BTC",
                        "walletBalance": "0.00035",
                        "availableBalance": "0.0001",
                        "maxWithdrawAmount": "0.0001",
                        "usdtEquity": "17.5",
                    },
                ],
                "accounts": [
                    {"marginCoin": "USDT", "usdtEquity": "42.422432895899"},
                    {"marginCoin": "BTC", "usdtEquity": "17.5"},
                ],
            },
            rest_client=FakeRestClient(),  # type: ignore[arg-type]
        )

        self.assertEqual(inputs.spot_available_balance_usd, 12.5)
        self.assertEqual(inputs.spot_recognized_balance_usd, 616.9955)
        self.assertEqual(inputs.spot_funding_assets[0].asset, "BTC")
        self.assertEqual(inputs.spot_funding_assets[0].free_balance_usd, 500.0)
        self.assertEqual(inputs.futures_available_balance_usd, 38.2)
        self.assertEqual(inputs.futures_execution_balance_usd, 4.9)
        self.assertEqual(inputs.futures_recognized_balance_usd, 59.922433)
        funding_assets = {item.asset: item for item in inputs.futures_funding_assets}
        self.assertEqual(set(funding_assets), {"BTC", "USDT"})
        self.assertEqual(funding_assets["BTC"].free_balance_usd, 5.0)
        self.assertEqual(funding_assets["USDT"].free_balance_usd, 4.9)

    def test_capital_report_uses_recognized_balances_for_adequacy_checks(self) -> None:
        report = build_capital_adequacy_report(
            spot_available_balance_usd=0.0,
            spot_recognized_balance_usd=40.0,
            futures_available_balance_usd=0.0,
            futures_recognized_balance_usd=700.0,
            settings=self.settings,
            rest_client=FakeRestClient(),  # type: ignore[arg-type]
        )

        self.assertTrue(report.can_trade_any)
        self.assertTrue(report.can_trade_spot_any)
        self.assertTrue(report.can_trade_futures_any)
        self.assertEqual(report.spot_available_balance_usd, 0.0)
        self.assertEqual(report.spot_recognized_balance_usd, 40.0)
        self.assertEqual(report.futures_available_balance_usd, 0.0)
        self.assertEqual(report.futures_recognized_balance_usd, 700.0)

    def test_capital_report_builds_cross_quote_spot_routes_for_held_btc(self) -> None:
        inputs = extract_account_capital_inputs(
            spot_account={
                "balances": [
                    {"asset": "USDT", "free": "0", "locked": "0"},
                    {"asset": "BTC", "free": "0.01", "locked": "0"},
                ]
            },
            futures_account={},
            rest_client=FakeRestClient(),  # type: ignore[arg-type]
        )

        report = build_capital_adequacy_report(
            spot_available_balance_usd=inputs.spot_available_balance_usd,
            spot_recognized_balance_usd=inputs.spot_recognized_balance_usd,
            spot_funding_assets=inputs.spot_funding_assets,
            futures_available_balance_usd=0.0,
            settings=self.settings,
            rest_client=FakeRestClient(),  # type: ignore[arg-type]
        )

        eth_routes = [item for item in report.spot_execution_routes if item.target_symbol == "ETHUSDT"]
        self.assertTrue(any(item.execution_symbol == "ETHBTC" for item in eth_routes))
        btc_route = next(item for item in eth_routes if item.execution_symbol == "ETHBTC")
        self.assertEqual(btc_route.funding_asset, "BTC")
        self.assertEqual(btc_route.route_type, "cross_quote")
        self.assertEqual(btc_route.min_notional_usd, 5.0)
        self.assertTrue(report.can_trade_spot_any)


class QuantBinanceCapitalMobilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def test_capital_report_exposes_transfer_capacity_between_spot_and_futures(self) -> None:
        report = build_capital_adequacy_report(
            spot_available_balance_usd=25.0,
            spot_recognized_balance_usd=25.0,
            spot_funding_assets=(
                SpotFundingAsset(
                    asset="USDT",
                    free=25.0,
                    locked=0.0,
                    total=25.0,
                    free_balance_usd=25.0,
                    total_balance_usd=25.0,
                ),
            ),
            futures_available_balance_usd=7.5,
            futures_recognized_balance_usd=30.0,
            settings=self.settings,
            rest_client=FakeRestClient(),  # type: ignore[arg-type]
        )

        self.assertEqual(report.max_spot_to_futures_transfer_usd, 25.0)
        self.assertEqual(report.max_futures_to_spot_transfer_usd, 7.5)
        self.assertTrue(any(item.source_market == "spot" and item.target_market == "futures" for item in report.capital_transfer_routes))
        self.assertTrue(any(item.source_market == "futures" and item.target_market == "spot" for item in report.capital_transfer_routes))

    def test_capital_report_exposes_futures_asset_routes_for_spot_reinvestment(self) -> None:
        report = build_capital_adequacy_report(
            spot_available_balance_usd=0.0,
            spot_recognized_balance_usd=0.0,
            spot_funding_assets=(),
            futures_available_balance_usd=0.0,
            futures_recognized_balance_usd=60.0,
            futures_funding_assets=(
                FuturesFundingAsset(
                    asset="BTC",
                    free=0.01,
                    locked=0.0,
                    total=0.01,
                    free_balance_usd=500.0,
                    total_balance_usd=500.0,
                    margin_available=False,
                ),
            ),
            settings=self.settings,
            rest_client=FakeRestClient(),  # type: ignore[arg-type]
        )

        transfer_route = next(
            item
            for item in report.capital_transfer_routes
            if item.source_market == "futures" and item.target_market == "spot" and item.asset == "BTC"
        )
        self.assertEqual(transfer_route.transferable_usd, 500.0)
        execution_route = next(
            item
            for item in report.spot_execution_routes
            if item.target_symbol == "ETHUSDT" and item.execution_symbol == "ETHBTC"
        )
        self.assertEqual(execution_route.funding_asset, "BTC")
        self.assertEqual(execution_route.funding_source_market, "futures")
        self.assertTrue(execution_route.requires_wallet_transfer)


if __name__ == "__main__":
    unittest.main()
