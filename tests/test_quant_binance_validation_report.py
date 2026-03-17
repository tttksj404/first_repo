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

    def test_build_policy_comparison_validation_artifact_prefers_runtime_evidence_when_available(self) -> None:
        candidate_policy = {"adjustments": [{"symbol": "BTCUSDT", "size_multiplier": 1.15, "leverage_multiplier": 1.1, "entry_threshold_bps": -0.5, "expected_profit_floor_bps": -1.0}]}
        current_policy_state = {
            "active_policy": {"adjustments": []},
            "policy_validation": {
                "evidence": {
                    "runner_total_realized_pnl_usd": 9.0,
                    "runner_drawdown_to_pnl_ratio": 0.15,
                    "runner_reject_rate": 0.01,
                    "runner_avg_slippage_bps": 2.0,
                    "runner_avg_realized_edge_bps": 8.0,
                    "runner_avg_edge_retention_ratio": 0.9,
                }
            },
        }
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_a = base / "output" / "paper-live-shell" / "run-a"
            (run_a / "logs").mkdir(parents=True, exist_ok=True)
            (run_a / "summary.json").write_text(
                json.dumps(
                    {
                        "live_order_count": 2,
                        "accepted_live_order_count": 1,
                        "rejected_live_order_count": 1,
                        "avg_slippage_bps": 18.0,
                        "avg_edge_retention_ratio": 0.3,
                        "avg_realized_edge_bps": -2.0,
                    }
                ),
                encoding="utf-8",
            )
            (run_a / "logs" / "closed_trades.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": -3.0, "realized_return_bps_estimate": -8.0}) + "\n",
                encoding="utf-8",
            )
            (run_a / "logs" / "decisions.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 50.0, "net_expected_edge_bps": 2.0, "estimated_round_trip_cost_bps": 10.0, "timestamp": "2026-03-14T00:00:00+00:00"})
                + "\n",
                encoding="utf-8",
            )
            artifact = build_policy_comparison_validation_artifact(
                current_policy_state=current_policy_state,
                candidate_policy=candidate_policy,
                base_dir=base,
                lookback_days=7,
            )
            self.assertEqual(artifact["comparison_verdict"], "candidate_worse")
            self.assertEqual(artifact["evidence"]["comparison_runtime_verdict"], "candidate_worse")
            self.assertTrue(artifact["validation_path"]["current_evidence_available"])

    def test_build_policy_comparison_validation_artifact_preserves_pending_micro_live_gate(self) -> None:
        candidate_policy = {"adjustments": [{"symbol": "BTCUSDT", "size_multiplier": 1.1, "leverage_multiplier": 1.05, "entry_threshold_bps": -0.5, "expected_profit_floor_bps": -1.0}]}
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_a = base / "output" / "paper-live-shell" / "run-a"
            logs_dir = run_a / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (run_a / "summary.json").write_text(json.dumps({"live_order_count": 1, "accepted_live_order_count": 1, "rejected_live_order_count": 0, "avg_slippage_bps": 4.0, "avg_edge_retention_ratio": 0.8, "avg_realized_edge_bps": 5.0, "avg_expected_edge_bps": 8.0}), encoding="utf-8")
            (logs_dir / "closed_trades.jsonl").write_text('', encoding="utf-8")
            (logs_dir / "decisions.jsonl").write_text(json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 70.0, "net_expected_edge_bps": 12.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:00:00+00:00"}) + "\n", encoding="utf-8")
            artifact = build_policy_comparison_validation_artifact(current_policy_state={"active_policy": {"adjustments": []}}, candidate_policy=candidate_policy, base_dir=base, lookback_days=7)
            self.assertEqual(artifact["evidence"]["micro_live_gate"]["status"], "pending")
            self.assertEqual(artifact["evidence"]["comparison_structural_verdict"], "candidate_better")
            self.assertEqual(artifact["validation_path"]["mode"], "paper_live_walk_forward_artifacts")

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
            self.assertEqual(artifact["validation_path_mode"], "paper_live_walk_forward_artifacts")
            self.assertEqual(artifact["runner_walk_forward_window_count"], 1)
            output = run_a / "validation_report.json"
            write_policy_validation_runner_artifact(base_dir=base, output_path=output, lookback_days=7)
            self.assertTrue(output.exists())

    def test_build_policy_validation_runner_artifact_emits_walk_forward_and_micro_live_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_a = base / "output" / "paper-live-shell" / "run-a"
            logs_dir = run_a / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (run_a / "summary.json").write_text(
                json.dumps(
                    {
                        "live_order_count": 3,
                        "accepted_live_order_count": 3,
                        "rejected_live_order_count": 0,
                        "tested_order_count": 1,
                        "avg_slippage_bps": 4.0,
                        "avg_edge_retention_ratio": 0.82,
                        "avg_realized_edge_bps": 6.5,
                        "avg_expected_edge_bps": 8.0,
                    }
                ),
                encoding="utf-8",
            )
            (logs_dir / "closed_trades.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 4.0, "realized_return_bps_estimate": 10.0}) + "\n",
                encoding="utf-8",
            )
            (logs_dir / "decisions.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 70.0, "net_expected_edge_bps": 12.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:00:00+00:00"}),
                        json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 72.0, "net_expected_edge_bps": 11.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:05:00+00:00"}),
                        json.dumps({"symbol": "ETHUSDT", "final_mode": "spot", "predictability_score": 68.0, "net_expected_edge_bps": 9.0, "estimated_round_trip_cost_bps": 7.0, "timestamp": "2026-03-14T00:10:00+00:00"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            artifact = build_policy_validation_runner_artifact(base_dir=base, lookback_days=7)
            self.assertEqual(artifact["runner_total_realized_pnl_usd"], 4.0)
            self.assertGreaterEqual(artifact["runner_walk_forward_window_count"], 1)
            self.assertEqual(artifact["micro_live_gate"]["status"], "pass")
            self.assertEqual(artifact["micro_live_gate"]["live_order_count"], 3)
            self.assertTrue(artifact["walk_forward_windows"])

    def test_build_policy_validation_runner_artifact_emits_decomposition_context(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_a = base / "output" / "paper-live-shell" / "run-a"
            logs_dir = run_a / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (run_a / "summary.json").write_text(
                json.dumps({"live_order_count": 0, "tested_order_count": 0}),
                encoding="utf-8",
            )
            (logs_dir / "closed_trades.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 4.0, "realized_return_bps_estimate": 10.0}),
                        json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 3.0, "realized_return_bps_estimate": 8.0}),
                        json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 2.0, "realized_return_bps_estimate": 6.0}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (logs_dir / "decisions.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 70.0, "net_expected_edge_bps": 12.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:00:00+00:00"}),
                        json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 71.0, "net_expected_edge_bps": 11.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:05:00+00:00"}),
                        json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 72.0, "net_expected_edge_bps": 13.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:10:00+00:00"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            artifact = build_policy_validation_runner_artifact(base_dir=base, lookback_days=7)
            self.assertTrue(artifact["symbol_summary"])
            self.assertTrue(artifact["regime_summary"])
            self.assertIn("pruning_recommendations", artifact)
            self.assertEqual(artifact["symbol_summary"][0]["symbol"], "BTCUSDT")
            self.assertTrue(any(row["mode"] == "futures" for row in artifact["regime_summary"]))

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
