from __future__ import annotations

import unittest

from quant_binance.observability.report import build_auto_tune_policy, build_persisted_policy_state
from quant_binance.policy_lineage import build_policy_lineage_snapshot
from quant_binance.symbol_lifecycle import build_symbol_lifecycle


class QuantBinanceSymbolLifecycleTests(unittest.TestCase):
    def test_build_symbol_lifecycle_ignores_previous_state_when_policy_lineage_mismatches(self) -> None:
        rows = build_symbol_lifecycle(
            symbol_summary=[
                {
                    "symbol": "BTCUSDT",
                    "trade_count": 3,
                    "required_trade_count_for_validation": 3,
                    "recommendation": "promote",
                    "rolling_evidence": {
                        "observed_run_count": 2,
                        "positive_window_ratio": 0.8,
                        "recent_run_consistency": 1.0,
                    },
                }
            ],
            symbol_scorecard=[
                {
                    "symbol": "BTCUSDT",
                    "recommendation": "promote",
                }
            ],
            previous_rows=[
                {
                    "symbol": "BTCUSDT",
                    "current_state": "promoted",
                    "target_state": "promoted",
                    "active_policy_action": "promote",
                    "policy_lineage": build_policy_lineage_snapshot(
                        policy={
                            "status": "promote",
                            "adjustments": [{"symbol": "BTCUSDT", "action": "promote"}],
                        },
                        rollout_phase="full",
                        policy_status="promote",
                        version=1,
                        updated_at="2026-03-18T00:00:00+00:00",
                        source="test_previous_state",
                    ),
                }
            ],
            sample_quality_watchdog={"status": "healthy"},
            active_policy={"status": "baseline", "adjustments": []},
            rollout_phase="baseline",
            policy_version=2,
            evaluated_at="2026-03-19T00:00:00+00:00",
        )

        row = rows[0]
        self.assertEqual(row["current_state"], "baseline")
        self.assertFalse(row["policy_context_fresh"])
        self.assertEqual(row["policy_context_alignment"]["reason"], "POLICY_VERSION_MISMATCH")
        self.assertIn("POLICY_VERSION_MISMATCH", row["reason_codes"])

    def test_build_symbol_lifecycle_keeps_previous_state_when_structural_lineage_matches(self) -> None:
        active_adjustments = [{"symbol": "BTCUSDT", "action": "promote"}]

        rows = build_symbol_lifecycle(
            active_adjustments=active_adjustments,
            previous_rows=[
                {
                    "symbol": "BTCUSDT",
                    "current_state": "promoted",
                    "target_state": "promoted",
                    "active_policy_action": "promote",
                    "policy_lineage": build_policy_lineage_snapshot(
                        policy={"status": "promote", "adjustments": active_adjustments},
                        rollout_phase="full",
                        policy_status="promote",
                        version=1,
                        updated_at="2026-03-18T00:00:00+00:00",
                        source="test_previous_state",
                    ),
                }
            ],
            active_policy={"status": "promote", "adjustments": active_adjustments},
            rollout_phase="full",
            policy_version=2,
            evaluated_at="2026-03-19T00:00:00+00:00",
        )

        row = rows[0]
        self.assertEqual(row["current_state"], "promoted")
        self.assertTrue(row["policy_context_fresh"])
        self.assertEqual(row["policy_context_alignment"]["reason"], "POLICY_LINEAGE_MATCH")

    def test_build_auto_tune_policy_blocks_symbol_promotion_when_lifecycle_requires_review(self) -> None:
        policy = build_auto_tune_policy(
            [],
            {
                "symbol_summary": [
                    {
                        "symbol": "BTCUSDT",
                        "trade_count": 3,
                        "expectancy_usd": 4.5,
                        "recommendation": "promote",
                    },
                ],
                "regime_summary": [
                    {"mode": "futures", "decision_count": 6, "avg_score": 70.0, "avg_net_edge_bps": 12.0, "avg_cost_bps": 8.0},
                ],
                "symbol_lifecycle": [
                    {
                        "symbol": "BTCUSDT",
                        "current_state": "observe_only",
                        "target_state": "re_review",
                        "recommended_action": "re_review",
                    }
                ],
            },
        )

        self.assertEqual(policy["adjustments"], [])
        self.assertEqual(
            policy["decomposition_summary"]["symbol_lifecycle_overlay"]["blocked_symbols"],
            ["BTCUSDT"],
        )

    def test_build_auto_tune_policy_downgrades_aggressive_repromotion_when_lifecycle_requires_caution(self) -> None:
        policy = build_auto_tune_policy(
            [],
            {
                "symbol_summary": [
                    {
                        "symbol": "BTCUSDT",
                        "trade_count": 3,
                        "expectancy_usd": 5.0,
                        "recommendation": "promote",
                    },
                ],
                "regime_summary": [
                    {"mode": "futures", "decision_count": 6, "avg_score": 72.0, "avg_net_edge_bps": 13.0, "avg_cost_bps": 8.0},
                ],
                "symbol_lifecycle": [
                    {
                        "symbol": "BTCUSDT",
                        "current_state": "demoted",
                        "target_state": "cautious_repromotion",
                        "recommended_action": "cautious_repromote",
                    }
                ],
            },
        )

        adjustment = policy["adjustments"][0]
        self.assertEqual(adjustment["action"], "promote")
        self.assertEqual(adjustment["reason"], "SYMBOL_LIFECYCLE_CAUTIOUS_REPROMOTION")
        self.assertIn("symbol_lifecycle", adjustment["signal_sources"])

    def test_build_symbol_lifecycle_requires_re_review_when_bucket_scope_has_no_symbol_evidence(self) -> None:
        active_policy = {
            "status": "promote",
            "adjustments": [{"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.1}],
        }
        active_lineage = build_policy_lineage_snapshot(
            policy=active_policy,
            rollout_phase="full",
            policy_status="promote",
            version=3,
            updated_at="2026-03-19T00:00:00+00:00",
            source="test_active_policy",
        )
        rows = build_symbol_lifecycle(
            symbol_summary=[
                {
                    "symbol": "BTCUSDT",
                    "trade_count": 4,
                    "required_trade_count_for_validation": 3,
                    "recommendation": "promote",
                    "rolling_evidence": {
                        "observed_run_count": 3,
                        "positive_window_ratio": 1.0,
                        "recent_run_consistency": 1.0,
                    },
                }
            ],
            symbol_scorecard=[
                {
                    "symbol": "BTCUSDT",
                    "recommendation": "promote",
                }
            ],
            policy_context_bucket_name="active_policy",
            active_adjustments=[{"symbol": "BTCUSDT", "action": "promote"}],
            previous_rows=[
                {
                    "symbol": "BTCUSDT",
                    "current_state": "promoted",
                    "target_state": "promoted",
                    "active_policy_action": "promote",
                    "policy_lineage": dict(active_lineage),
                }
            ],
            sample_quality_watchdog={"status": "healthy"},
            active_policy=active_policy,
            rollout_phase="full",
            policy_version=3,
            evaluated_at="2026-03-19T00:00:00+00:00",
        )

        row = rows[0]
        self.assertEqual(row["current_state"], "promoted")
        self.assertEqual(row["recommended_action"], "re_review")
        self.assertEqual(row["symbol_evidence_source"], "policy_context_bucket")
        self.assertFalse(row["policy_context_bucket_evidence_available"])
        self.assertIn("POLICY_CONTEXT_BUCKET_ACTIVE_POLICY_NO_SYMBOL_EVIDENCE", row["reason_codes"])

    def test_build_persisted_policy_state_demotes_active_promotions_when_symbol_lifecycle_requests_rollback(self) -> None:
        state = build_persisted_policy_state(
            {
                "version": 2,
                "active_policy": {
                    "status": "promote",
                    "adjustments": [
                        {"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.15, "leverage_multiplier": 1.1},
                    ],
                },
                "rollout_status": "ready",
            },
            {
                "adjustments": [
                    {"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.15, "leverage_multiplier": 1.1},
                ],
            },
            {"status": "promote", "requested_status": "promote", "effective_status": "promote"},
            {"status": "pass", "reasons": []},
            {
                "status": "pass",
                "evidence": {
                    "generated_at": "2026-03-19T00:00:00+00:00",
                    "runner_total_realized_pnl_usd": 5.0,
                    "runner_drawdown_to_pnl_ratio": 0.2,
                    "runner_reject_rate": 0.01,
                    "runner_avg_edge_retention_ratio": 0.8,
                    "runner_walk_forward_window_count": 3,
                    "runner_positive_walk_forward_ratio": 1.0,
                    "sample_quality_watchdog": {"status": "healthy"},
                    "checkpoint_auto_judge": {
                        "verdict": "hold",
                        "symbol_actions": [
                            {
                                "symbol": "BTCUSDT",
                                "lifecycle_action": "rollback",
                                "reason_codes": ["SYMBOL_SUPPORT_NEGATIVE"],
                            }
                        ],
                    },
                    "symbol_summary": [
                        {
                            "symbol": "BTCUSDT",
                            "trade_count": 3,
                            "required_trade_count_for_validation": 3,
                            "recommendation": "prune",
                        }
                    ],
                    "symbol_scorecard": [
                        {"symbol": "BTCUSDT", "recommendation": "demote"},
                    ],
                    "pruning_recommendations": [
                        {"symbol": "BTCUSDT", "recommendation": "prune"},
                    ],
                },
            },
        )

        self.assertEqual(state["active_policy"]["status"], "demote")
        self.assertEqual(state["active_policy"]["adjustments"][0]["action"], "demote")
        self.assertEqual(state["symbol_lifecycle"][0]["recommended_action"], "rollback")


if __name__ == "__main__":
    unittest.main()
