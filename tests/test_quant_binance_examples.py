from __future__ import annotations

import unittest
from pathlib import Path

from quant_binance.backtest.fixtures import load_snapshot_fixture
from quant_binance.backtest.oracle import load_oracle
from quant_binance.backtest.paper_live_fixtures import load_paper_live_cycles


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "quant_binance" / "examples"


class QuantBinanceExamplesTests(unittest.TestCase):
    def test_replay_fixture_sample_loads(self) -> None:
        snapshots = load_snapshot_fixture(EXAMPLES / "replay_fixture.sample.json")
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[0].symbol, "BTCUSDT")

    def test_paper_live_fixture_sample_loads(self) -> None:
        cycles = load_paper_live_cycles(EXAMPLES / "paper_live_fixture.sample.json")
        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0].symbol, "BTCUSDT")

    def test_oracle_sample_loads(self) -> None:
        segments = load_oracle(EXAMPLES / "oracle.sample.json")
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].expected_mode, "futures")


if __name__ == "__main__":
    unittest.main()
