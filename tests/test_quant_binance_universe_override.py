from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from quant_binance.env import resolve_universe_symbols
from quant_binance.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class QuantBinanceUniverseOverrideTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_value = os.environ.get("UNIVERSE_SYMBOLS")
        self.old_override_path = os.environ.get("STRATEGY_OVERRIDE_PATH")

    def tearDown(self) -> None:
        if self.old_value is None:
            os.environ.pop("UNIVERSE_SYMBOLS", None)
        else:
            os.environ["UNIVERSE_SYMBOLS"] = self.old_value
        if self.old_override_path is None:
            os.environ.pop("STRATEGY_OVERRIDE_PATH", None)
        else:
            os.environ["STRATEGY_OVERRIDE_PATH"] = self.old_override_path

    def test_resolve_universe_symbols(self) -> None:
        os.environ["UNIVERSE_SYMBOLS"] = "btcusdt, ethusdt,SOLUSDT,BTCUSDT"
        self.assertEqual(resolve_universe_symbols(), ("BTCUSDT", "ETHUSDT", "SOLUSDT"))

    def test_settings_load_uses_universe_override(self) -> None:
        os.environ["UNIVERSE_SYMBOLS"] = "XRPUSDT,DOGEUSDT"
        settings = Settings.load(CONFIG_PATH)
        self.assertEqual(settings.universe, ("XRPUSDT", "DOGEUSDT"))

    def test_settings_load_preserves_universe_override_over_override_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            override_path = Path(temp_dir) / "override.json"
            override_path.write_text(
                '{"universe":["PEPEUSDT","DOGEUSDT","BTCUSDT"]}',
                encoding="utf-8",
            )
            os.environ["UNIVERSE_SYMBOLS"] = "BTCUSDT,ETHUSDT,SOLUSDT"
            os.environ["STRATEGY_OVERRIDE_PATH"] = str(override_path)
            settings = Settings.load(CONFIG_PATH)
        self.assertEqual(settings.universe, ("BTCUSDT", "ETHUSDT", "SOLUSDT"))


if __name__ == "__main__":
    unittest.main()
