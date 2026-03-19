from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant_binance.observability.report import build_persisted_policy_state, build_policy_validation, build_promotion_verdict
from quant_binance.promotion import apply_strategy_proposal, build_strategy_proposal
from quant_binance.validation_report import build_policy_comparison_validation_artifact


class QuantBinanceCheckpointAutoJudgeTests(unittest.TestCase):
    def _write_run(
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

    def test_policy_comparison_artifact_emits_checkpoint_auto_judge(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_a = base / "output" / "paper-live-shell" / "run-a"
            comparison_run = base / "output" / "strategy-comparison-recent" / "run-b"
            comparison_run.mkdir(parents=True, exist_ok=True)
            (comparison_run / "comparison.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {"strategy_name": "current_strategy", "trade_count": 3, "total_pnl_usd": 0.1, "total_return_pct": 0.01},
                            {"strategy_name": "directional_hold", "trade_count": 3, "total_pnl_usd": 0.8, "total_return_pct": 0.06},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self._write_run(
                run_dir=run_a,
                summary={
                    "live_order_count": 8,
                    "accepted_live_order_count": 6,
                    "rejected_live_order_count": 2,
                    "tested_order_count": 2,
                    "avg_slippage_bps": 14.5,
                    "avg_edge_retention_ratio": 0.3,
                    "avg_realized_edge_bps": -2.5,
                    "avg_expected_edge_bps": 8.0,
                    "protection_degraded_rate": 0.2,
                },
                trades=[
                    {"symbol": "BTCUSDT", "realized_pnl_usd_estimate": -4.0, "realized_return_bps_estimate": -10.0, "entry_predictability_score": 72.0},
                    {"symbol": "BTCUSDT", "realized_pnl_usd_estimate": -3.0, "realized_return_bps_estimate": -8.0, "entry_predictability_score": 71.0},
                    {"symbol": "BTCUSDT", "realized_pnl_usd_estimate": -2.0, "realized_return_bps_estimate": -6.0, "entry_predictability_score": 69.0},
                    {"symbol": "ETHUSDT", "realized_pnl_usd_estimate": -2.5, "realized_return_bps_estimate": -7.0, "entry_predictability_score": 66.0},
                    {"symbol": "ETHUSDT", "realized_pnl_usd_estimate": -1.5, "realized_return_bps_estimate": -5.0, "entry_predictability_score": 64.0},
                    {"symbol": "SOLUSDT", "realized_pnl_usd_estimate": -1.0, "realized_return_bps_estimate": -4.0, "entry_predictability_score": 55.0},
                ],
                decisions=[
                    {"symbol": "BTCUSDT", "final_mode": "futures", "timestamp": "2026-03-14T00:00:00+00:00", "predictability_score": 72.0, "net_expected_edge_bps": 6.0, "estimated_round_trip_cost_bps": 8.0},
                    {"symbol": "BTCUSDT", "final_mode": "futures", "timestamp": "2026-03-14T00:05:00+00:00", "predictability_score": 71.0, "net_expected_edge_bps": 5.5, "estimated_round_trip_cost_bps": 8.0},
                    {"symbol": "BTCUSDT", "final_mode": "cash", "timestamp": "2026-03-14T00:10:00+00:00", "predictability_score": 69.0, "net_expected_edge_bps": 0.0, "estimated_round_trip_cost_bps": 8.0, "rejection_reasons": ["EDGE_TOO_THIN"]},
                    {"symbol": "ETHUSDT", "final_mode": "spot", "timestamp": "2026-03-14T00:15:00+00:00", "predictability_score": 66.0, "net_expected_edge_bps": 4.0, "estimated_round_trip_cost_bps": 7.0},
                    {"symbol": "ETHUSDT", "final_mode": "cash", "timestamp": "2026-03-14T00:20:00+00:00", "predictability_score": 64.0, "net_expected_edge_bps": 0.0, "estimated_round_trip_cost_bps": 7.0, "rejection_reasons": ["LIQUIDITY_TOO_WEAK"]},
                    {"symbol": "SOLUSDT", "final_mode": "cash", "timestamp": "2026-03-14T00:25:00+00:00", "predictability_score": 55.0, "net_expected_edge_bps": 0.0, "estimated_round_trip_cost_bps": 6.0, "rejection_reasons": ["EDGE_TOO_THIN"]},
                ],
            )
            artifact = build_policy_comparison_validation_artifact(
                current_policy_state={
                    "active_policy": {
                        "status": "promote",
                        "adjustments": [{"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.1}],
                    }
                },
                candidate_policy={"adjustments": []},
                base_dir=base,
                lookback_days=7,
            )
            judge = artifact["checkpoint_auto_judge"]
            self.assertEqual(judge["verdict"], "rollback")
            self.assertEqual(judge["baseline_control_comparison"]["verdict"], "caution")
            self.assertEqual(artifact["auto_mode"]["mode"], "tighter")
            self.assertIn("AUTO_MODE_TIGHTENED_BY_CHECKPOINT_ROLLBACK", artifact["auto_mode"]["reason_codes"])
            self.assertEqual(artifact["evidence"]["checkpoint_auto_judge"], judge)

    def test_policy_comparison_artifact_does_not_claim_simple_baseline_gate_with_thin_comparison_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            run_a = base / "output" / "paper-live-shell" / "run-a"
            comparison_run = base / "output" / "strategy-comparison-recent" / "run-b"
            comparison_run.mkdir(parents=True, exist_ok=True)
            (comparison_run / "comparison.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {"strategy_name": "current_strategy", "trade_count": 2, "total_pnl_usd": 0.4, "total_return_pct": 0.04},
                            {"strategy_name": "directional_hold", "trade_count": 2, "total_pnl_usd": 0.3, "total_return_pct": 0.03},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self._write_run(
                run_dir=run_a,
                summary={
                    "live_order_count": 2,
                    "accepted_live_order_count": 2,
                    "rejected_live_order_count": 0,
                    "avg_slippage_bps": 2.0,
                    "avg_edge_retention_ratio": 0.8,
                    "avg_realized_edge_bps": 4.0,
                    "avg_expected_edge_bps": 8.0,
                },
                trades=[
                    {"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 2.0, "realized_return_bps_estimate": 5.0},
                ],
                decisions=[
                    {"symbol": "BTCUSDT", "final_mode": "futures", "timestamp": "2026-03-14T00:00:00+00:00", "predictability_score": 72.0, "net_expected_edge_bps": 12.0, "estimated_round_trip_cost_bps": 8.0},
                ],
            )
            artifact = build_policy_comparison_validation_artifact(
                current_policy_state={"active_policy": {"status": "baseline", "adjustments": []}},
                candidate_policy={"adjustments": []},
                base_dir=base,
                lookback_days=7,
            )
            baseline = artifact["baseline_control_comparison"]
            self.assertEqual(baseline["verdict"], "not_available")
            self.assertEqual(baseline["expansion_gate"], "not_available")
            self.assertEqual(baseline["reason"], "RECENT_BASELINE_CONTROL_EVIDENCE_THIN")

    def test_build_policy_validation_fails_when_checkpoint_auto_judge_requests_rollback(self) -> None:
        validation = build_policy_validation(
            candidate_policy={"adjustments": [{"symbol": "BTCUSDT", "action": "promote"}]},
            promotion_verdict={"status": "promote", "requested_status": "promote", "rollout_stage": "promotion_active"},
            operational_verdict={"status": "pass", "reasons": []},
            runner_evidence={
                "checkpoint_auto_judge": {"verdict": "rollback"},
                "sample_quality_watchdog": {"status": "degraded"},
                "runner_total_realized_pnl_usd": -10.0,
                "runner_drawdown_to_pnl_ratio": 1.0,
                "runner_reject_rate": 0.2,
                "runner_protection_degraded_rate": 0.2,
                "runner_avg_edge_retention_ratio": 0.2,
                "runner_positive_walk_forward_ratio": 0.0,
            },
        )
        self.assertEqual(validation["status"], "fail")
        self.assertIn("CHECKPOINT_AUTO_JUDGE_ROLLBACK", validation["reasons"])

    def test_build_promotion_verdict_blocks_expansion_when_simple_baseline_only_reaches_parity(self) -> None:
        verdict = build_promotion_verdict(
            {
                "adjustments": [
                    {"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.1},
                ]
            },
            {
                "comparison_verdict": "candidate_better",
                "candidate_vs_current_score_delta": 0.2,
                "runner_total_realized_pnl_usd": 6.0,
                "runner_drawdown_to_pnl_ratio": 0.2,
                "runner_reject_rate": 0.01,
                "runner_avg_slippage_bps": 2.0,
                "runner_avg_edge_retention_ratio": 0.82,
                "runner_walk_forward_window_count": 3,
                "runner_positive_walk_forward_ratio": 1.0,
                "micro_live_gate": {"available": True, "status": "pass"},
                "baseline_control_comparison": {
                    "available": True,
                    "verdict": "parity",
                    "expansion_gate": "block",
                    "expansion_gate_reason": "SIMPLE_BASELINE_CONTROL_NOT_CLEARLY_BEATEN",
                    "best_simple_baseline": {"strategy_name": "directional_hold"},
                },
            },
        )
        self.assertEqual(verdict["status"], "keep")
        self.assertIn("PROMOTION_BLOCKED_BY_SIMPLE_BASELINE_PARITY", verdict["reasons"])
        self.assertEqual(verdict["simple_baseline_gate_status"], "block")
        self.assertEqual(
            verdict["baseline_control_comparison"]["best_simple_baseline"]["strategy_name"],
            "directional_hold",
        )

    def test_build_policy_validation_fails_when_simple_baseline_gate_blocks_promotion(self) -> None:
        validation = build_policy_validation(
            candidate_policy={"adjustments": [{"symbol": "BTCUSDT", "action": "promote"}]},
            promotion_verdict={
                "status": "keep",
                "requested_status": "promote",
                "rollout_stage": "promotion_blocked",
            },
            operational_verdict={"status": "pass", "reasons": []},
            runner_evidence={
                "candidate_vs_current_score_delta": 0.2,
                "runner_total_realized_pnl_usd": 6.0,
                "runner_drawdown_to_pnl_ratio": 0.2,
                "runner_reject_rate": 0.01,
                "runner_avg_slippage_bps": 2.0,
                "runner_avg_edge_retention_ratio": 0.82,
                "runner_positive_walk_forward_ratio": 1.0,
                "micro_live_gate": {"available": True, "status": "pass"},
                "baseline_control_comparison": {
                    "available": True,
                    "verdict": "parity",
                    "expansion_gate": "block",
                    "expansion_gate_reason": "SIMPLE_BASELINE_CONTROL_NOT_CLEARLY_BEATEN",
                },
            },
        )
        self.assertEqual(validation["status"], "fail")
        self.assertIn("SIMPLE_BASELINE_CONTROL_NOT_CLEARLY_BEATEN", validation["reasons"])
        self.assertIn("PROMOTION_PATH_BLOCKED_BY_SIMPLE_BASELINE_CONTROL", validation["reasons"])

    def test_build_promotion_verdict_blocks_promotion_when_symbol_lifecycle_requires_hold(self) -> None:
        verdict = build_promotion_verdict(
            {
                "adjustments": [
                    {"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.1},
                ]
            },
            {
                "comparison_verdict": "candidate_better",
                "candidate_vs_current_score_delta": 0.2,
                "runner_total_realized_pnl_usd": 6.0,
                "runner_drawdown_to_pnl_ratio": 0.2,
                "runner_reject_rate": 0.01,
                "runner_avg_slippage_bps": 2.0,
                "runner_avg_edge_retention_ratio": 0.82,
                "runner_walk_forward_window_count": 3,
                "runner_positive_walk_forward_ratio": 1.0,
                "micro_live_gate": {"available": True, "status": "pass"},
                "symbol_lifecycle": [
                    {
                        "symbol": "BTCUSDT",
                        "current_state": "observe_only",
                        "target_state": "observe_only",
                        "recommended_action": "hold",
                    }
                ],
            },
        )
        self.assertEqual(verdict["status"], "keep")
        self.assertIn("PROMOTION_BLOCKED_BY_SYMBOL_LIFECYCLE_HOLD", verdict["reasons"])
        self.assertEqual(verdict["symbol_lifecycle_signal"]["blocked_symbols"], ["BTCUSDT"])

    def test_build_persisted_policy_state_rolls_back_on_checkpoint_auto_judge(self) -> None:
        state = build_persisted_policy_state(
            {
                "version": 4,
                "active_policy": {"status": "promote", "adjustments": [{"symbol": "BTCUSDT", "action": "promote"}]},
                "rollout_status": "ready",
            },
            {"adjustments": [{"symbol": "BTCUSDT", "action": "promote"}]},
            {"status": "keep", "reasons": []},
            {"status": "pass", "reasons": []},
            {"status": "pass", "evidence": {"checkpoint_auto_judge": {"verdict": "rollback"}}},
        )
        self.assertEqual(state["status"], "rolled_back")
        self.assertEqual(state["rollout_reason"], "CHECKPOINT_AUTO_JUDGE_ROLLBACK")
        self.assertEqual(state["active_policy"]["status"], "baseline")
        self.assertEqual(state["checkpoint_auto_judge"]["verdict"], "rollback")

    def test_build_persisted_policy_state_tightens_active_policy_when_simple_baseline_gate_blocks_expansion(self) -> None:
        state = build_persisted_policy_state(
            {
                "version": 4,
                "active_policy": {
                    "status": "promote",
                    "adjustments": [{"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.15, "leverage_multiplier": 1.1}],
                },
                "rollout_status": "ready",
            },
            {"adjustments": [{"symbol": "BTCUSDT", "action": "promote"}]},
            {"status": "keep", "requested_status": "promote", "reasons": ["PROMOTION_BLOCKED_BY_SIMPLE_BASELINE_PARITY"]},
            {"status": "pass", "reasons": []},
            {
                "status": "fail",
                "evidence": {
                    "checkpoint_auto_judge": {
                        "verdict": "tighten",
                        "reason_codes": ["SIMPLE_BASELINE_CONTROL_NOT_CLEARLY_BEATEN"],
                    },
                    "baseline_control_comparison": {
                        "available": True,
                        "verdict": "parity",
                        "expansion_gate": "block",
                        "expansion_gate_reason": "SIMPLE_BASELINE_CONTROL_NOT_CLEARLY_BEATEN",
                    },
                },
            },
        )
        self.assertEqual(state["status"], "checkpoint_tightened")
        self.assertEqual(state["rollout_status"], "checkpoint_tightened")
        self.assertEqual(state["rollout_reason"], "SIMPLE_BASELINE_CONTROL_NOT_CLEARLY_BEATEN")
        self.assertEqual(state["active_policy"]["status"], "demote")
        self.assertEqual(state["active_policy"]["adjustments"][0]["reason"], "SIMPLE_BASELINE_CONTROL_NOT_CLEARLY_BEATEN")

    def test_strategy_proposal_is_not_ready_when_checkpoint_auto_judge_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            (base / "artifacts" / "optimization").mkdir(parents=True, exist_ok=True)
            (base / "output" / "paper-live-shell" / "run-a").mkdir(parents=True, exist_ok=True)
            (base / "output" / "strategy-comparison-recent" / "run-b").mkdir(parents=True, exist_ok=True)
            (base / "artifacts" / "optimization" / "latest.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-14T00:00:00+00:00",
                        "best_candidate": {
                            "name": "candidate-a",
                            "objective_score": 12.5,
                            "overrides": {"mode_thresholds": {"futures_score_min": 50}},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (base / "output" / "paper-live-shell" / "run-a" / "performance_report.json").write_text(
                json.dumps({"pruning_recommendations": []}),
                encoding="utf-8",
            )
            (base / "output" / "paper-live-shell" / "run-a" / "policy_comparison.json").write_text(
                json.dumps(
                    {
                        "checkpoint_auto_judge": {
                            "verdict": "tighten",
                            "confidence": "medium",
                            "reason_codes": ["SAMPLE_QUALITY_WATCHDOG_DEGRADED"],
                        }
                    }
                ),
                encoding="utf-8",
            )
            (base / "output" / "strategy-comparison-recent" / "run-b" / "comparison.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {"strategy_name": "current_strategy", "total_pnl_usd": 1.2},
                            {"strategy_name": "simple_momentum", "total_pnl_usd": 0.5},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            proposal = build_strategy_proposal(base_dir=base)
            self.assertEqual(proposal["status"], "proposal_pending")
            self.assertEqual(proposal["gates"]["checkpoint_auto_judge_verdict"], "tighten")
            apply_result = apply_strategy_proposal(base_dir=base)
            self.assertEqual(apply_result["status"], "proposal_not_ready")
            self.assertEqual(apply_result["proposal_status"], "proposal_pending")

    def test_strategy_proposal_uses_simple_baseline_gate_when_checkpoint_judge_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            (base / "artifacts" / "optimization").mkdir(parents=True, exist_ok=True)
            (base / "output" / "paper-live-shell" / "run-a").mkdir(parents=True, exist_ok=True)
            (base / "output" / "strategy-comparison-recent" / "run-b").mkdir(parents=True, exist_ok=True)
            (base / "artifacts" / "optimization" / "latest.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-14T00:00:00+00:00",
                        "best_candidate": {
                            "name": "candidate-a",
                            "objective_score": 12.5,
                            "overrides": {"mode_thresholds": {"futures_score_min": 50}},
                        },
                    }
                ),
                encoding="utf-8",
            )
            (base / "output" / "paper-live-shell" / "run-a" / "performance_report.json").write_text(
                json.dumps({"pruning_recommendations": []}),
                encoding="utf-8",
            )
            (base / "output" / "paper-live-shell" / "run-a" / "policy_comparison.json").write_text(
                json.dumps(
                    {
                        "baseline_control_comparison": {
                            "available": True,
                            "verdict": "parity",
                            "expansion_gate": "block",
                            "expansion_gate_reason": "SIMPLE_BASELINE_CONTROL_NOT_CLEARLY_BEATEN",
                            "best_simple_baseline": {"strategy_name": "directional_hold"},
                        }
                    }
                ),
                encoding="utf-8",
            )
            (base / "output" / "strategy-comparison-recent" / "run-b" / "comparison.json").write_text(
                json.dumps(
                    {
                        "strategies": [
                            {"strategy_name": "current_strategy", "total_pnl_usd": 1.2},
                            {"strategy_name": "directional_hold", "total_pnl_usd": 1.1},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            proposal = build_strategy_proposal(base_dir=base)
            self.assertEqual(proposal["status"], "proposal_pending")
            self.assertEqual(proposal["gates"]["simple_baseline_gate_status"], "block")
            self.assertEqual(proposal["gates"]["simple_baseline_strategy"], "directional_hold")
            apply_result = apply_strategy_proposal(base_dir=base)
            self.assertEqual(apply_result["status"], "proposal_not_ready")
            self.assertEqual(
                apply_result["baseline_control_comparison"]["best_simple_baseline"]["strategy_name"],
                "directional_hold",
            )


if __name__ == "__main__":
    unittest.main()
