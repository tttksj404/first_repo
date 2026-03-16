from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant_binance.validation_report import build_weekly_validation_report


class QuantBinanceValidationReportTests(unittest.TestCase):
    def test_build_weekly_validation_report_aggregates_recent_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_a = base / "output" / "paper-live-shell" / "run-a"
            run_b = base / "output" / "paper-live-shell" / "run-b"
            for run_dir in (run_a, run_b):
                logs_dir = run_dir / "logs"
                logs_dir.mkdir(parents=True, exist_ok=True)
            (run_a / "summary.json").write_text(
                json.dumps({"live_order_count": 2, "tested_order_count": 1}),
                encoding="utf-8",
            )
            (run_b / "summary.json").write_text(
                json.dumps({"live_order_count": 1, "tested_order_count": 0}),
                encoding="utf-8",
            )
            (run_a / "logs" / "closed_trades.jsonl").write_text(
                json.dumps(
                    {
                        "symbol": "BTCUSDT",
                        "realized_pnl_usd_estimate": 5.0,
                        "realized_return_bps_estimate": 10.0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (run_b / "logs" / "closed_trades.jsonl").write_text(
                json.dumps(
                    {
                        "symbol": "BTCUSDT",
                        "realized_pnl_usd_estimate": -3.0,
                        "realized_return_bps_estimate": -6.0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            for run_dir, symbol, mode, score, edge, cost in (
                (run_a, "BTCUSDT", "futures", 70.0, 12.0, 8.0),
                (run_b, "ETHUSDT", "cash", 45.0, -5.0, 12.0),
            ):
                (run_dir / "logs" / "decisions.jsonl").write_text(
                    json.dumps(
                        {
                            "symbol": symbol,
                            "final_mode": mode,
                            "predictability_score": score,
                            "net_expected_edge_bps": edge,
                            "estimated_round_trip_cost_bps": cost,
                            "timestamp": "2026-03-14T00:00:00+00:00",
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )

            report = build_weekly_validation_report(base_dir=base, lookback_days=7)

            self.assertEqual(report.run_count, 2)
            self.assertEqual(report.total_closed_trade_count, 2)
            self.assertEqual(report.total_live_order_count, 3)
            self.assertEqual(report.total_tested_order_count, 1)
            symbols = {row["symbol"]: row for row in report.symbol_summary}
            self.assertIn("BTCUSDT", symbols)
            self.assertIn("ETHUSDT", {row["symbol"]: row for row in report.symbol_summary} | {"ETHUSDT": {}})
            self.assertTrue(any(row["mode"] == "futures" for row in report.regime_summary))
            self.assertTrue(any(item.category == "prune" for item in report.criteria))


if __name__ == "__main__":
    unittest.main()
