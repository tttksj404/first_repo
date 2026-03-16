from __future__ import annotations

import os
import unittest
from pathlib import Path

from quant_binance.overlays import load_macro_inputs


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = ROOT / "quant_binance" / "examples" / "macro_inputs.sample.json"


class QuantBinanceMacroInputsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_path = os.environ.get("MACRO_INPUTS_PATH")
        self.old_json = os.environ.get("MACRO_INPUTS_JSON")
        os.environ.pop("MACRO_INPUTS_PATH", None)
        os.environ.pop("MACRO_INPUTS_JSON", None)

    def tearDown(self) -> None:
        if self.old_path is not None:
            os.environ["MACRO_INPUTS_PATH"] = self.old_path
        if self.old_json is not None:
            os.environ["MACRO_INPUTS_JSON"] = self.old_json

    def test_load_macro_inputs_from_path(self) -> None:
        os.environ["MACRO_INPUTS_PATH"] = str(SAMPLE_PATH)
        macro = load_macro_inputs()
        self.assertIsNotNone(macro)
        assert macro is not None
        self.assertAlmostEqual(macro.truflation_yoy, 1.8)
        self.assertAlmostEqual(macro.tga_drain_score, 0.7)
        self.assertAlmostEqual(macro.dxy_change_30d_pct, -1.8)
        self.assertAlmostEqual(macro.fed_liquidity_score, 0.66)

    def test_load_macro_inputs_reuses_cached_value_for_same_source(self) -> None:
        os.environ["MACRO_INPUTS_PATH"] = str(SAMPLE_PATH)
        first = load_macro_inputs()
        second = load_macro_inputs()
        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main()
