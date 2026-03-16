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

            self.assertEqual(proposal["status"], "proposal_ready")
            self.assertEqual(proposal["candidate_name"], "candidate-a")
            self.assertTrue(proposal["supporting_artifacts"]["performance_report"])
            self.assertTrue(proposal["supporting_artifacts"]["recent_comparison"])
            self.assertEqual(proposal["gates"]["risky_symbols"], ["XYZUSDT"])
            self.assertEqual(proposal["gates"]["best_comparison_strategy"], "current_strategy")
            self.assertIn("universe", proposal["overrides"])
            self.assertNotIn("XYZUSDT", proposal["overrides"]["universe"])


if __name__ == "__main__":
    unittest.main()
