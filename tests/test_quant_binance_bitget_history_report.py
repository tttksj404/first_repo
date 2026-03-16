from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from quant_binance.bitget_history_report import build_bitget_realized_winner_report, write_bitget_history_report


class _FakeBitgetHistoryClient:
    def get_futures_position_history(self, **kwargs):  # type: ignore[no-untyped-def]
        return {
            "positions": [
                {
                    "symbol": "BTCUSDT",
                    "holdSide": "long",
                    "pnl": "12.5",
                    "netProfit": "12.0",
                    "openPriceAvg": "50000",
                    "closePriceAvg": "50500",
                    "cTime": "1773000000000",
                    "uTime": "1773003600000",
                    "positionId": "pos-1",
                },
                {
                    "symbol": "ETHUSDT",
                    "holdSide": "short",
                    "pnl": "23.5",
                    "netProfit": "22.8",
                    "openPriceAvg": "2200",
                    "closePriceAvg": "2100",
                    "cTime": "1773000000000",
                    "uTime": "1773007200000",
                    "positionId": "pos-2",
                },
            ]
        }


class QuantBinanceBitgetHistoryReportTests(unittest.TestCase):
    def test_build_bitget_realized_winner_report_filters_for_threshold(self) -> None:
        report = build_bitget_realized_winner_report(
            client=_FakeBitgetHistoryClient(),
            start_time=datetime.now(UTC) - timedelta(days=30),
            end_time=datetime.now(UTC),
            min_realized_pnl_usd=20.0,
        )
        self.assertEqual(report.winner_count, 1)
        self.assertEqual(report.winners[0].symbol, "ETHUSDT")
        self.assertEqual(report.winners[0].net_profit_usd, 22.8)

    def test_write_bitget_history_report_writes_json(self) -> None:
        report = build_bitget_realized_winner_report(
            client=_FakeBitgetHistoryClient(),
            start_time=datetime.now(UTC) - timedelta(days=30),
            end_time=datetime.now(UTC),
            min_realized_pnl_usd=20.0,
        )
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "winners.json"
            write_bitget_history_report(report=report, output_path=output)
            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
