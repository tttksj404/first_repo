from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "quant_multi_arm_monitor.py"
SPEC = importlib.util.spec_from_file_location("quant_multi_arm_monitor", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class QuantMultiArmMonitorTests(unittest.TestCase):
    def test_latest_cycle_symbols_uses_only_most_recent_timestamp(self) -> None:
        decisions = [
            {"timestamp": "2026-04-25T19:35:00+00:00", "symbol": "PEPEUSDT"},
            {"timestamp": "2026-04-25T19:40:00+00:00", "symbol": "BTCUSDT"},
            {"timestamp": "2026-04-25T19:40:00+00:00", "symbol": "ETHUSDT"},
            {"timestamp": "2026-04-25T19:40:00+00:00", "symbol": "SOLUSDT"},
        ]

        latest = MODULE._latest_cycle_symbols(decisions)

        self.assertEqual(
            latest,
            {
                "timestamp": "2026-04-25T19:40:00+00:00",
                "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            },
        )

    def test_universe_mismatch_detects_unexpected_symbols_for_armc(self) -> None:
        latest_cycle = {
            "timestamp": "2026-04-25T19:40:00+00:00",
            "symbols": ["BTCUSDT", "DOGEUSDT", "ETHUSDT", "PEPEUSDT", "SOLUSDT"],
        }

        mismatch = MODULE._universe_mismatch("C_majors", latest_cycle)

        self.assertIsNotNone(mismatch)
        self.assertTrue(mismatch["detected"])
        self.assertEqual(mismatch["unexpected_symbols"], ["DOGEUSDT", "PEPEUSDT"])
        self.assertEqual(mismatch["missing_symbols"], [])

    def test_universe_mismatch_is_clear_when_latest_cycle_matches_expected(self) -> None:
        latest_cycle = {
            "timestamp": "2026-04-25T19:40:00+00:00",
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        }

        mismatch = MODULE._universe_mismatch("C_majors", latest_cycle)

        self.assertIsNotNone(mismatch)
        self.assertFalse(mismatch["detected"])
        self.assertEqual(mismatch["unexpected_symbols"], [])
        self.assertEqual(mismatch["missing_symbols"], [])


if __name__ == "__main__":
    unittest.main()
