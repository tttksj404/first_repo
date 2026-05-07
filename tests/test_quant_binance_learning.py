from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from quant_binance.learning import OnlineEdgeLearner
from quant_binance.models import DecisionIntent
from quant_binance.observability.log_store import JsonlLogStore


ROOT = Path(__file__).resolve().parents[1]


def make_decision(decision_id: str, symbol: str, mode: str, net_edge_bps: float) -> DecisionIntent:
    return DecisionIntent(
        decision_id=decision_id,
        decision_hash=f"hash-{decision_id}",
        snapshot_id=f"snap-{decision_id}",
        config_version="2026-03-08.v1",
        timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
        symbol=symbol,
        candidate_mode=mode,
        final_mode=mode,
        side="long",
        trend_direction=1,
        trend_strength=0.8,
        volume_confirmation=0.7,
        liquidity_score=0.75,
        volatility_penalty=0.25,
        overheat_penalty=0.1,
        predictability_score=82.0,
        gross_expected_edge_bps=24.0,
        net_expected_edge_bps=net_edge_bps,
        estimated_round_trip_cost_bps=10.0,
        order_intent_notional_usd=2000.0,
        stop_distance_bps=45.0,
    )


class QuantBinanceLearningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / "tests" / "tmp_learning"
        self.edge_path = self.root / "edge_table.json"
        self.store = JsonlLogStore(self.root / "logs")

    def tearDown(self) -> None:
        if self.root.exists():
            for path in sorted(self.root.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                else:
                    path.rmdir()

    def test_jsonl_log_store_appends_and_reads(self) -> None:
        self.store.append("decisions", {"decision_id": "d1", "value": 1})
        self.store.append("decisions", {"decision_id": "d2", "value": 2})
        rows = self.store.read("decisions")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["decision_id"], "d1")

    def test_online_edge_learner_exports_table(self) -> None:
        learner = OnlineEdgeLearner(min_observations=1)
        decisions = (
            make_decision("d1", "BTCUSDT", "futures", 14.0),
            make_decision("d2", "BTCUSDT", "futures", 12.0),
            make_decision("d3", "ETHUSDT", "spot", 10.0),
        )
        count = learner.ingest_decisions(decisions)
        self.assertEqual(count, 3)
        update = learner.export(self.edge_path)
        self.assertEqual(update.observation_count, 3)
        payload = json.loads(self.edge_path.read_text(encoding="utf-8"))
        self.assertIn("BTCUSDT", payload["symbols"])
        btc_rows = payload["symbols"]["BTCUSDT"]
        self.assertEqual(btc_rows[0]["median_bps"], 24.0)


if __name__ == "__main__":
    unittest.main()
