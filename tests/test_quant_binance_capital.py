from __future__ import annotations

import unittest
from pathlib import Path

from quant_binance.risk.capital import build_capital_adequacy_report
from quant_binance.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class FakeRestClient:
    def get_exchange_info(self, *, market):  # type: ignore[no-untyped-def]
        return {
            "symbols": [
                {"symbol": "BTCUSDT", "filters": [{"filterType": "MIN_NOTIONAL", "notional": "100"}]},
                {"symbol": "ETHUSDT", "filters": [{"filterType": "MIN_NOTIONAL", "notional": "20"}]},
                {"symbol": "SOLUSDT", "filters": [{"filterType": "MIN_NOTIONAL", "notional": "5"}]},
            ]
        }


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


if __name__ == "__main__":
    unittest.main()
