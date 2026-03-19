from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant_binance.promotion import build_strategy_proposal


class QuantBinancePromotionTests(unittest.TestCase):
    def test_build_strategy_proposal_includes_supporting_reports(self) -> None:
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
                json.dumps(
                    {
                        "pruning_recommendations": [
                            {"symbol": "XYZUSDT", "recommendation": "prune"},
                            {"symbol": "ABCUSDT", "recommendation": "keep"},
                        ]
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
            self.assertEqual(proposal["candidate_name"], "candidate-a")
            self.assertTrue(proposal["supporting_artifacts"]["performance_report"])
            self.assertTrue(proposal["supporting_artifacts"]["recent_comparison"])
            self.assertEqual(proposal["gates"]["simple_baseline_gate_status"], "not_available")
            self.assertEqual(proposal["gates"]["risky_symbols"], ["XYZUSDT"])
            self.assertEqual(proposal["gates"]["best_comparison_strategy"], "current_strategy")
            self.assertIn("universe", proposal["overrides"])
            self.assertNotIn("XYZUSDT", proposal["overrides"]["universe"])

    def test_build_strategy_proposal_includes_symbol_lifecycle_and_deprioritizes_held_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            (base / "artifacts" / "optimization").mkdir(parents=True, exist_ok=True)
            (base / "output" / "paper-live-shell" / "run-a").mkdir(parents=True, exist_ok=True)
            (base / "output" / "strategy-comparison-recent" / "run-b").mkdir(parents=True, exist_ok=True)

            (base / "artifacts" / "optimization" / "latest.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-19T00:00:00+00:00",
                        "best_candidate": {
                            "name": "candidate-b",
                            "objective_score": 9.5,
                            "overrides": {},
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
                        "checkpoint_auto_judge": {"verdict": "hold"},
                        "symbol_lifecycle": [
                            {
                                "symbol": "BTCUSDT",
                                "target_state": "observe_only",
                                "recommended_action": "hold",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (base / "output" / "strategy-comparison-recent" / "run-b" / "comparison.json").write_text(
                json.dumps({"strategies": [{"strategy_name": "current_strategy", "total_pnl_usd": 1.0}]}),
                encoding="utf-8",
            )

            proposal = build_strategy_proposal(base_dir=base)

            self.assertEqual(proposal["gates"]["lifecycle_blocked_symbols"], ["BTCUSDT"])
            self.assertEqual(proposal["symbol_lifecycle"][0]["symbol"], "BTCUSDT")
            self.assertIn("priority_symbols", proposal["overrides"]["futures_exposure"])
            self.assertNotIn("BTCUSDT", proposal["overrides"]["futures_exposure"]["priority_symbols"])

    def test_build_strategy_proposal_applies_auto_mode_runtime_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            (base / "artifacts" / "optimization").mkdir(parents=True, exist_ok=True)
            (base / "output" / "paper-live-shell" / "run-a").mkdir(parents=True, exist_ok=True)
            (base / "output" / "strategy-comparison-recent" / "run-b").mkdir(parents=True, exist_ok=True)

            (base / "artifacts" / "optimization" / "latest.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-19T00:00:00+00:00",
                        "best_candidate": {
                            "name": "candidate-c",
                            "objective_score": 7.5,
                            "overrides": {},
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
                        "checkpoint_auto_judge": {"verdict": "expand"},
                        "auto_mode": {
                            "mode": "cautiously_expanded",
                            "reason_codes": ["AUTO_MODE_EXECUTION_QUALITY_STRONG"],
                            "runtime_guidance": {
                                "mode_thresholds": {
                                    "futures_score_min_delta": -1.0,
                                    "spot_score_min_delta": -1.0,
                                },
                                "risk": {"per_trade_equity_risk_scale": 1.03},
                                "cash_reserve": {"when_futures_enabled_delta": -0.01},
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            (base / "output" / "strategy-comparison-recent" / "run-b" / "comparison.json").write_text(
                json.dumps({"strategies": [{"strategy_name": "current_strategy", "total_pnl_usd": 1.0}]}),
                encoding="utf-8",
            )

            proposal = build_strategy_proposal(base_dir=base)

            self.assertEqual(proposal["auto_mode"]["mode"], "cautiously_expanded")
            self.assertEqual(proposal["gates"]["auto_mode"], "cautiously_expanded")
            self.assertEqual(proposal["overrides"]["mode_thresholds"]["futures_score_min"], 41.0)
            self.assertEqual(proposal["overrides"]["mode_thresholds"]["spot_score_min"], 43.0)
            self.assertEqual(proposal["overrides"]["risk"]["per_trade_equity_risk"], 0.005665)
            self.assertEqual(proposal["overrides"]["cash_reserve"]["when_futures_enabled"], 0.07)

    def test_build_strategy_proposal_reprioritizes_existing_bucket_supported_symbols_only(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            (base / "artifacts" / "optimization").mkdir(parents=True, exist_ok=True)
            (base / "output" / "paper-live-shell" / "run-a").mkdir(parents=True, exist_ok=True)

            (base / "artifacts" / "optimization" / "latest.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-19T00:00:00+00:00",
                        "best_candidate": {
                            "name": "candidate-d",
                            "objective_score": 8.1,
                            "overrides": {},
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
                        "checkpoint_auto_judge": {"verdict": "hold"},
                        "symbol_lifecycle": [
                            {
                                "symbol": "SOLUSDT",
                                "recommended_action": "cautious_repromote",
                                "target_state": "cautious_repromotion",
                                "recommendation": "promote",
                                "symbol_evidence_source": "policy_context_bucket",
                                "policy_context_bucket_evidence_available": True,
                            },
                            {
                                "symbol": "XLMUSDT",
                                "recommended_action": "cautious_repromote",
                                "target_state": "cautious_repromotion",
                                "recommendation": "promote",
                                "symbol_evidence_source": "policy_context_bucket",
                                "policy_context_bucket_evidence_available": True,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            proposal = build_strategy_proposal(base_dir=base)

            futures_priority = proposal["overrides"]["futures_exposure"]["priority_symbols"]
            self.assertEqual(futures_priority[0], "BTCUSDT")
            self.assertLess(futures_priority.index("SOLUSDT"), futures_priority.index("DOGEUSDT"))
            self.assertNotIn("XLMUSDT", futures_priority)


if __name__ == "__main__":
    unittest.main()
