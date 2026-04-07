from __future__ import annotations

import unittest

from quant_binance.runtime_universe import build_runtime_universe_hydration


class QuantBinanceRuntimeUniverseTests(unittest.TestCase):
    def test_build_runtime_universe_hydration_uses_aligned_bucket_evidence(self) -> None:
        hydration = build_runtime_universe_hydration(
            policy_state={
                "active_policy": {"status": "baseline", "adjustments": []},
                "policy_evidence_buckets": {
                    "active_policy": {
                        "available": True,
                        "alignment": {"aligned": True, "status": "aligned"},
                        "evidence": {
                            "policy_context_bucket_symbol_summary": [
                                {"symbol": "SOLUSDT", "recommendation": "observe_only", "trade_count": 3}
                            ]
                        },
                    }
                },
            },
            configured_symbols=("BTCUSDT", "SOLUSDT"),
            major_symbols=("BTCUSDT", "ETHUSDT"),
        )

        sol_row = hydration["rows_by_symbol"]["SOLUSDT"]
        self.assertEqual(hydration["bucket_name"], "active_policy")
        self.assertTrue(sol_row["observe_only"])
        self.assertFalse(sol_row["allow_bootstrap"])
        self.assertTrue(sol_row["exclude_from_top_k"])
        self.assertIn("POLICY_BUCKET_OBSERVE_ONLY", sol_row["reason_codes"])

    def test_build_runtime_universe_hydration_ignores_misaligned_bucket_evidence(self) -> None:
        hydration = build_runtime_universe_hydration(
            policy_state={
                "active_policy": {"status": "baseline", "adjustments": []},
                "policy_evidence_buckets": {
                    "active_policy": {
                        "available": True,
                        "alignment": {"aligned": False, "status": "misaligned"},
                        "evidence": {
                            "policy_context_bucket_symbol_summary": [
                                {"symbol": "SOLUSDT", "recommendation": "observe_only", "trade_count": 3}
                            ]
                        },
                    }
                },
            },
            configured_symbols=("BTCUSDT", "SOLUSDT"),
            major_symbols=("BTCUSDT", "ETHUSDT"),
        )

        sol_row = hydration["rows_by_symbol"]["SOLUSDT"]
        self.assertEqual(hydration["bucket_name"], "")
        self.assertFalse(sol_row["observe_only"])
        self.assertTrue(sol_row["allow_bootstrap"])
        self.assertFalse(sol_row["bucket_evidence_available"])


if __name__ == "__main__":
    unittest.main()
