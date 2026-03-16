from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant_binance.performance_report import build_runtime_performance_report


class QuantBinancePerformanceReportTests(unittest.TestCase):
    def test_build_runtime_performance_report_aggregates_symbol_expectancy_and_regimes(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            run_dir = Path(tempdir) / "paper-live-shell" / "run-a"
            logs_dir = run_dir / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "summary.json").write_text("{}", encoding="utf-8")
            (logs_dir / "closed_trades.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "symbol": "BTCUSDT",
                                "realized_pnl_usd_estimate": 10.0,
                                "realized_return_bps_estimate": 40.0,
                            }
                        ),
                        json.dumps(
                            {
                                "symbol": "BTCUSDT",
                                "realized_pnl_usd_estimate": -2.0,
                                "realized_return_bps_estimate": -8.0,
                            }
                        ),
                        json.dumps(
                            {
                                "symbol": "ETHUSDT",
                                "realized_pnl_usd_estimate": 5.0,
                                "realized_return_bps_estimate": 20.0,
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (logs_dir / "decisions.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "symbol": "BTCUSDT",
                                "final_mode": "futures",
                                "timestamp": "2026-03-14T00:00:00+00:00",
                                "predictability_score": 70.0,
                                "net_expected_edge_bps": 12.0,
                                "estimated_round_trip_cost_bps": 8.0,
                            }
                        ),
                        json.dumps(
                            {
                                "symbol": "ETHUSDT",
                                "final_mode": "spot",
                                "timestamp": "2026-03-14T00:05:00+00:00",
                                "predictability_score": 60.0,
                                "net_expected_edge_bps": 8.0,
                                "estimated_round_trip_cost_bps": 10.0,
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_runtime_performance_report(run_dir=run_dir)

            self.assertEqual(report.closed_trade_count, 3)
            self.assertEqual(report.realized_pnl_usd, 13.0)
            by_symbol = {row.symbol: row for row in report.symbol_expectancy}
            self.assertEqual(by_symbol["BTCUSDT"].trade_count, 2)
            self.assertAlmostEqual(by_symbol["BTCUSDT"].expectancy_usd, 4.0)
            modes = {row.mode: row for row in report.regime_performance}
            self.assertIn("futures", modes)
            self.assertIn("spot", modes)
            self.assertAlmostEqual(modes["futures"].avg_net_edge_bps, 12.0)
            self.assertGreaterEqual(len(report.walk_forward), 1)
            recs = {row["symbol"]: row for row in report.pruning_recommendations}
            self.assertEqual(recs["BTCUSDT"]["recommendation"], "keep")
            self.assertEqual(recs["ETHUSDT"]["recommendation"], "keep")


if __name__ == "__main__":
    unittest.main()
