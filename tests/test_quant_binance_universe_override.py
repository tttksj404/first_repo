from __future__ import annotations

import os
import unittest
from pathlib import Path

from quant_binance.env import (
    resolve_bitget_us_stock_symbols,
    resolve_universe_symbols,
    resolve_universe_symbols_append,
)
from quant_binance.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class QuantBinanceUniverseOverrideTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_value = os.environ.get("UNIVERSE_SYMBOLS")
        self.old_append_value = os.environ.get("UNIVERSE_SYMBOLS_APPEND")
        self.old_us_stock_value = os.environ.get("BITGET_US_STOCK_SYMBOLS")

    def tearDown(self) -> None:
        if self.old_value is None:
            os.environ.pop("UNIVERSE_SYMBOLS", None)
        else:
            os.environ["UNIVERSE_SYMBOLS"] = self.old_value
        if self.old_append_value is None:
            os.environ.pop("UNIVERSE_SYMBOLS_APPEND", None)
        else:
            os.environ["UNIVERSE_SYMBOLS_APPEND"] = self.old_append_value
        if self.old_us_stock_value is None:
            os.environ.pop("BITGET_US_STOCK_SYMBOLS", None)
        else:
            os.environ["BITGET_US_STOCK_SYMBOLS"] = self.old_us_stock_value

    def test_resolve_universe_symbols(self) -> None:
        os.environ["UNIVERSE_SYMBOLS"] = "btcusdt, ethusdt,SOLUSDT,BTCUSDT"
        self.assertEqual(resolve_universe_symbols(), ("BTCUSDT", "ETHUSDT", "SOLUSDT"))

    def test_resolve_universe_symbols_append(self) -> None:
        os.environ["UNIVERSE_SYMBOLS_APPEND"] = "dogeusdt, xrpusdt,DOGEUSDT"
        self.assertEqual(resolve_universe_symbols_append(), ("DOGEUSDT", "XRPUSDT"))

    def test_resolve_bitget_us_stock_symbols(self) -> None:
        os.environ["BITGET_US_STOCK_SYMBOLS"] = "AAPLUSDT,tslausdt,AAPLUSDT"
        self.assertEqual(resolve_bitget_us_stock_symbols(), ("AAPLUSDT", "TSLAUSDT"))

    def test_settings_load_uses_universe_override(self) -> None:
        os.environ["UNIVERSE_SYMBOLS"] = "XRPUSDT,DOGEUSDT"
        settings = Settings.load(CONFIG_PATH)
        self.assertEqual(settings.universe, ("XRPUSDT", "DOGEUSDT"))

    def test_settings_load_appends_additional_universe_symbols(self) -> None:
        os.environ.pop("UNIVERSE_SYMBOLS", None)
        os.environ["UNIVERSE_SYMBOLS_APPEND"] = "XRPUSDT,DOGEUSDT"
        settings = Settings.load(CONFIG_PATH)
        self.assertEqual(settings.universe[:3], ("BTCUSDT", "ETHUSDT", "SOLUSDT"))
        self.assertIn("XRPUSDT", settings.universe)
        self.assertIn("DOGEUSDT", settings.universe)

    def test_settings_load_appends_bitget_us_stock_symbols(self) -> None:
        os.environ.pop("UNIVERSE_SYMBOLS", None)
        os.environ.pop("UNIVERSE_SYMBOLS_APPEND", None)
        os.environ["BITGET_US_STOCK_SYMBOLS"] = "AAPLUSDT,TSLAUSDT"
        settings = Settings.load(CONFIG_PATH)
        self.assertEqual(settings.universe[:3], ("BTCUSDT", "ETHUSDT", "SOLUSDT"))
        self.assertIn("AAPLUSDT", settings.universe)
        self.assertIn("TSLAUSDT", settings.universe)


if __name__ == "__main__":
    unittest.main()
