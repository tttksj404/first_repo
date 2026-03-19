from __future__ import annotations

import unittest

from quant_binance.auto_mode import build_regime_aware_auto_mode


class QuantBinanceAutoModeTests(unittest.TestCase):
    def test_build_regime_aware_auto_mode_prefers_preferred_policy_bucket_execution_quality(self) -> None:
        auto_mode = build_regime_aware_auto_mode(
            regime_summary=[
                {
                    "mode": "futures",
                    "decision_count": 6,
                    "avg_score": 63.0,
                    "avg_net_edge_bps": 10.0,
                }
            ],
            sample_quality_watchdog={"status": "promote_ready"},
            checkpoint_auto_judge={"verdict": "expand"},
            baseline_control_comparison={"verdict": "supportive", "expansion_gate": "pass"},
            execution_quality={
                "runner_total_realized_pnl_usd": 12.0,
                "runner_drawdown_to_pnl_ratio": 0.1,
                "runner_reject_rate": 0.0,
                "runner_protection_degraded_rate": 0.0,
                "runner_avg_edge_retention_ratio": 0.9,
                "runner_avg_realized_edge_bps": 8.0,
                "runner_walk_forward_window_count": 3,
                "runner_positive_walk_forward_ratio": 1.0,
                "total_closed_trade_count": 6,
                "total_live_order_count": 8,
                "micro_live_gate": {"available": True, "status": "pass"},
                "policy_context_bucket_evidence": {
                    "staged_candidate": {
                        "runner_total_realized_pnl_usd": -2.0,
                        "runner_drawdown_to_pnl_ratio": 1.1,
                        "runner_reject_rate": 0.2,
                        "runner_protection_degraded_rate": 0.12,
                        "runner_avg_edge_retention_ratio": 0.4,
                        "runner_avg_realized_edge_bps": -1.0,
                        "runner_walk_forward_window_count": 2,
                        "runner_positive_walk_forward_ratio": 0.0,
                        "total_closed_trade_count": 2,
                        "total_live_order_count": 6,
                        "micro_live_gate": {"available": True, "status": "pending"},
                    }
                },
                "preferred_policy_bucket": "staged_candidate",
            },
            symbol_lifecycle_summary={"actionable_symbol_count": 0},
            symbol_lifecycle=[],
        )

        self.assertEqual(auto_mode["mode"], "tighter")
        self.assertTrue(auto_mode["expansion_blocked"])
        self.assertIn("AUTO_MODE_TIGHTENED_BY_EXECUTION_QUALITY", auto_mode["reason_codes"])
        self.assertEqual(auto_mode["inputs"]["execution_quality"]["policy_bucket"], "staged_candidate")
        self.assertEqual(auto_mode["inputs"]["execution_quality"]["source"], "policy_bucket")

    def test_build_regime_aware_auto_mode_requires_simple_baseline_gate_pass_before_supporting_expansion(self) -> None:
        auto_mode = build_regime_aware_auto_mode(
            regime_summary=[
                {
                    "mode": "futures",
                    "decision_count": 6,
                    "avg_score": 68.0,
                    "avg_net_edge_bps": 12.0,
                }
            ],
            sample_quality_watchdog={"status": "promote_ready"},
            checkpoint_auto_judge={"verdict": "expand"},
            baseline_control_comparison={"verdict": "supportive", "expansion_gate": "not_available"},
            execution_quality={
                "runner_total_realized_pnl_usd": 12.0,
                "runner_drawdown_to_pnl_ratio": 0.1,
                "runner_reject_rate": 0.0,
                "runner_protection_degraded_rate": 0.0,
                "runner_avg_edge_retention_ratio": 0.9,
                "runner_avg_realized_edge_bps": 8.0,
                "runner_walk_forward_window_count": 3,
                "runner_positive_walk_forward_ratio": 1.0,
                "total_closed_trade_count": 6,
                "total_live_order_count": 8,
                "micro_live_gate": {"available": True, "status": "pass"},
            },
            symbol_lifecycle_summary={"actionable_symbol_count": 0},
            symbol_lifecycle=[],
        )

        self.assertNotIn("AUTO_MODE_SIMPLE_BASELINE_SUPPORTIVE", auto_mode["reason_codes"])
        self.assertNotEqual(auto_mode["mode"], "cautiously_expanded")


if __name__ == "__main__":
    unittest.main()
