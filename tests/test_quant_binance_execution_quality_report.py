from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant_binance.execution_quality_report import build_execution_quality_report


class QuantBinanceExecutionQualityReportTests(unittest.TestCase):
    def test_build_execution_quality_report_aggregates_orders_and_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_dir = base / "output" / "paper-live-shell" / "run-a" / "logs"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "live_orders.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"symbol": "BTCUSDT", "accepted": True}),
                        json.dumps({"symbol": "ETHUSDT", "accepted": False}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (run_dir / "tested_orders.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT"}) + "\n",
                encoding="utf-8",
            )
            (run_dir / "order_errors.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"symbol": "ETHUSDT", "error_message": 'Bitget HTTP 400: {"code":"40762","msg":"balance"}'}),
                        json.dumps({"symbol": "ETHUSDT", "error_message": 'Bitget HTTP 400: {"code":"40762","msg":"balance"}'}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_execution_quality_report(base_dir=base, lookback_days=7)

            self.assertEqual(report.run_count, 1)
            self.assertEqual(report.live_order_count, 2)
            self.assertEqual(report.accepted_live_order_count, 1)
            self.assertEqual(report.order_error_count, 2)
            self.assertEqual(report.estimated_live_acceptance_rate, 0.5)
            self.assertEqual(report.top_error_codes[0]["code"], "40762")
            by_symbol = {row["symbol"]: row for row in report.symbol_order_summary}
            self.assertEqual(by_symbol["ETHUSDT"]["order_error_count"], 2)


if __name__ == "__main__":
    unittest.main()
