from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant_binance.validation_report import build_policy_comparison_validation_artifact, build_policy_validation_runner_artifact, build_weekly_validation_report, write_policy_validation_runner_artifact


class QuantBinanceValidationReportTests(unittest.TestCase):
    def test_build_policy_comparison_validation_artifact_scores_candidate_vs_current(self) -> None:
        candidate_policy = {"adjustments": [{"symbol": "BTCUSDT", "size_multiplier": 1.1, "leverage_multiplier": 1.1, "entry_threshold_bps": -0.5, "expected_profit_floor_bps": -1.0}]}
        current_policy_state = {"active_policy": {"adjustments": [{"symbol": "BTCUSDT", "size_multiplier": 1.0, "leverage_multiplier": 1.0, "entry_threshold_bps": 0.0, "expected_profit_floor_bps": 0.0}]}}
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            artifact = build_policy_comparison_validation_artifact(current_policy_state=current_policy_state, candidate_policy=candidate_policy, base_dir=base, lookback_days=7)
            self.assertEqual(artifact["comparison_verdict"], "candidate_better")
            self.assertGreater(artifact["candidate_vs_current_score_delta"], 0.0)

    def test_write_policy_validation_runner_artifact_creates_runner_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_a = base / "output" / "paper-live-shell" / "run-a"
            logs_dir = run_a / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (run_a / "summary.json").write_text(json.dumps({"live_order_count": 1, "tested_order_count": 1}), encoding="utf-8")
            (run_a / "logs" / "closed_trades.jsonl").write_text(json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 5.0, "realized_return_bps_estimate": 10.0}) + "\n", encoding="utf-8")
            (run_a / "logs" / "decisions.jsonl").write_text(json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 70.0, "net_expected_edge_bps": 12.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:00:00+00:00"}) + "\n", encoding="utf-8")
            artifact = build_policy_validation_runner_artifact(base_dir=base, lookback_days=7)
            self.assertIn("runner_total_return_pct", artifact)
            output = run_a / "validation_report.json"
            write_policy_validation_runner_artifact(base_dir=base, output_path=output, lookback_days=7)
            self.assertTrue(output.exists())

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
