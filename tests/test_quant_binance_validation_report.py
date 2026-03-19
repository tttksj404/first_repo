from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant_binance.policy_lineage import build_policy_state_lineage_snapshot
from quant_binance.validation_report import build_policy_comparison_validation_artifact, build_policy_validation_runner_artifact, build_weekly_validation_report, write_policy_validation_runner_artifact


class QuantBinanceValidationReportTests(unittest.TestCase):
    def _write_watchdog_run(
        self,
        *,
        run_dir: Path,
        summary: dict[str, object],
        trades: list[dict[str, object]],
        decisions: list[dict[str, object]],
    ) -> None:
        logs_dir = run_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (logs_dir / "closed_trades.jsonl").write_text(
            "\n".join(json.dumps(row) for row in trades) + ("\n" if trades else ""),
            encoding="utf-8",
        )
        (logs_dir / "decisions.jsonl").write_text(
            "\n".join(json.dumps(row) for row in decisions) + ("\n" if decisions else ""),
            encoding="utf-8",
        )

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

    def test_build_policy_comparison_validation_artifact_emits_metric_rows_and_replay_summaries(self) -> None:
        candidate_policy = {"adjustments": [{"symbol": "BTCUSDT", "size_multiplier": 1.15, "leverage_multiplier": 1.1, "entry_threshold_bps": -0.5, "expected_profit_floor_bps": -1.0, "score_delta": 0.2}]}
        current_policy_state = {
            "active_policy": {"adjustments": [{"symbol": "BTCUSDT", "size_multiplier": 1.0, "leverage_multiplier": 1.0, "entry_threshold_bps": 0.0, "expected_profit_floor_bps": 0.0}]},
            "policy_validation": {
                "evidence": {
                    "runner_total_realized_pnl_usd": 2.0,
                    "runner_drawdown_to_pnl_ratio": 0.3,
                    "runner_reject_rate": 0.02,
                    "runner_avg_slippage_bps": 3.0,
                    "runner_avg_realized_edge_bps": 5.0,
                    "runner_avg_edge_retention_ratio": 0.7,
                    "runner_shadow_alignment_score": 0.6,
                    "runner_walk_forward_window_count": 2,
                    "runner_positive_walk_forward_window_count": 1,
                    "runner_positive_walk_forward_ratio": 0.5,
                    "symbol_summary": [{"symbol": "BTCUSDT", "trade_count": 3, "expectancy_usd": 1.5, "recommendation": "keep"}],
                    "regime_summary": [{"mode": "futures", "decision_count": 2, "avg_score": 55.0, "avg_net_edge_bps": 3.0, "avg_cost_bps": 8.0}],
                    "micro_live_gate": {"available": True, "status": "pending"},
                }
            },
        }
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
                        "avg_slippage_bps": 2.0,
                        "avg_edge_retention_ratio": 0.88,
                        "avg_realized_edge_bps": 8.0,
                        "avg_expected_edge_bps": 9.0,
                    }
                ),
                encoding="utf-8",
            )
            (logs_dir / "closed_trades.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 5.0, "realized_return_bps_estimate": 12.0}) + "\n",
                encoding="utf-8",
            )
            (logs_dir / "decisions.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 70.0, "net_expected_edge_bps": 12.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:00:00+00:00"}),
                        json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 71.0, "net_expected_edge_bps": 12.5, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:05:00+00:00"}),
                        json.dumps({"symbol": "ETHUSDT", "final_mode": "spot", "predictability_score": 68.0, "net_expected_edge_bps": 9.0, "estimated_round_trip_cost_bps": 7.0, "timestamp": "2026-03-14T00:10:00+00:00"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            artifact = build_policy_comparison_validation_artifact(
                current_policy_state=current_policy_state,
                candidate_policy=candidate_policy,
                base_dir=base,
                lookback_days=7,
            )
            self.assertGreater(artifact["runner_positive_walk_forward_ratio"], 0.0)
            self.assertEqual(artifact["validation_path"]["candidate_positive_walk_forward_ratio"], 1.0)
            self.assertTrue(artifact["candidate_replay_summary"]["top_symbols"])
            self.assertEqual(artifact["counterfactual_replay_path"]["mode"], "counterfactual_current_vs_candidate_policy")
            self.assertEqual(artifact["counterfactual_replay_path"]["candidate_policy"]["replay_summary"]["micro_live_gate"]["status"], "pass")
            self.assertTrue(artifact["counterfactual_replay_path"]["current_policy"]["evidence_available"])
            self.assertEqual(
                artifact["counterfactual_replay_path"]["execution_style_comparison"]["candidate_path"]["policy_score"],
                artifact["candidate_policy_score"],
            )
            self.assertEqual(
                artifact["counterfactual_replay_path"]["execution_style_comparison"]["current_path"]["policy_score"],
                artifact["current_policy_score"],
            )
            self.assertEqual(
                artifact["counterfactual_replay_path"]["execution_style_comparison"]["comparison_summary"]["candidate_micro_live_status"],
                "pass",
            )
            self.assertTrue(any(row["metric"] == "runner_positive_walk_forward_ratio" for row in artifact["evidence"]["metric_comparisons"]))
            self.assertEqual(artifact["evidence"]["candidate_replay_summary"]["micro_live_gate"]["status"], "pass")
            self.assertEqual(
                artifact["evidence"]["counterfactual_replay_path"]["candidate_policy"]["policy_score"],
                artifact["candidate_policy_score"],
            )
            comparison_summary = artifact["counterfactual_replay_path"]["execution_style_comparison"]["comparison_summary"]
            self.assertEqual(
                comparison_summary["policy_application_comparison"]["delta"],
                artifact["evidence"]["policy_application_delta"],
            )
            self.assertTrue(comparison_summary["execution_path_comparison"]["candidate"]["uses_projected_runtime_replay"])
            self.assertEqual(
                comparison_summary["replay_evidence_comparison"]["candidate"]["replay_source"],
                "projected_candidate_policy_from_runtime_artifacts",
            )
            self.assertEqual(
                comparison_summary["replay_evidence_comparison"]["current"]["replay_source"],
                "observed_runtime_artifacts",
            )

    def test_build_policy_comparison_validation_artifact_emits_policy_evidence_buckets(self) -> None:
        candidate_policy = {"adjustments": [{"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.1}]}
        current_policy_state = {
            "active_policy": {"status": "baseline", "adjustments": []},
            "policy_validation": {
                "evidence": {
                    "runner_total_realized_pnl_usd": 2.0,
                    "runner_drawdown_to_pnl_ratio": 0.2,
                    "runner_reject_rate": 0.01,
                    "runner_avg_edge_retention_ratio": 0.75,
                    "micro_live_gate": {"available": True, "status": "pass", "live_order_count": 4, "closed_trade_count": 1},
                    "sample_quality_watchdog": {"status": "healthy"},
                    "validation_runs": [{"live_order_count": 4, "closed_trade_count": 1, "avg_edge_retention_ratio": 0.75}],
                    "walk_forward_windows": [{"avg_net_edge_bps": 2.0, "avg_score": 55.0}],
                }
            },
        }
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
                        "avg_slippage_bps": 2.0,
                        "avg_edge_retention_ratio": 0.8,
                        "avg_realized_edge_bps": 6.0,
                        "avg_expected_edge_bps": 8.0,
                    }
                ),
                encoding="utf-8",
            )
            (logs_dir / "closed_trades.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 4.0, "realized_return_bps_estimate": 9.0}) + "\n",
                encoding="utf-8",
            )
            (logs_dir / "decisions.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 71.0, "net_expected_edge_bps": 11.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:00:00+00:00"})
                + "\n",
                encoding="utf-8",
            )
            artifact = build_policy_comparison_validation_artifact(
                current_policy_state=current_policy_state,
                candidate_policy=candidate_policy,
                base_dir=base,
                lookback_days=7,
            )
            buckets = artifact["policy_evidence_buckets"]
            self.assertEqual(sorted(buckets), ["active_policy", "baseline_control", "staged_candidate"])
            self.assertTrue(buckets["staged_candidate"]["available"])
            self.assertTrue(buckets["active_policy"]["available"])
            self.assertEqual(
                artifact["evidence"]["policy_evidence_buckets"]["baseline_control"]["comparison"],
                artifact["baseline_control_comparison"],
            )
            self.assertEqual(
                buckets["staged_candidate"]["policy_lineage"]["source"],
                "staged_candidate_policy",
            )
            self.assertEqual(
                artifact["auto_mode"]["inputs"]["execution_quality"]["policy_bucket"],
                "staged_candidate",
            )

    def test_build_policy_comparison_validation_artifact_requires_bucket_replay_before_simple_baseline_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_a = base / "output" / "paper-live-shell" / "run-a"
            comparison_run = base / "output" / "strategy-comparison-recent" / "run-b"
            logs_dir = run_a / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            comparison_run.mkdir(parents=True, exist_ok=True)
            (comparison_run / "comparison.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {
                                "strategy_name": "current_strategy",
                                "trade_count": 4,
                                "closed_trade_count": 4,
                                "total_pnl_usd": 1.0,
                                "total_return_pct": 0.08,
                                "max_drawdown_pct": 0.1,
                            },
                            {
                                "strategy_name": "directional_hold",
                                "trade_count": 4,
                                "closed_trade_count": 4,
                                "total_pnl_usd": 0.2,
                                "total_return_pct": 0.01,
                                "max_drawdown_pct": 0.2,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (run_a / "summary.json").write_text(
                json.dumps(
                    {
                        "live_order_count": 2,
                        "accepted_live_order_count": 2,
                        "rejected_live_order_count": 0,
                        "tested_order_count": 1,
                        "avg_slippage_bps": 2.0,
                        "avg_edge_retention_ratio": 0.8,
                        "avg_realized_edge_bps": 4.0,
                        "avg_expected_edge_bps": 5.0,
                    }
                ),
                encoding="utf-8",
            )
            (logs_dir / "closed_trades.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 2.0, "realized_return_bps_estimate": 4.0}) + "\n",
                encoding="utf-8",
            )
            (logs_dir / "decisions.jsonl").write_text(
                json.dumps(
                    {
                        "symbol": "BTCUSDT",
                        "final_mode": "futures",
                        "predictability_score": 70.0,
                        "net_expected_edge_bps": 10.0,
                        "estimated_round_trip_cost_bps": 6.0,
                        "timestamp": "2026-03-14T00:00:00+00:00",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            artifact = build_policy_comparison_validation_artifact(
                current_policy_state={"active_policy": {"status": "baseline", "adjustments": []}},
                candidate_policy={"adjustments": []},
                base_dir=base,
                lookback_days=7,
            )

            baseline = artifact["baseline_control_comparison"]
            self.assertEqual(baseline["verdict"], "supportive")
            self.assertEqual(baseline["expansion_gate"], "not_available")
            self.assertFalse(baseline["bucket_replay_ready"])
            self.assertEqual(baseline["bucket_replay_reason"], "BASELINE_CONTROL_BUCKET_REPLAY_NOT_AVAILABLE")
            self.assertNotIn("AUTO_MODE_SIMPLE_BASELINE_SUPPORTIVE", artifact["auto_mode"]["reason_codes"])

    def test_build_policy_comparison_validation_artifact_prefers_direct_active_bucket_from_current_policy_state(self) -> None:
        candidate_policy = {"adjustments": []}
        current_policy_state = {
            "version": 3,
            "active_policy": {
                "status": "promote",
                "adjustments": [{"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.1}],
            },
            "rollout_progression": {"execution_phase": "partial"},
            "policy_evidence_buckets": {
                "active_policy": {
                    "available": True,
                    "source": "persisted_policy_validation_evidence",
                    "alignment": {"aligned": True, "status": "aligned", "reason": "POLICY_LINEAGE_MATCH"},
                    "evidence": {
                        "runner_total_realized_pnl_usd": 3.5,
                        "runner_drawdown_to_pnl_ratio": 0.08,
                        "runner_reject_rate": 0.0,
                        "runner_avg_edge_retention_ratio": 0.82,
                        "runner_walk_forward_window_count": 1,
                        "runner_positive_walk_forward_ratio": 1.0,
                        "micro_live_gate": {"available": True, "status": "pass", "live_order_count": 4, "closed_trade_count": 1},
                        "sample_quality_watchdog": {"status": "healthy"},
                        "validation_runs": [{"live_order_count": 4, "closed_trade_count": 1, "avg_edge_retention_ratio": 0.82}],
                        "walk_forward_windows": [{"avg_net_edge_bps": 2.1, "avg_score": 56.0}],
                    },
                }
            },
        }
        current_lineage = build_policy_state_lineage_snapshot(current_policy_state, source="current_policy_state")
        current_policy_state["policy_lineage"] = dict(current_lineage)
        current_policy_state["policy_evidence_buckets"]["active_policy"]["policy_lineage"] = dict(current_lineage)
        current_policy_state["policy_evidence_buckets"]["active_policy"]["evidence_lineage"] = dict(current_lineage)
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
                        "avg_slippage_bps": 2.2,
                        "avg_edge_retention_ratio": 0.8,
                        "avg_realized_edge_bps": 6.0,
                        "avg_expected_edge_bps": 8.0,
                    }
                ),
                encoding="utf-8",
            )
            (logs_dir / "closed_trades.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 4.0, "realized_return_bps_estimate": 9.0}) + "\n",
                encoding="utf-8",
            )
            (logs_dir / "decisions.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 71.0, "net_expected_edge_bps": 11.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:00:00+00:00"})
                + "\n",
                encoding="utf-8",
            )
            artifact = build_policy_comparison_validation_artifact(
                current_policy_state=current_policy_state,
                candidate_policy=candidate_policy,
                base_dir=base,
                lookback_days=7,
            )
            self.assertTrue(artifact["policy_evidence_buckets"]["active_policy"]["available"])
            self.assertTrue(artifact["validation_path"]["current_evidence_available"])
            self.assertEqual(artifact["current_replay_summary"]["source"], "persisted_policy_validation_evidence")
            self.assertTrue(
                artifact["counterfactual_replay_path"]["current_policy"]["execution_path"]["uses_persisted_validation_evidence"]
            )

    def test_build_policy_comparison_validation_artifact_prefers_bucket_validation_runs_for_current_snapshot(self) -> None:
        candidate_policy = {"adjustments": []}
        current_policy_state = {
            "version": 4,
            "active_policy": {
                "status": "promote",
                "adjustments": [{"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.1}],
            },
            "rollout_progression": {"execution_phase": "partial"},
            "policy_validation": {
                "evidence": {
                    "validation_runs": [
                        {
                            "live_order_count": 9,
                            "accepted_live_order_count": 8,
                            "rejected_live_order_count": 1,
                            "closed_trade_count": 3,
                            "realized_pnl_usd": 7.0,
                            "avg_edge_retention_ratio": 0.88,
                            "avg_slippage_bps": 3.0,
                        }
                    ],
                    "walk_forward_windows": [{"avg_net_edge_bps": 3.5, "avg_score": 62.0}],
                }
            },
            "policy_evidence_buckets": {
                "active_policy": {
                    "available": True,
                    "source": "persisted_policy_validation_evidence",
                    "alignment": {"aligned": True, "status": "aligned", "reason": "POLICY_LINEAGE_MATCH"},
                    "evidence": {
                        "runner_walk_forward_window_count": 2,
                        "runner_positive_walk_forward_ratio": 1.0,
                        "validation_runs": [
                            {
                                "live_order_count": 2,
                                "accepted_live_order_count": 2,
                                "rejected_live_order_count": 0,
                                "closed_trade_count": 1,
                                "realized_pnl_usd": 1.2,
                                "avg_edge_retention_ratio": 0.75,
                                "avg_slippage_bps": 2.4,
                            },
                            {
                                "live_order_count": 4,
                                "accepted_live_order_count": 3,
                                "rejected_live_order_count": 1,
                                "closed_trade_count": 1,
                                "realized_pnl_usd": 1.0,
                                "avg_edge_retention_ratio": 0.65,
                                "avg_slippage_bps": 3.2,
                            },
                        ],
                        "walk_forward_windows": [
                            {"avg_net_edge_bps": 2.0, "avg_score": 55.0},
                            {"avg_net_edge_bps": 1.0, "avg_score": 51.0},
                        ],
                    },
                }
            },
        }
        current_lineage = build_policy_state_lineage_snapshot(current_policy_state, source="current_policy_state")
        current_policy_state["policy_lineage"] = dict(current_lineage)
        current_policy_state["policy_evidence_buckets"]["active_policy"]["policy_lineage"] = dict(current_lineage)
        current_policy_state["policy_evidence_buckets"]["active_policy"]["evidence_lineage"] = dict(current_lineage)
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_a = base / "output" / "paper-live-shell" / "run-a"
            logs_dir = run_a / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (run_a / "summary.json").write_text(
                json.dumps(
                    {
                        "live_order_count": 3,
                        "accepted_live_order_count": 2,
                        "rejected_live_order_count": 1,
                        "avg_slippage_bps": 9.0,
                        "avg_edge_retention_ratio": 0.2,
                        "avg_realized_edge_bps": -2.0,
                        "avg_expected_edge_bps": 8.0,
                    }
                ),
                encoding="utf-8",
            )
            (logs_dir / "closed_trades.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": -2.0, "realized_return_bps_estimate": -5.0}) + "\n",
                encoding="utf-8",
            )
            (logs_dir / "decisions.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT", "final_mode": "cash", "predictability_score": 42.0, "net_expected_edge_bps": 0.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:00:00+00:00"})
                + "\n",
                encoding="utf-8",
            )
            artifact = build_policy_comparison_validation_artifact(
                current_policy_state=current_policy_state,
                candidate_policy=candidate_policy,
                base_dir=base,
                lookback_days=7,
            )
            self.assertEqual(artifact["current_replay_summary"]["source"], "persisted_policy_validation_evidence")
            self.assertEqual(artifact["current_replay_summary"]["execution_metrics"]["live_order_count"], 6)
            self.assertEqual(artifact["current_replay_summary"]["execution_metrics"]["closed_trade_count"], 2)
            self.assertAlmostEqual(artifact["current_replay_summary"]["positive_walk_forward_ratio"], 1.0)
            self.assertEqual(artifact["validation_path"]["current_walk_forward_window_count"], 2)
            self.assertAlmostEqual(artifact["validation_path"]["current_positive_walk_forward_ratio"], 1.0)

    def test_build_policy_comparison_validation_artifact_falls_back_to_legacy_current_validation_runs_without_buckets(self) -> None:
        candidate_policy = {"adjustments": []}
        current_policy_state = {
            "version": 2,
            "active_policy": {"status": "baseline", "adjustments": []},
            "policy_validation": {
                "evidence": {
                    "runner_walk_forward_window_count": 2,
                    "runner_positive_walk_forward_ratio": 1.0,
                    "validation_runs": [
                        {
                            "live_order_count": 3,
                            "accepted_live_order_count": 3,
                            "rejected_live_order_count": 0,
                            "closed_trade_count": 1,
                            "realized_pnl_usd": 1.1,
                            "avg_edge_retention_ratio": 0.72,
                            "avg_slippage_bps": 2.8,
                        },
                        {
                            "live_order_count": 3,
                            "accepted_live_order_count": 2,
                            "rejected_live_order_count": 1,
                            "closed_trade_count": 1,
                            "realized_pnl_usd": 0.9,
                            "avg_edge_retention_ratio": 0.68,
                            "avg_slippage_bps": 3.1,
                        },
                    ],
                    "walk_forward_windows": [
                        {"avg_net_edge_bps": 1.8, "avg_score": 54.0},
                        {"avg_net_edge_bps": 1.1, "avg_score": 52.0},
                    ],
                }
            },
        }
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_a = base / "output" / "paper-live-shell" / "run-a"
            logs_dir = run_a / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (run_a / "summary.json").write_text(
                json.dumps(
                    {
                        "live_order_count": 4,
                        "accepted_live_order_count": 2,
                        "rejected_live_order_count": 2,
                        "avg_slippage_bps": 11.0,
                        "avg_edge_retention_ratio": 0.1,
                        "avg_realized_edge_bps": -4.0,
                        "avg_expected_edge_bps": 6.0,
                    }
                ),
                encoding="utf-8",
            )
            (logs_dir / "closed_trades.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": -3.0, "realized_return_bps_estimate": -7.0}) + "\n",
                encoding="utf-8",
            )
            (logs_dir / "decisions.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT", "final_mode": "cash", "predictability_score": 40.0, "net_expected_edge_bps": 0.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:00:00+00:00"})
                + "\n",
                encoding="utf-8",
            )
            artifact = build_policy_comparison_validation_artifact(
                current_policy_state=current_policy_state,
                candidate_policy=candidate_policy,
                base_dir=base,
                lookback_days=7,
            )
            self.assertEqual(artifact["current_replay_summary"]["source"], "persisted_policy_validation_evidence")
            self.assertEqual(artifact["current_replay_summary"]["execution_metrics"]["live_order_count"], 6)
            self.assertEqual(artifact["current_replay_summary"]["execution_metrics"]["closed_trade_count"], 2)
            self.assertAlmostEqual(artifact["current_replay_summary"]["positive_walk_forward_ratio"], 1.0)
            self.assertEqual(artifact["validation_path"]["current_walk_forward_window_count"], 2)
            self.assertAlmostEqual(artifact["validation_path"]["current_positive_walk_forward_ratio"], 1.0)

    def test_build_policy_comparison_validation_artifact_prefers_active_bucket_logs_over_root_current_evidence(self) -> None:
        candidate_policy = {"adjustments": []}
        current_policy_state = {
            "version": 5,
            "active_policy": {
                "status": "promote",
                "adjustments": [{"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.1}],
            },
            "rollout_progression": {"execution_phase": "partial"},
            "policy_validation": {
                "evidence": {
                    "validation_runs": [
                        {
                            "live_order_count": 8,
                            "accepted_live_order_count": 8,
                            "rejected_live_order_count": 0,
                            "closed_trade_count": 3,
                            "realized_pnl_usd": 9.0,
                            "avg_edge_retention_ratio": 0.92,
                            "avg_slippage_bps": 2.0,
                        }
                    ],
                    "walk_forward_windows": [{"avg_net_edge_bps": 3.5, "avg_score": 60.0}],
                }
            },
        }
        current_lineage = build_policy_state_lineage_snapshot(current_policy_state, source="current_policy_state")
        current_policy_state["policy_lineage"] = dict(current_lineage)
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_a = base / "output" / "paper-live-shell" / "run-a"
            logs_dir = run_a / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (run_a / "summary.json").write_text(
                json.dumps(
                    {
                        "live_order_count": 2,
                        "accepted_live_order_count": 2,
                        "rejected_live_order_count": 0,
                        "tested_order_count": 2,
                        "avg_slippage_bps": 5.5,
                        "avg_edge_retention_ratio": 0.1,
                        "avg_realized_edge_bps": -0.5,
                        "avg_expected_edge_bps": 5.0,
                    }
                ),
                encoding="utf-8",
            )
            entry_fields = {
                "entry_policy_bucket_available": True,
                "entry_policy_bucket_alignment_status": "aligned",
                "entry_policy_bucket_source": "persisted_policy_state",
                "entry_policy_lineage": dict(current_lineage),
            }
            (logs_dir / "decisions.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "symbol": "BTCUSDT",
                                "final_mode": "futures",
                                "predictability_score": 72.0,
                                "net_expected_edge_bps": 12.0,
                                "estimated_round_trip_cost_bps": 8.0,
                                "timestamp": "2026-03-18T00:00:00+00:00",
                                "entry_policy_bucket": "active_policy",
                                **entry_fields,
                            }
                        ),
                        json.dumps(
                            {
                                "symbol": "ETHUSDT",
                                "final_mode": "futures",
                                "predictability_score": 58.0,
                                "net_expected_edge_bps": 6.0,
                                "estimated_round_trip_cost_bps": 8.0,
                                "timestamp": "2026-03-18T00:05:00+00:00",
                                "entry_policy_bucket": "staged_candidate",
                                **entry_fields,
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (logs_dir / "live_orders.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "symbol": "BTCUSDT",
                                "accepted": True,
                                "fill_status": "accepted",
                                "slippage_bps": 2.0,
                                "realized_edge_bps": 4.0,
                                "expected_net_edge_bps": 5.0,
                                "entry_policy_bucket": "active_policy",
                                **entry_fields,
                            }
                        ),
                        json.dumps(
                            {
                                "symbol": "ETHUSDT",
                                "accepted": True,
                                "fill_status": "accepted",
                                "slippage_bps": 9.0,
                                "realized_edge_bps": -3.0,
                                "expected_net_edge_bps": 5.0,
                                "entry_policy_bucket": "staged_candidate",
                                **entry_fields,
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (logs_dir / "tested_orders.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"symbol": "BTCUSDT", "entry_policy_bucket": "active_policy", **entry_fields}),
                        json.dumps({"symbol": "ETHUSDT", "entry_policy_bucket": "staged_candidate", **entry_fields}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (logs_dir / "closed_trades.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "symbol": "BTCUSDT",
                                "realized_pnl_usd_estimate": 3.0,
                                "realized_return_bps_estimate": 7.0,
                                "entry_predictability_score": 72.0,
                                "entry_policy_bucket": "active_policy",
                                **entry_fields,
                            }
                        ),
                        json.dumps(
                            {
                                "symbol": "ETHUSDT",
                                "realized_pnl_usd_estimate": -4.0,
                                "realized_return_bps_estimate": -8.0,
                                "entry_predictability_score": 58.0,
                                "entry_policy_bucket": "staged_candidate",
                                **entry_fields,
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            artifact = build_policy_comparison_validation_artifact(
                current_policy_state=current_policy_state,
                candidate_policy=candidate_policy,
                base_dir=base,
                lookback_days=7,
            )

            self.assertEqual(artifact["current_replay_summary"]["source"], "observed_runtime_policy_bucket_artifacts")
            self.assertEqual(artifact["current_replay_summary"]["execution_metrics"]["live_order_count"], 1)
            self.assertEqual(artifact["current_replay_summary"]["execution_metrics"]["closed_trade_count"], 1)
            self.assertEqual(artifact["current_replay_summary"]["execution_metrics"]["total_realized_pnl_usd"], 3.0)
            self.assertEqual(
                artifact["current_replay_summary"]["replay_provenance"]["classification"],
                "direct_bucket_aware_replay",
            )
            self.assertEqual(artifact["validation_path"]["current_walk_forward_window_count"], 1)
            self.assertEqual(artifact["policy_evidence_buckets"]["active_policy"]["source"], "observed_runtime_policy_bucket_artifacts")

    def test_build_policy_comparison_validation_artifact_prefers_staged_candidate_bucket_logs_for_candidate_replay(self) -> None:
        candidate_policy = {"adjustments": [{"symbol": "ETHUSDT", "action": "promote", "size_multiplier": 1.1}]}
        current_policy_state = {
            "active_policy": {"status": "baseline", "adjustments": []},
            "policy_validation": {
                "evidence": {
                    "runner_total_realized_pnl_usd": 4.0,
                    "runner_drawdown_to_pnl_ratio": 0.1,
                    "runner_reject_rate": 0.0,
                    "runner_avg_edge_retention_ratio": 0.8,
                    "runner_avg_slippage_bps": 2.0,
                    "runner_avg_realized_edge_bps": 5.0,
                    "runner_positive_walk_forward_ratio": 1.0,
                }
            },
        }
        current_lineage = build_policy_state_lineage_snapshot(current_policy_state, source="current_policy_state")
        current_policy_state["policy_lineage"] = dict(current_lineage)
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_a = base / "output" / "paper-live-shell" / "run-a"
            logs_dir = run_a / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (run_a / "summary.json").write_text(
                json.dumps(
                    {
                        "live_order_count": 2,
                        "accepted_live_order_count": 2,
                        "rejected_live_order_count": 0,
                        "tested_order_count": 2,
                        "avg_slippage_bps": 4.0,
                        "avg_edge_retention_ratio": 0.45,
                        "avg_realized_edge_bps": 0.5,
                        "avg_expected_edge_bps": 5.0,
                    }
                ),
                encoding="utf-8",
            )
            entry_fields = {
                "entry_policy_bucket_available": True,
                "entry_policy_bucket_alignment_status": "aligned",
                "entry_policy_bucket_source": "persisted_policy_state",
                "entry_policy_lineage": dict(current_lineage),
            }
            (logs_dir / "decisions.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "symbol": "BTCUSDT",
                                "final_mode": "futures",
                                "predictability_score": 72.0,
                                "net_expected_edge_bps": 12.0,
                                "estimated_round_trip_cost_bps": 8.0,
                                "timestamp": "2026-03-18T00:00:00+00:00",
                                "entry_policy_bucket": "active_policy",
                                **entry_fields,
                            }
                        ),
                        json.dumps(
                            {
                                "symbol": "ETHUSDT",
                                "final_mode": "futures",
                                "predictability_score": 58.0,
                                "net_expected_edge_bps": 6.0,
                                "estimated_round_trip_cost_bps": 8.0,
                                "timestamp": "2026-03-18T00:05:00+00:00",
                                "entry_policy_bucket": "staged_candidate",
                                **entry_fields,
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (logs_dir / "live_orders.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "symbol": "BTCUSDT",
                                "accepted": True,
                                "fill_status": "accepted",
                                "slippage_bps": 2.0,
                                "realized_edge_bps": 4.0,
                                "expected_net_edge_bps": 5.0,
                                "entry_policy_bucket": "active_policy",
                                **entry_fields,
                            }
                        ),
                        json.dumps(
                            {
                                "symbol": "ETHUSDT",
                                "accepted": True,
                                "fill_status": "accepted",
                                "slippage_bps": 9.0,
                                "realized_edge_bps": -3.0,
                                "expected_net_edge_bps": 5.0,
                                "entry_policy_bucket": "staged_candidate",
                                **entry_fields,
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (logs_dir / "tested_orders.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"symbol": "BTCUSDT", "entry_policy_bucket": "active_policy", **entry_fields}),
                        json.dumps({"symbol": "ETHUSDT", "entry_policy_bucket": "staged_candidate", **entry_fields}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (logs_dir / "closed_trades.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "symbol": "BTCUSDT",
                                "realized_pnl_usd_estimate": 3.0,
                                "realized_return_bps_estimate": 7.0,
                                "entry_predictability_score": 72.0,
                                "entry_policy_bucket": "active_policy",
                                **entry_fields,
                            }
                        ),
                        json.dumps(
                            {
                                "symbol": "ETHUSDT",
                                "realized_pnl_usd_estimate": -4.0,
                                "realized_return_bps_estimate": -8.0,
                                "entry_predictability_score": 58.0,
                                "entry_policy_bucket": "staged_candidate",
                                **entry_fields,
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            artifact = build_policy_comparison_validation_artifact(
                current_policy_state=current_policy_state,
                candidate_policy=candidate_policy,
                base_dir=base,
                lookback_days=7,
            )

            self.assertEqual(artifact["candidate_replay_summary"]["source"], "observed_staged_candidate_policy_bucket_artifacts")
            self.assertEqual(artifact["candidate_replay_summary"]["execution_metrics"]["live_order_count"], 1)
            self.assertEqual(artifact["candidate_replay_summary"]["execution_metrics"]["closed_trade_count"], 1)
            comparison_summary = artifact["counterfactual_replay_path"]["execution_style_comparison"]["comparison_summary"]
            self.assertFalse(comparison_summary["execution_path_comparison"]["candidate"]["uses_projected_runtime_replay"])
            self.assertTrue(comparison_summary["execution_path_comparison"]["candidate"]["uses_bucket_log_replay"])
            self.assertEqual(
                comparison_summary["replay_evidence_comparison"]["candidate"]["bucket_name"],
                "staged_candidate",
            )
            self.assertEqual(
                comparison_summary["candidate_replay_provenance"]["classification"],
                "direct_bucket_aware_replay",
            )
            self.assertEqual(
                artifact["validation_path"]["candidate_replay_source"],
                "observed_staged_candidate_policy_bucket_artifacts",
            )

    def test_build_policy_comparison_validation_artifact_uses_latest_bucket_logs_for_current_policy_replay(self) -> None:
        candidate_policy = {"adjustments": []}
        current_policy_state = {
            "version": 6,
            "active_policy": {
                "status": "promote",
                "adjustments": [{"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.1}],
            },
            "rollout_progression": {"execution_phase": "partial"},
        }
        current_lineage = build_policy_state_lineage_snapshot(current_policy_state, source="current_policy_state")
        current_policy_state["policy_lineage"] = dict(current_lineage)
        runtime_summary = {
            "generated_at": "2026-03-18T00:10:00+00:00",
            "live_order_count": 5,
            "accepted_live_order_count": 5,
            "rejected_live_order_count": 0,
            "closed_trade_count": 5,
            "avg_slippage_bps": 2.0,
            "avg_edge_retention_ratio": 0.9,
            "avg_realized_edge_bps": 7.0,
            "avg_expected_edge_bps": 8.0,
            "realized_pnl_usd_estimate": 12.0,
        }
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_a = base / "output" / "paper-live-shell" / "run-a"
            latest = base / "output" / "paper-live-shell" / "latest"
            for run_dir in (run_a, latest):
                (run_dir / "logs").mkdir(parents=True, exist_ok=True)
            (run_a / "summary.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-17T00:00:00+00:00",
                        "live_order_count": 1,
                        "accepted_live_order_count": 1,
                        "rejected_live_order_count": 0,
                        "tested_order_count": 1,
                        "avg_slippage_bps": 6.0,
                        "avg_edge_retention_ratio": 0.5,
                        "avg_realized_edge_bps": 1.0,
                        "avg_expected_edge_bps": 3.0,
                    }
                ),
                encoding="utf-8",
            )
            (run_a / "logs" / "closed_trades.jsonl").write_text(
                json.dumps({"symbol": "ETHUSDT", "realized_pnl_usd_estimate": -1.0, "realized_return_bps_estimate": -2.0}) + "\n",
                encoding="utf-8",
            )
            (run_a / "logs" / "decisions.jsonl").write_text(
                json.dumps({"symbol": "ETHUSDT", "final_mode": "spot", "predictability_score": 51.0, "net_expected_edge_bps": 4.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-17T00:00:00+00:00"})
                + "\n",
                encoding="utf-8",
            )
            entry_fields = {
                "entry_policy_bucket_available": True,
                "entry_policy_bucket_alignment_status": "aligned",
                "entry_policy_bucket_source": "persisted_policy_state",
                "entry_policy_lineage": dict(current_lineage),
            }
            (latest / "summary.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-18T00:10:00+00:00",
                        "live_order_count": 2,
                        "accepted_live_order_count": 2,
                        "rejected_live_order_count": 0,
                        "tested_order_count": 1,
                        "avg_slippage_bps": 5.0,
                        "avg_edge_retention_ratio": 0.1,
                        "avg_realized_edge_bps": -1.0,
                        "avg_expected_edge_bps": 5.0,
                    }
                ),
                encoding="utf-8",
            )
            (latest / "logs" / "decisions.jsonl").write_text(
                json.dumps(
                    {
                        "symbol": "BTCUSDT",
                        "final_mode": "futures",
                        "predictability_score": 73.0,
                        "net_expected_edge_bps": 11.0,
                        "estimated_round_trip_cost_bps": 8.0,
                        "timestamp": "2026-03-18T00:10:00+00:00",
                        "entry_policy_bucket": "active_policy",
                        **entry_fields,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (latest / "logs" / "live_orders.jsonl").write_text(
                json.dumps(
                    {
                        "symbol": "BTCUSDT",
                        "accepted": True,
                        "fill_status": "accepted",
                        "slippage_bps": 1.5,
                        "realized_edge_bps": 3.0,
                        "expected_net_edge_bps": 4.0,
                        "entry_policy_bucket": "active_policy",
                        **entry_fields,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (latest / "logs" / "tested_orders.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT", "entry_policy_bucket": "active_policy", **entry_fields}) + "\n",
                encoding="utf-8",
            )
            (latest / "logs" / "closed_trades.jsonl").write_text(
                json.dumps(
                    {
                        "symbol": "BTCUSDT",
                        "realized_pnl_usd_estimate": 2.5,
                        "realized_return_bps_estimate": 6.0,
                        "entry_predictability_score": 73.0,
                        "entry_policy_bucket": "active_policy",
                        **entry_fields,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            artifact = build_policy_comparison_validation_artifact(
                current_policy_state=current_policy_state,
                candidate_policy=candidate_policy,
                base_dir=base,
                lookback_days=7,
                current_runtime_summary=runtime_summary,
            )

            self.assertEqual(artifact["current_replay_summary"]["source"], "observed_runtime_policy_bucket_artifacts")
            self.assertEqual(artifact["current_replay_summary"]["execution_metrics"]["live_order_count"], 1)
            self.assertEqual(artifact["current_replay_summary"]["execution_metrics"]["closed_trade_count"], 1)
            self.assertEqual(artifact["current_replay_summary"]["execution_metrics"]["total_realized_pnl_usd"], 2.5)
            self.assertEqual(artifact["current_replay_summary"]["runtime_summary_anchor"]["source"], "current_runtime_summary")

    def test_build_policy_comparison_validation_artifact_filters_mismatched_run_lineage(self) -> None:
        candidate_policy = {"adjustments": []}
        current_policy_state = {
            "version": 7,
            "active_policy": {"status": "baseline", "adjustments": []},
            "rollout_progression": {"execution_phase": "baseline"},
            "policy_validation": {"evidence": {}},
            "updated_at": "2026-03-19T00:00:00+00:00",
        }
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_a = base / "output" / "paper-live-shell" / "run-a"
            run_b = base / "output" / "paper-live-shell" / "run-b"
            self._write_watchdog_run(
                run_dir=run_a,
                summary={
                    "generated_at": "2026-03-19T00:00:00+00:00",
                    "live_order_count": 2,
                    "accepted_live_order_count": 2,
                    "rejected_live_order_count": 0,
                    "tested_order_count": 1,
                    "avg_slippage_bps": 2.0,
                    "avg_edge_retention_ratio": 0.8,
                    "avg_realized_edge_bps": 4.0,
                    "avg_expected_edge_bps": 5.0,
                },
                trades=[
                    {"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 2.0, "realized_return_bps_estimate": 6.0},
                    {"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 2.0, "realized_return_bps_estimate": 5.0},
                ],
                decisions=[
                    {"symbol": "BTCUSDT", "final_mode": "futures", "timestamp": "2026-03-19T00:00:00+00:00", "predictability_score": 70.0, "net_expected_edge_bps": 10.0, "estimated_round_trip_cost_bps": 8.0},
                    {"symbol": "BTCUSDT", "final_mode": "futures", "timestamp": "2026-03-19T00:05:00+00:00", "predictability_score": 71.0, "net_expected_edge_bps": 11.0, "estimated_round_trip_cost_bps": 8.0},
                ],
            )
            self._write_watchdog_run(
                run_dir=run_b,
                summary={
                    "generated_at": "2026-03-19T00:10:00+00:00",
                    "live_order_count": 2,
                    "accepted_live_order_count": 2,
                    "rejected_live_order_count": 0,
                    "tested_order_count": 1,
                    "avg_slippage_bps": 10.0,
                    "avg_edge_retention_ratio": 0.2,
                    "avg_realized_edge_bps": -5.0,
                    "avg_expected_edge_bps": 5.0,
                },
                trades=[
                    {"symbol": "BTCUSDT", "realized_pnl_usd_estimate": -6.0, "realized_return_bps_estimate": -10.0},
                    {"symbol": "BTCUSDT", "realized_pnl_usd_estimate": -4.0, "realized_return_bps_estimate": -8.0},
                ],
                decisions=[
                    {"symbol": "BTCUSDT", "final_mode": "cash", "timestamp": "2026-03-19T00:10:00+00:00", "predictability_score": 45.0, "net_expected_edge_bps": 0.0, "estimated_round_trip_cost_bps": 8.0},
                    {"symbol": "BTCUSDT", "final_mode": "cash", "timestamp": "2026-03-19T00:15:00+00:00", "predictability_score": 46.0, "net_expected_edge_bps": 0.0, "estimated_round_trip_cost_bps": 8.0},
                ],
            )
            (run_a / "policy_state.json").write_text(
                json.dumps(
                    {
                        "version": 7,
                        "active_policy": {"status": "baseline", "adjustments": []},
                        "rollout_progression": {"execution_phase": "baseline"},
                        "updated_at": "2026-03-19T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            (run_b / "policy_state.json").write_text(
                json.dumps(
                    {
                        "version": 6,
                        "active_policy": {"status": "baseline", "adjustments": []},
                        "rollout_progression": {"execution_phase": "baseline"},
                        "updated_at": "2026-03-19T00:10:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            artifact = build_policy_comparison_validation_artifact(
                current_policy_state=current_policy_state,
                candidate_policy=candidate_policy,
                base_dir=base,
                lookback_days=7,
            )
            self.assertTrue(artifact["lineage_attribution"]["applied"])
            self.assertEqual(artifact["lineage_attribution"]["aligned_run_count"], 1)
            self.assertEqual(artifact["lineage_attribution"]["mismatched_run_count"], 1)
            self.assertEqual(artifact["runner_total_realized_pnl_usd"], 4.0)
            self.assertEqual(artifact["validation_path"]["lineage_attribution_mode"], "filtered_to_active_lineage")

    def test_build_policy_comparison_validation_artifact_preserves_legacy_runner_when_run_lineage_is_unknown(self) -> None:
        candidate_policy = {"adjustments": []}
        current_policy_state = {
            "version": 3,
            "active_policy": {"status": "baseline", "adjustments": []},
            "rollout_progression": {"execution_phase": "baseline"},
        }
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_a = base / "output" / "paper-live-shell" / "run-a"
            self._write_watchdog_run(
                run_dir=run_a,
                summary={
                    "generated_at": "2026-03-19T00:00:00+00:00",
                    "live_order_count": 2,
                    "accepted_live_order_count": 2,
                    "rejected_live_order_count": 0,
                    "tested_order_count": 1,
                    "avg_slippage_bps": 2.0,
                    "avg_edge_retention_ratio": 0.8,
                    "avg_realized_edge_bps": 4.0,
                    "avg_expected_edge_bps": 5.0,
                },
                trades=[
                    {"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 2.0, "realized_return_bps_estimate": 6.0},
                ],
                decisions=[
                    {"symbol": "BTCUSDT", "final_mode": "futures", "timestamp": "2026-03-19T00:00:00+00:00", "predictability_score": 70.0, "net_expected_edge_bps": 10.0, "estimated_round_trip_cost_bps": 8.0},
                ],
            )
            artifact = build_policy_comparison_validation_artifact(
                current_policy_state=current_policy_state,
                candidate_policy=candidate_policy,
                base_dir=base,
                lookback_days=7,
            )
            self.assertFalse(artifact["lineage_attribution"]["applied"])
            self.assertEqual(artifact["lineage_attribution"]["mode"], "unfiltered_no_derived_run_lineage")
            self.assertEqual(artifact["runner_total_realized_pnl_usd"], 2.0)

    def test_build_policy_validation_runner_artifact_emits_thin_watchdog_and_checkpoint_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_a = base / "output" / "paper-live-shell" / "run-a"
            self._write_watchdog_run(
                run_dir=run_a,
                summary={
                    "live_order_count": 3,
                    "accepted_live_order_count": 3,
                    "rejected_live_order_count": 0,
                    "tested_order_count": 1,
                    "avg_slippage_bps": 3.0,
                    "avg_edge_retention_ratio": 0.82,
                    "avg_realized_edge_bps": 7.0,
                    "avg_expected_edge_bps": 8.0,
                    "protection_degraded_rate": 0.0,
                },
                trades=[
                    {"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 3.0, "realized_return_bps_estimate": 10.0, "entry_predictability_score": 72.0},
                    {"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 2.5, "realized_return_bps_estimate": 8.0, "entry_predictability_score": 74.0},
                    {"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 1.5, "realized_return_bps_estimate": 6.0, "entry_predictability_score": 76.0},
                ],
                decisions=[
                    {"symbol": "BTCUSDT", "final_mode": "futures", "timestamp": "2026-03-14T00:00:00+00:00", "predictability_score": 72.0, "net_expected_edge_bps": 12.0, "estimated_round_trip_cost_bps": 8.0},
                    {"symbol": "BTCUSDT", "final_mode": "futures", "timestamp": "2026-03-14T00:05:00+00:00", "predictability_score": 74.0, "net_expected_edge_bps": 12.5, "estimated_round_trip_cost_bps": 8.0},
                    {"symbol": "BTCUSDT", "final_mode": "futures", "timestamp": "2026-03-14T00:10:00+00:00", "predictability_score": 76.0, "net_expected_edge_bps": 13.0, "estimated_round_trip_cost_bps": 8.0},
                ],
            )
            artifact = build_policy_validation_runner_artifact(base_dir=base, lookback_days=7)
            watchdog = artifact["sample_quality_watchdog"]
            self.assertEqual(watchdog["status"], "thin")
            self.assertIn("RUN_HISTORY_THIN", watchdog["reason_codes"])
            self.assertEqual(watchdog["metrics"]["dominant_symbol_trade_share"], 1.0)
            self.assertEqual(watchdog["policy_guardrails"]["max_positive_symbols"], 1)
            self.assertEqual(
                watchdog["checkpoint_snapshot"]["symbols"][0]["validation_ready"],
                True,
            )

    def test_build_policy_validation_runner_artifact_emits_promote_ready_watchdog_for_broad_supportive_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_a = base / "output" / "paper-live-shell" / "run-a"
            run_b = base / "output" / "paper-live-shell" / "run-b"
            self._write_watchdog_run(
                run_dir=run_a,
                summary={
                    "live_order_count": 6,
                    "accepted_live_order_count": 6,
                    "rejected_live_order_count": 0,
                    "tested_order_count": 2,
                    "avg_slippage_bps": 3.2,
                    "avg_edge_retention_ratio": 0.83,
                    "avg_realized_edge_bps": 8.5,
                    "avg_expected_edge_bps": 9.4,
                    "protection_degraded_rate": 0.0,
                },
                trades=[
                    {"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 3.0, "realized_return_bps_estimate": 12.0, "entry_predictability_score": 78.0},
                    {"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 2.2, "realized_return_bps_estimate": 9.0, "entry_predictability_score": 76.0},
                    {"symbol": "ETHUSDT", "realized_pnl_usd_estimate": 2.4, "realized_return_bps_estimate": 11.0, "entry_predictability_score": 68.0},
                    {"symbol": "ETHUSDT", "realized_pnl_usd_estimate": 1.8, "realized_return_bps_estimate": 8.0, "entry_predictability_score": 66.0},
                    {"symbol": "SOLUSDT", "realized_pnl_usd_estimate": 1.4, "realized_return_bps_estimate": 7.0, "entry_predictability_score": 58.0},
                ],
                decisions=[
                    {"symbol": "BTCUSDT", "final_mode": "futures", "timestamp": "2026-03-14T00:00:00+00:00", "predictability_score": 78.0, "net_expected_edge_bps": 13.0, "estimated_round_trip_cost_bps": 8.0},
                    {"symbol": "BTCUSDT", "final_mode": "futures", "timestamp": "2026-03-14T00:05:00+00:00", "predictability_score": 76.0, "net_expected_edge_bps": 12.0, "estimated_round_trip_cost_bps": 8.0},
                    {"symbol": "ETHUSDT", "final_mode": "spot", "timestamp": "2026-03-14T00:10:00+00:00", "predictability_score": 68.0, "net_expected_edge_bps": 10.0, "estimated_round_trip_cost_bps": 7.0},
                    {"symbol": "ETHUSDT", "final_mode": "spot", "timestamp": "2026-03-14T00:15:00+00:00", "predictability_score": 66.0, "net_expected_edge_bps": 9.5, "estimated_round_trip_cost_bps": 7.0},
                    {"symbol": "SOLUSDT", "final_mode": "spot", "timestamp": "2026-03-14T00:20:00+00:00", "predictability_score": 58.0, "net_expected_edge_bps": 7.5, "estimated_round_trip_cost_bps": 6.0},
                ],
            )
            self._write_watchdog_run(
                run_dir=run_b,
                summary={
                    "live_order_count": 6,
                    "accepted_live_order_count": 6,
                    "rejected_live_order_count": 0,
                    "tested_order_count": 2,
                    "avg_slippage_bps": 3.5,
                    "avg_edge_retention_ratio": 0.81,
                    "avg_realized_edge_bps": 8.1,
                    "avg_expected_edge_bps": 9.0,
                    "protection_degraded_rate": 0.0,
                },
                trades=[
                    {"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 2.8, "realized_return_bps_estimate": 11.0, "entry_predictability_score": 79.0},
                    {"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 2.0, "realized_return_bps_estimate": 8.0, "entry_predictability_score": 77.0},
                    {"symbol": "ETHUSDT", "realized_pnl_usd_estimate": 2.1, "realized_return_bps_estimate": 9.0, "entry_predictability_score": 69.0},
                    {"symbol": "ETHUSDT", "realized_pnl_usd_estimate": 1.7, "realized_return_bps_estimate": 7.0, "entry_predictability_score": 67.0},
                    {"symbol": "SOLUSDT", "realized_pnl_usd_estimate": 1.2, "realized_return_bps_estimate": 5.0, "entry_predictability_score": 59.0},
                ],
                decisions=[
                    {"symbol": "BTCUSDT", "final_mode": "futures", "timestamp": "2026-03-15T00:00:00+00:00", "predictability_score": 79.0, "net_expected_edge_bps": 13.2, "estimated_round_trip_cost_bps": 8.0},
                    {"symbol": "BTCUSDT", "final_mode": "futures", "timestamp": "2026-03-15T00:05:00+00:00", "predictability_score": 77.0, "net_expected_edge_bps": 12.4, "estimated_round_trip_cost_bps": 8.0},
                    {"symbol": "ETHUSDT", "final_mode": "spot", "timestamp": "2026-03-15T00:10:00+00:00", "predictability_score": 69.0, "net_expected_edge_bps": 10.2, "estimated_round_trip_cost_bps": 7.0},
                    {"symbol": "ETHUSDT", "final_mode": "spot", "timestamp": "2026-03-15T00:15:00+00:00", "predictability_score": 67.0, "net_expected_edge_bps": 9.4, "estimated_round_trip_cost_bps": 7.0},
                    {"symbol": "SOLUSDT", "final_mode": "spot", "timestamp": "2026-03-15T00:20:00+00:00", "predictability_score": 59.0, "net_expected_edge_bps": 7.4, "estimated_round_trip_cost_bps": 6.0},
                ],
            )
            artifact = build_policy_validation_runner_artifact(base_dir=base, lookback_days=7)
            watchdog = artifact["sample_quality_watchdog"]
            self.assertEqual(watchdog["status"], "promote_ready")
            self.assertEqual(watchdog["policy_guardrails"]["allow_alt_promotions"], True)
            self.assertLess(watchdog["metrics"]["dominant_symbol_trade_share"], 0.5)
            self.assertGreaterEqual(watchdog["metrics"]["score_alignment_score"], 0.6)

    def test_build_policy_comparison_validation_artifact_emits_policy_application_delta_and_cumulative_retention(self) -> None:
        candidate_policy = {
            "adjustments": [
                {
                    "symbol": "BTCUSDT",
                    "action": "promote",
                    "size_multiplier": 1.4,
                    "leverage_multiplier": 1.2,
                    "entry_threshold_bps": -2.0,
                    "expected_profit_floor_bps": -3.0,
                }
            ]
        }
        current_policy_state = {
            "rollout_progression": {"execution_phase": "partial"},
            "active_policy": {
                "adjustments": [
                    {
                        "symbol": "BTCUSDT",
                        "action": "promote",
                        "size_multiplier": 1.2,
                        "leverage_multiplier": 1.1,
                        "entry_threshold_bps": -1.0,
                        "expected_profit_floor_bps": -1.0,
                    }
                ]
            },
            "policy_validation": {
                "evidence": {
                    "runner_total_realized_pnl_usd": 4.0,
                    "runner_drawdown_to_pnl_ratio": 0.2,
                    "runner_reject_rate": 0.02,
                    "runner_avg_slippage_bps": 3.0,
                    "runner_avg_realized_edge_bps": 5.0,
                    "runner_avg_edge_retention_ratio": 0.72,
                    "runner_shadow_alignment_score": 0.65,
                    "runner_walk_forward_window_count": 3,
                    "runner_positive_walk_forward_window_count": 2,
                    "runner_positive_walk_forward_ratio": 0.666667,
                    "recent_retention_window": {"run_count": 3},
                    "cumulative_retention_window": {"run_count": 4},
                }
            },
        }
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_root = base / "output" / "paper-live-shell"
            for index, retention, pnl, accepted, rejected in (
                ("run-a", 0.95, 2.0, 2, 0),
                ("run-b", 0.92, 2.0, 2, 0),
                ("run-c", 0.55, 1.0, 2, 1),
                ("run-d", 0.45, 1.0, 1, 1),
            ):
                run_dir = run_root / index
                logs_dir = run_dir / "logs"
                logs_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "summary.json").write_text(
                    json.dumps(
                        {
                            "live_order_count": accepted + rejected,
                            "accepted_live_order_count": accepted,
                            "rejected_live_order_count": rejected,
                            "tested_order_count": 1,
                            "avg_slippage_bps": 3.0 + rejected,
                            "avg_edge_retention_ratio": retention,
                            "avg_realized_edge_bps": 6.0 - rejected,
                            "avg_expected_edge_bps": 8.0,
                        }
                    ),
                    encoding="utf-8",
                )
                (logs_dir / "closed_trades.jsonl").write_text(
                    json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": pnl, "realized_return_bps_estimate": 8.0}) + "\n",
                    encoding="utf-8",
                )
                (logs_dir / "decisions.jsonl").write_text(
                    "\n".join(
                        [
                            json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 70.0, "net_expected_edge_bps": 12.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:00:00+00:00"}),
                            json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 71.0, "net_expected_edge_bps": 11.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:05:00+00:00"}),
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )

            artifact = build_policy_comparison_validation_artifact(
                current_policy_state=current_policy_state,
                candidate_policy=candidate_policy,
                base_dir=base,
                lookback_days=7,
            )
            comparison_summary = artifact["counterfactual_replay_path"]["execution_style_comparison"]["comparison_summary"]
            current_path = artifact["counterfactual_replay_path"]["current_policy"]
            self.assertEqual(artifact["recent_retention_window"]["run_count"], 3)
            self.assertEqual(artifact["cumulative_retention_window"]["run_count"], 4)
            self.assertEqual(current_path["policy_application"]["rollout_phase"], "partial")
            self.assertEqual(current_path["policy_application"]["phase_application_factor"], 0.35)
            self.assertGreater(
                comparison_summary["policy_application_delta"]["avg_size_multiplier_delta"],
                0.0,
            )
            self.assertLess(
                comparison_summary["policy_application_delta"]["avg_entry_threshold_bps_delta"],
                0.0,
            )

    def test_build_policy_comparison_validation_artifact_adds_separated_execution_replay_from_runtime_summary(self) -> None:
        candidate_policy = {
            "adjustments": [
                {
                    "symbol": "BTCUSDT",
                    "action": "aggressive_promote",
                    "size_multiplier": 1.25,
                    "leverage_multiplier": 1.2,
                    "entry_threshold_bps": -1.5,
                    "expected_profit_floor_bps": -2.0,
                }
            ]
        }
        current_policy_state = {
            "rollout_progression": {"execution_phase": "partial"},
            "active_policy": {
                "adjustments": [
                    {
                        "symbol": "BTCUSDT",
                        "action": "promote",
                        "size_multiplier": 1.1,
                        "leverage_multiplier": 1.05,
                        "entry_threshold_bps": -0.5,
                        "expected_profit_floor_bps": -1.0,
                    }
                ]
            },
        }
        runtime_summary = {
            "generated_at": "2026-03-18T00:00:00+00:00",
            "live_order_count": 4,
            "accepted_live_order_count": 4,
            "rejected_live_order_count": 0,
            "closed_trade_count": 1,
            "avg_slippage_bps": 2.5,
            "avg_edge_retention_ratio": 0.82,
            "avg_realized_edge_bps": 6.0,
            "avg_expected_edge_bps": 7.5,
            "realized_pnl_usd_estimate": 5.0,
        }
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
                        "avg_slippage_bps": 3.0,
                        "avg_edge_retention_ratio": 0.8,
                        "avg_realized_edge_bps": 5.5,
                        "avg_expected_edge_bps": 7.0,
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
                        json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 72.0, "net_expected_edge_bps": 12.5, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:05:00+00:00"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            artifact = build_policy_comparison_validation_artifact(
                current_policy_state=current_policy_state,
                candidate_policy=candidate_policy,
                base_dir=base,
                lookback_days=7,
                current_runtime_summary=runtime_summary,
            )
            comparison = artifact["counterfactual_replay_path"]["execution_style_comparison"]["comparison_summary"]
            candidate_path = artifact["counterfactual_replay_path"]["candidate_policy"]
            current_path = artifact["counterfactual_replay_path"]["current_policy"]
            self.assertEqual(
                candidate_path["runtime_summary_anchor"]["source"],
                "current_runtime_summary",
            )
            self.assertEqual(
                current_path["runtime_summary_anchor"]["source"],
                "current_runtime_summary",
            )
            self.assertGreater(
                comparison["execution_metric_delta"]["live_order_count_delta"],
                0.0,
            )
            self.assertNotEqual(
                artifact["candidate_execution_replay_score"],
                artifact["current_execution_replay_score"],
            )
            self.assertEqual(
                artifact["candidate_vs_current_score_delta"],
                artifact["candidate_vs_current_execution_replay_score_delta"],
            )
            self.assertIn(
                artifact["comparison_execution_replay_verdict"],
                {"candidate_better", "keep"},
            )

    def test_build_policy_comparison_validation_artifact_prefers_runtime_summary_closed_trades_over_stale_counters(self) -> None:
        runtime_summary = {
            "generated_at": "2026-03-18T00:00:00+00:00",
            "live_order_count": 2,
            "accepted_live_order_count": 2,
            "rejected_live_order_count": 0,
            "closed_trade_count": 99,
            "realized_pnl_usd_estimate": 999.0,
            "avg_slippage_bps": 2.5,
            "avg_edge_retention_ratio": 0.82,
            "avg_realized_edge_bps": 6.0,
            "avg_expected_edge_bps": 7.5,
            "closed_trades": [
                {"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 5.0, "realized_return_bps_estimate": 10.0},
                {"symbol": "ETHUSDT", "realized_pnl_usd_estimate": 2.0, "realized_return_bps_estimate": 6.0},
            ],
        }
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            artifact = build_policy_comparison_validation_artifact(
                current_policy_state={"active_policy": {"adjustments": []}},
                candidate_policy={"adjustments": []},
                base_dir=base,
                lookback_days=7,
                current_runtime_summary=runtime_summary,
            )
            current_path = artifact["counterfactual_replay_path"]["current_policy"]
            self.assertEqual(current_path["runtime_summary_anchor"]["source"], "current_runtime_summary")
            self.assertEqual(current_path["runtime_summary_anchor"]["closed_trade_count"], 2)
            self.assertEqual(current_path["runtime_summary_anchor"]["realized_pnl_usd"], 7.0)
            self.assertEqual(current_path["execution_metrics"]["closed_trade_count"], 2)
            self.assertEqual(current_path["execution_metrics"]["total_realized_pnl_usd"], 7.0)

    def test_build_policy_comparison_validation_artifact_prefers_latest_run_closed_trades_when_summary_has_stale_counters(self) -> None:
        runtime_summary = {
            "generated_at": "2026-03-18T00:00:00+00:00",
            "live_order_count": 3,
            "accepted_live_order_count": 3,
            "rejected_live_order_count": 0,
            "closed_trade_count": 99,
            "realized_pnl_usd_estimate": 999.0,
            "avg_slippage_bps": 2.5,
            "avg_edge_retention_ratio": 0.82,
            "avg_realized_edge_bps": 6.0,
            "avg_expected_edge_bps": 7.5,
        }
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_a = base / "output" / "paper-live-shell" / "run-a"
            logs_dir = run_a / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (run_a / "summary.json").write_text(
                json.dumps({"closed_trade_count": 1, "realized_pnl_usd_estimate": 1.0}),
                encoding="utf-8",
            )
            (logs_dir / "closed_trades.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 4.0, "realized_return_bps_estimate": 10.0}),
                        json.dumps({"symbol": "ETHUSDT", "realized_pnl_usd_estimate": -1.5, "realized_return_bps_estimate": -4.0}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (logs_dir / "decisions.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 70.0, "net_expected_edge_bps": 12.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:00:00+00:00"})
                + "\n",
                encoding="utf-8",
            )

            artifact = build_policy_comparison_validation_artifact(
                current_policy_state={"active_policy": {"adjustments": []}},
                candidate_policy={"adjustments": []},
                base_dir=base,
                lookback_days=7,
                current_runtime_summary=runtime_summary,
            )

            current_path = artifact["counterfactual_replay_path"]["current_policy"]
            self.assertEqual(current_path["runtime_summary_anchor"]["source"], "current_runtime_summary")
            self.assertEqual(current_path["runtime_summary_anchor"]["closed_trade_count"], 2)
            self.assertEqual(current_path["runtime_summary_anchor"]["realized_pnl_usd"], 2.5)
            self.assertEqual(current_path["execution_metrics"]["closed_trade_count"], 2)
            self.assertEqual(current_path["execution_metrics"]["total_realized_pnl_usd"], 2.5)

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
            self.assertEqual(artifact["recent_retention_window"]["run_count"], 1)
            self.assertEqual(artifact["cumulative_retention_window"]["run_count"], 1)

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
            self.assertEqual(artifact["sample_progress"]["status"], "collecting_evidence")
            self.assertEqual(artifact["score_alignment_summary"][0]["score_bucket_label"], "00-09")
            self.assertEqual(artifact["total_closed_trade_count"], 3)
            self.assertEqual(artifact["runner_total_return_pct"], 0.0)
            self.assertTrue(any(row["mode"] == "futures" for row in artifact["regime_summary"]))
            self.assertEqual(artifact["evidence"]["score_alignment_summary"][0]["trade_count"], 3)
            self.assertTrue(artifact["symbol_lifecycle"])
            self.assertEqual(artifact["symbol_lifecycle_summary"]["symbol_count"], len(artifact["symbol_lifecycle"]))

    def test_build_policy_validation_runner_artifact_tracks_recent_and_cumulative_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_root = base / "output" / "paper-live-shell"
            for index, retention in enumerate((0.95, 0.9, 0.5, 0.4), start=1):
                run_dir = run_root / f"run-{index}"
                logs_dir = run_dir / "logs"
                logs_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "summary.json").write_text(
                    json.dumps(
                        {
                            "live_order_count": 2,
                            "accepted_live_order_count": 2,
                            "rejected_live_order_count": 0,
                            "avg_slippage_bps": 3.0,
                            "avg_edge_retention_ratio": retention,
                            "avg_realized_edge_bps": 6.0,
                            "avg_expected_edge_bps": 8.0,
                        }
                    ),
                    encoding="utf-8",
                )
                (logs_dir / "closed_trades.jsonl").write_text(
                    json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 1.0, "realized_return_bps_estimate": 8.0}) + "\n",
                    encoding="utf-8",
                )
                (logs_dir / "decisions.jsonl").write_text(
                    "\n".join(
                        [
                            json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 70.0, "net_expected_edge_bps": 12.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:00:00+00:00"}),
                            json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 71.0, "net_expected_edge_bps": 11.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:05:00+00:00"}),
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )
            artifact = build_policy_validation_runner_artifact(base_dir=base, lookback_days=7)
            self.assertEqual(artifact["recent_retention_window"]["run_count"], 3)
            self.assertEqual(artifact["cumulative_retention_window"]["run_count"], 4)
            self.assertLess(
                artifact["recent_retention_window"]["avg_edge_retention_ratio"],
                artifact["cumulative_retention_window"]["avg_edge_retention_ratio"],
            )

    def test_build_policy_validation_runner_artifact_emits_policy_context_bucket_symbol_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_dir = base / "output" / "paper-live-shell" / "run-a"
            logs_dir = run_dir / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "summary.json").write_text(
                json.dumps({"live_order_count": 0, "tested_order_count": 0}),
                encoding="utf-8",
            )
            (logs_dir / "closed_trades.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "symbol": "BTCUSDT",
                                "realized_pnl_usd_estimate": 3.0,
                                "realized_return_bps_estimate": 8.0,
                                "entry_policy_bucket": "active_policy",
                                "entry_policy_bucket_available": True,
                                "entry_policy_bucket_alignment_status": "aligned",
                            }
                        ),
                        json.dumps(
                            {
                                "symbol": "ETHUSDT",
                                "realized_pnl_usd_estimate": 1.0,
                                "realized_return_bps_estimate": 2.0,
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
                                "predictability_score": 70.0,
                                "net_expected_edge_bps": 12.0,
                                "estimated_round_trip_cost_bps": 8.0,
                                "timestamp": "2026-03-14T00:00:00+00:00",
                                "entry_policy_bucket": "active_policy",
                                "entry_policy_bucket_available": True,
                                "entry_policy_bucket_alignment_status": "aligned",
                            }
                        ),
                        json.dumps(
                            {
                                "symbol": "ETHUSDT",
                                "final_mode": "futures",
                                "predictability_score": 68.0,
                                "net_expected_edge_bps": 10.0,
                                "estimated_round_trip_cost_bps": 8.0,
                                "timestamp": "2026-03-14T00:05:00+00:00",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (logs_dir / "live_orders.jsonl").write_text(
                json.dumps(
                    {
                        "symbol": "BTCUSDT",
                        "accepted": True,
                        "slippage_bps": 2.0,
                        "realized_edge_bps": 6.0,
                        "expected_net_edge_bps": 8.0,
                        "entry_policy_bucket": "active_policy",
                        "entry_policy_bucket_available": True,
                        "entry_policy_bucket_alignment_status": "aligned",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (logs_dir / "tested_orders.jsonl").write_text(
                json.dumps(
                    {
                        "symbol": "BTCUSDT",
                        "entry_policy_bucket": "active_policy",
                        "entry_policy_bucket_available": True,
                        "entry_policy_bucket_alignment_status": "aligned",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (logs_dir / "order_errors.jsonl").write_text(
                json.dumps(
                    {
                        "symbol": "BTCUSDT",
                        "stage": "protection_order",
                        "error": "timeout",
                        "entry_policy_bucket": "active_policy",
                        "entry_policy_bucket_available": True,
                        "entry_policy_bucket_alignment_status": "aligned",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            artifact = build_policy_validation_runner_artifact(base_dir=base, lookback_days=7)
            bucket_evidence = artifact["policy_context_bucket_evidence"]["active_policy"]
            self.assertEqual(bucket_evidence["policy_context_bucket_name"], "active_policy")
            self.assertEqual(bucket_evidence["policy_context_bucket_symbol_summary"][0]["symbol"], "BTCUSDT")
            self.assertEqual(bucket_evidence["policy_context_bucket_symbol_summary"][0]["trade_count"], 1)
            self.assertEqual(bucket_evidence["policy_context_bucket_pruning_recommendations"][0]["symbol"], "BTCUSDT")
            self.assertEqual(bucket_evidence["live_order_count"], 1)
            self.assertEqual(bucket_evidence["tested_order_count"], 1)
            self.assertEqual(bucket_evidence["avg_edge_retention_ratio"], 0.75)

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
                        "entry_predictability_score": 74.0,
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
                        "entry_predictability_score": 74.0,
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
            self.assertEqual(report.sample_progress["status"], "collecting_evidence")
            self.assertEqual(report.sample_progress["remaining_closed_trade_count"], 4)
            self.assertEqual(report.sample_progress["remaining_live_order_count"], 5)
            self.assertEqual(report.score_alignment_summary[0]["score_bucket_label"], "70-79")
            self.assertEqual(report.score_alignment_summary[0]["trade_count"], 2)
            symbols = {row["symbol"]: row for row in report.symbol_summary}
            self.assertEqual(symbols["BTCUSDT"]["sample_status"], "warming_up")
            self.assertEqual(symbols["BTCUSDT"]["remaining_trade_count_for_validation"], 1)
            self.assertTrue(symbols["BTCUSDT"]["rolling_evidence"]["available"])
            self.assertEqual(symbols["BTCUSDT"]["rolling_evidence"]["observed_run_count"], 2)
            self.assertEqual(symbols["BTCUSDT"]["rolling_evidence"]["positive_window_ratio"], 0.5)
            self.assertEqual(symbols["BTCUSDT"]["rolling_evidence"]["recent_run_consistency"], 0.5)
            self.assertEqual(symbols["BTCUSDT"]["rolling_evidence"]["expectancy_stability"], 0.0)
            self.assertIn("BTCUSDT", symbols)
            self.assertIn("ETHUSDT", {row["symbol"]: row for row in report.symbol_summary} | {"ETHUSDT": {}})
            self.assertTrue(any(row["mode"] == "futures" for row in report.regime_summary))
            self.assertTrue(any(item.category == "prune" for item in report.criteria))


if __name__ == "__main__":
    unittest.main()
