from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant_binance.observability.overview import build_runtime_overview, write_runtime_overview


class QuantBinanceOverviewTests(unittest.TestCase):
    def test_build_runtime_overview_keeps_only_core_fields(self) -> None:
        overview = build_runtime_overview(
            summary={
                "live_order_count": 2,
                "tested_order_count": 1,
                "realized_pnl_usd_estimate": 1.5,
                "unrealized_pnl_usd_estimate": -0.2,
                "top_rejection_reasons": {"EDGE_TOO_THIN": 3},
                "recent_decisions": [{"symbol": "BTCUSDT", "mode": "futures"}],
                "exchange_live_futures_position_count": 1,
                "exchange_live_futures_positions": [
                    {"symbol": "BTCUSDT", "holdSide": "long", "total": "0.01", "marginSize": "10", "unrealizedPL": "1.0"}
                ],
                "capital_report": {"futures_available_balance_usd": 50.0},
            },
            state={
                "updated_at": "2026-03-14T00:00:00+00:00",
                "decision_count": 5,
                "heartbeat_count": 100,
                "last_event_timestamp": "2026-03-14T00:00:01+00:00",
                "last_decision_timestamp": "2026-03-14T00:00:00+00:00",
                "last_decision_emitted_at": "2026-03-14T00:00:02+00:00",
                "self_healing": {"status": "healthy"},
                "kill_switch": {"armed": False, "reasons": []},
            },
        )
        self.assertEqual(overview["status"], "healthy")
        self.assertEqual(overview["decision_count"], 5)
        self.assertEqual(overview["live_order_count"], 2)
        self.assertEqual(len(overview["exchange_live_futures_positions"]), 1)

    def test_write_runtime_overview_writes_latest_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            run_dir = Path(tempdir) / "output" / "paper-live-shell" / "20260314-000000"
            run_dir.mkdir(parents=True, exist_ok=True)
            target = run_dir / "overview.json"
            write_runtime_overview(target, {"status": "healthy"})
            self.assertTrue(target.exists())
            latest = run_dir.parent / "latest" / "overview.json"
            self.assertTrue(latest.exists())
            self.assertEqual(json.loads(latest.read_text(encoding="utf-8"))["status"], "healthy")


if __name__ == "__main__":
    unittest.main()
