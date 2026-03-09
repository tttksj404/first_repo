from __future__ import annotations

import os
import unittest
from pathlib import Path

from quant_binance.env import resolve_universe_symbols
from quant_binance.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class QuantBinanceUniverseOverrideTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_value = os.environ.get("UNIVERSE_SYMBOLS")

    def tearDown(self) -> None:
        if self.old_value is None:
            os.environ.pop("UNIVERSE_SYMBOLS", None)
        else:
            os.environ["UNIVERSE_SYMBOLS"] = self.old_value

    def test_resolve_universe_symbols(self) -> None:
        os.environ["UNIVERSE_SYMBOLS"] = "btcusdt, ethusdt,SOLUSDT,BTCUSDT"
        self.assertEqual(resolve_universe_symbols(), ("BTCUSDT", "ETHUSDT", "SOLUSDT"))

    def test_settings_load_uses_universe_override(self) -> None:
        os.environ["UNIVERSE_SYMBOLS"] = "XRPUSDT,DOGEUSDT"
        settings = Settings.load(CONFIG_PATH)
        self.assertEqual(settings.universe, ("XRPUSDT", "DOGEUSDT"))


if __name__ == "__main__":
    unittest.main()
