from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant_binance.execution_quality_report import build_execution_quality_report


class QuantBinanceExecutionQualityReportTests(unittest.TestCase):
    def test_build_execution_quality_report_aggregates_orders_errors_and_validation_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_root = base / "output" / "paper-live-shell" / "run-a"
            logs_dir = run_root / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (logs_dir / "live_orders.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "symbol": "BTCUSDT",
                                "accepted": True,
                                "slippage_bps": 4.0,
                                "realized_edge_bps": 12.0,
                                "expected_net_edge_bps": 20.0,
                            }
                        ),
                        json.dumps(
                            {
                                "symbol": "ETHUSDT",
                                "accepted": False,
                                "slippage_bps": 6.0,
                                "realized_edge_bps": -2.0,
                                "expected_net_edge_bps": 10.0,
                                "protection_error": True,
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (logs_dir / "tested_orders.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT"}) + "\n",
                encoding="utf-8",
            )
            (logs_dir / "order_errors.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"symbol": "ETHUSDT", "error_message": 'Bitget HTTP 400: {"code":"40762","msg":"balance"}'}),
                        json.dumps({"symbol": "ETHUSDT", "error_message": 'Bitget HTTP 400: {"code":"40762","msg":"balance"}'}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (run_root / "validation_report.json").write_text(
                json.dumps(
                    {
                        "evidence": {
                            "runner_reject_rate": 0.5,
                            "runner_avg_slippage_bps": 5.0,
                            "runner_avg_realized_edge_bps": 5.0,
                            "runner_avg_edge_retention_ratio": 0.6,
                            "runner_protection_degraded_rate": 0.5,
                            "symbol_summary": [
                                {
                                    "symbol": "BTCUSDT",
                                    "expectancy_usd": -0.8,
                                    "trade_count": 8,
                                    "recommendation": "prune",
                                    "sample_status": "validated_negative",
                                },
                                {
                                    "symbol": "ETHUSDT",
                                    "expectancy_usd": 0.2,
                                    "trade_count": 3,
                                    "recommendation": "keep",
                                    "sample_status": "validated_mixed",
                                },
                            ],
                            "sample_quality_watchdog": {
                                "status": "degraded",
                                "reason_codes": ["EDGE_RETENTION_WEAK"],
                                "checkpoint_snapshot": {
                                    "symbols": [
                                        {
                                            "symbol": "BTCUSDT",
                                            "trade_count": 8,
                                            "validation_threshold": 3,
                                            "validation_ready": True,
                                        }
                                    ]
                                },
                            },
                            "auto_mode": {
                                "mode": "tighter",
                                "reason_codes": ["AUTO_MODE_TIGHTENED_BY_EXECUTION_QUALITY"],
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            report = build_execution_quality_report(base_dir=base, lookback_days=7)

            self.assertEqual(report.run_count, 1)
            self.assertEqual(report.live_order_count, 2)
            self.assertEqual(report.accepted_live_order_count, 1)
            self.assertEqual(report.order_error_count, 2)
            self.assertEqual(report.estimated_live_acceptance_rate, 0.5)
            self.assertEqual(report.reject_rate, 0.5)
            self.assertEqual(report.avg_slippage_bps, 5.0)
            self.assertEqual(report.protection_degraded_rate, 0.5)
            self.assertEqual(report.sample_quality_watchdog_status, "degraded")
            self.assertEqual(report.sample_quality_watchdog_reasons, ("EDGE_RETENTION_WEAK",))
            self.assertEqual(report.auto_mode, "tighter")
            self.assertEqual(report.auto_mode_reasons, ("AUTO_MODE_TIGHTENED_BY_EXECUTION_QUALITY",))
            self.assertEqual(report.top_error_codes[0]["code"], "40762")
            by_symbol = {row["symbol"]: row for row in report.symbol_order_summary}
            self.assertEqual(by_symbol["ETHUSDT"]["order_error_count"], 2)
            self.assertEqual(by_symbol["ETHUSDT"]["reject_rate"], 1.0)
            self.assertEqual(report.top_symbols[0]["symbol"], "BTCUSDT")
            self.assertTrue(report.top_symbols[0]["validation_ready"])
            self.assertEqual(report.checkpoint_symbols[0]["symbol"], "BTCUSDT")


if __name__ == "__main__":
    unittest.main()
