from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant_binance.bitget_winner_pattern_report import build_winner_pattern_report


class QuantBinanceBitgetWinnerPatternReportTests(unittest.TestCase):
    def test_build_winner_pattern_report_summarizes_symbol_and_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "winners.json"
            path.write_text(
                json.dumps(
                    {
                        "min_realized_pnl_usd": 20.0,
                        "winners": [
                            {
                                "symbol": "ETHUSDT",
                                "hold_side": "long",
                                "net_profit_usd": 24.8,
                                "open_time": "2026-03-12T21:51:48.856000+00:00",
                                "close_time": "2026-03-13T00:26:14.866000+00:00",
                            },
                            {
                                "symbol": "ETHUSDT",
                                "hold_side": "long",
                                "net_profit_usd": 21.3,
                                "open_time": "2026-03-11T06:35:19.609000+00:00",
                                "close_time": "2026-03-12T14:13:08.481000+00:00",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = build_winner_pattern_report(winners_path=path)

            self.assertEqual(report.winner_count, 2)
            self.assertEqual(report.symbols[0]["symbol"], "ETHUSDT")
            self.assertEqual(report.sides[0]["hold_side"], "long")
            self.assertGreater(report.average_hold_minutes, 0.0)
            self.assertTrue(any("ETHUSDT" in line for line in report.summary))


if __name__ == "__main__":
    unittest.main()
