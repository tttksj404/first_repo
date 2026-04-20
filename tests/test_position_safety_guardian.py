from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUARDIAN_PATH = ROOT / "scripts" / "position_safety_guardian.py"

spec = importlib.util.spec_from_file_location("position_safety_guardian", GUARDIAN_PATH)
guardian = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(guardian)


class PositionSafetyGuardianTests(unittest.TestCase):
    def test_strategy_managed_position_keys_exclude_adopted_positions(self) -> None:
        state = {
            "paper_open_futures_positions": [
                {"symbol": "DOGEUSDT", "side": "long", "origin": "strategy"},
                {
                    "symbol": "PEPEUSDT",
                    "side": "long",
                    "origin": "adopted",
                    "adoption_source": "manual_exchange_external",
                },
                {"symbol": "SOLUSDT", "side": "short", "origin": "strategy_recovered"},
            ]
        }

        keys = guardian._strategy_managed_position_keys(state)

        self.assertEqual(keys, {"DOGEUSDT:long", "SOLUSDT:short"})

    def test_position_key_normalizes_exchange_side_aliases(self) -> None:
        self.assertEqual(guardian._position_key("dogeusdt", "BUY"), "DOGEUSDT:long")
        self.assertEqual(guardian._position_key("PEPEUSDT", "sell"), "PEPEUSDT:short")
        self.assertEqual(guardian._position_key("PEPEUSDT", "flat"), "")


if __name__ == "__main__":
    unittest.main()
