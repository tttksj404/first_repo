from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quant_binance.strategy_advisor import (
    build_strategy_advisor_context,
    build_strategy_advisor_prompt,
    load_macro_event_windows,
    summarize_strategy_advisor_report,
    write_strategy_advisor_context,
)


ROOT = Path(__file__).resolve().parents[1]
MACRO_EVENTS_SAMPLE = ROOT / "quant_binance" / "examples" / "macro_strategy_events.sample.json"


class QuantBinanceStrategyAdvisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_macro_events_path = os.environ.get("MACRO_STRATEGY_EVENTS_PATH")
        os.environ.pop("MACRO_STRATEGY_EVENTS_PATH", None)

    def tearDown(self) -> None:
        if self.old_macro_events_path is not None:
            os.environ["MACRO_STRATEGY_EVENTS_PATH"] = self.old_macro_events_path
        else:
            os.environ.pop("MACRO_STRATEGY_EVENTS_PATH", None)

    def test_load_macro_event_windows_from_path(self) -> None:
        os.environ["MACRO_STRATEGY_EVENTS_PATH"] = str(MACRO_EVENTS_SAMPLE)
        events = load_macro_event_windows()
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0].name, "FOMC")
        self.assertEqual(events[0].impact, "high")

    def test_build_strategy_advisor_context_collects_runtime_and_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            latest = base / "output" / "paper-live-shell" / "latest"
            logs = latest / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            (latest / "summary.json").write_text(
                json.dumps(
                    {
                        "decision_count": 5,
                        "live_order_count": 1,
                        "tested_order_count": 2,
                        "recent_decisions": [{"symbol": "BTCUSDT"}],
                    }
                ),
                encoding="utf-8",
            )
            (latest / "summary.state.json").write_text(
                json.dumps({"decision_count": 5, "last_decision_timestamp": "2026-03-15T02:00:00Z"}),
                encoding="utf-8",
            )
            (latest / "overview.json").write_text(
                json.dumps({"updated_at": "2026-03-15T02:10:00Z", "status": "healthy"}),
                encoding="utf-8",
            )
            (logs / "decisions.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-03-15T02:00:00Z",
                        "symbol": "BTCUSDT",
                        "final_mode": "futures",
                        "predictability_score": 70.0,
                        "net_expected_edge_bps": 10.0,
                        "estimated_round_trip_cost_bps": 5.0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (logs / "live_orders.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT", "accepted": True, "order_id": "oid-1"}) + "\n",
                encoding="utf-8",
            )
            (logs / "closed_trades.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 12.5, "realized_return_bps_estimate": 35.0})
                + "\n",
                encoding="utf-8",
            )
            (base / "artifacts").mkdir(parents=True, exist_ok=True)
            (base / "artifacts" / "strategy_override.approved.json").write_text(
                json.dumps({"universe": ["BTCUSDT", "ETHUSDT"]}),
                encoding="utf-8",
            )
            os.environ["MACRO_STRATEGY_EVENTS_PATH"] = str(MACRO_EVENTS_SAMPLE)
            with patch("quant_binance.strategy_advisor.fetch_official_macro_events", return_value=()):
                context = build_strategy_advisor_context(base_dir=base, lookback_days=7)

            self.assertEqual(context.summary["decision_count"], 5)
            self.assertEqual(context.performance_report["closed_trade_count"], 1)
            self.assertGreaterEqual(len(context.macro_event_windows), 1)

    def test_build_strategy_advisor_prompt_mentions_required_sections(self) -> None:
        prompt = build_strategy_advisor_prompt(context_path=ROOT / "quant_runtime" / "artifacts" / "strategy_advisor.context.json")
        self.assertIn("현재 시장 요약", prompt)
        self.assertIn("주요 거시 이벤트와 영향 기간", prompt)
        self.assertIn("다음 개선 후보 3개", prompt)

    def test_write_strategy_advisor_context_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime"
            latest = base / "output" / "paper-live-shell" / "latest"
            logs = latest / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            (latest / "summary.json").write_text(json.dumps({}), encoding="utf-8")
            (latest / "summary.state.json").write_text(json.dumps({}), encoding="utf-8")
            (latest / "overview.json").write_text(json.dumps({}), encoding="utf-8")
            with patch("quant_binance.strategy_advisor.fetch_official_macro_events", return_value=()):
                context = build_strategy_advisor_context(base_dir=base)
            paths = write_strategy_advisor_context(context=context, base_dir=base)
            self.assertTrue(paths["context"].exists())
            payload = json.loads(paths["context"].read_text(encoding="utf-8"))
            self.assertIn("generated_at", payload)

    def test_summarize_strategy_advisor_report_truncates_cleanly(self) -> None:
        text = "\n".join(f"line {idx}" for idx in range(100))
        summary = summarize_strategy_advisor_report(text, max_chars=50)
        self.assertLessEqual(len(summary), 50)
        self.assertTrue(summary.startswith("line 0"))


if __name__ == "__main__":
    unittest.main()
