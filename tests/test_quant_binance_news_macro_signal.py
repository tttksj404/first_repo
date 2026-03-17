from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from quant_binance.news_macro_signal import NewsHeadline, build_signal, decide_refresh, write_news_macro_signal


class QuantBinanceNewsMacroSignalTests(unittest.TestCase):
    def test_decide_refresh_bootstrap_and_high_impact_event(self) -> None:
        now = datetime(2026, 3, 17, 8, 55, tzinfo=UTC)
        headlines = (
            NewsHeadline(
                title="Breaking CPI surprise sparks volatility",
                published_at=now.isoformat(),
                source="Example",
                query_label="macro",
                categories=("macro",),
                bearish_score=0.7,
                uncertainty_score=0.5,
            ),
        )
        decision = decide_refresh(now=now, existing_payload=None, official_events=(), headlines=headlines)
        self.assertTrue(decision.should_refresh)
        self.assertEqual(decision.reason, "bootstrap")

        existing = {"refreshed_at": "2026-03-17T06:00:00+00:00", "last_schedule_label": "2026-03-17-am", "headline_hash": "old"}
        event_payload = ({"name": "FOMC", "start": "2026-03-17T10:00:00+00:00", "impact": "high"},)
        decision = decide_refresh(now=now, existing_payload=existing, official_events=event_payload, headlines=headlines)
        self.assertTrue(decision.should_refresh)
        self.assertIn("HIGH_IMPACT_EVENT:FOMC", decision.trigger_reasons)

    def test_build_signal_maps_news_to_restraint(self) -> None:
        now = datetime(2026, 3, 17, 6, 30, tzinfo=UTC)
        headlines = (
            NewsHeadline(
                title="War risk and hot CPI shake crypto market",
                published_at=now.isoformat(),
                source="Example",
                query_label="macro",
                categories=("macro", "geopolitics"),
                bearish_score=1.6,
                uncertainty_score=0.5,
            ),
            NewsHeadline(
                title="ETF inflow remains solid",
                published_at=now.isoformat(),
                source="Example",
                query_label="etf_flow",
                categories=("etf_flow",),
                bullish_score=1.2,
            ),
        )
        signal = build_signal(
            now=now,
            refresh_reason="scheduled_window",
            trigger_reasons=("SCHEDULED_WINDOW",),
            next_scheduled_refresh_at=now,
            headlines=headlines,
            official_events=({"name": "CPI", "start": "2026-03-17T07:45:00+00:00", "impact": "high"},),
        )
        self.assertIn(signal.entry_policy_bias, {"pre_event_reduce", "halt_high_impact_window", "risk_off_reduce"})
        self.assertGreater(signal.macro_inputs["news_uncertainty_score"], 0.0)
        self.assertIn(signal.majors_bias, {"majors_only", "neutral"})

    def test_write_news_macro_signal_outputs_artifacts(self) -> None:
        now = datetime(2026, 3, 17, 6, 30, tzinfo=UTC)
        rss = '''<?xml version="1.0" encoding="UTF-8"?><rss><channel>
        <item><title>Bitcoin ETF inflow grows</title><link>https://example.com/a</link><pubDate>Tue, 17 Mar 2026 06:00:00 GMT</pubDate><source>Example</source></item>
        <item><title>Breaking war risk lifts oil volatility</title><link>https://example.com/b</link><pubDate>Tue, 17 Mar 2026 05:30:00 GMT</pubDate><source>Example</source></item>
        </channel></rss>'''

        def fake_fetcher(url: str) -> str:
            return rss

        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            official_events = base / "official_macro_events.json"
            official_events.write_text(json.dumps({"events": [{"name": "FOMC", "start": "2026-03-17T07:30:00+00:00", "impact": "high"}]}), encoding="utf-8")
            output_path, macro_inputs_path, status = write_news_macro_signal(
                output_path=base / "news_macro_signal.json",
                macro_inputs_output_path=base / "news_macro_inputs.json",
                official_events_path=official_events,
                fetcher=fake_fetcher,
                now=now,
            )
            self.assertEqual(status, "refreshed")
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            macro_payload = json.loads(macro_inputs_path.read_text(encoding="utf-8"))
            self.assertIn(payload["refresh_reason"], {"bootstrap", "scheduled_window", "high_impact_event"})
            self.assertIn("event_risk_score", macro_payload)
            self.assertIn("news_bearish_score", macro_payload)


if __name__ == "__main__":
    unittest.main()
