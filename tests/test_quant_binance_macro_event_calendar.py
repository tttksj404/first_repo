from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant_binance.macro_event_calendar import (
    fetch_bea_macro_events,
    fetch_bls_macro_events,
    fetch_fomc_events,
    write_official_macro_events,
)


FOMC_HTML = """
<html><body>
For 2026:
Tuesday, January 27, and Wednesday, January 28
Tuesday, March 17, and Wednesday, March 18
The Committee releases a policy statement after each meeting.
</body></html>
"""

BLS_CPI_HTML = """
<html><body>
<div>Next Release</div>
<div>Consumer Price Index data are scheduled to be released on April 10, 2026, at 8:30 A.M.</div>
</body></html>
"""

BLS_PPI_HTML = """
<html><body>
<div>Next Release</div>
<div>Producer Price Index data are scheduled to be released on April 11, 2026, at 8:30 A.M.</div>
</body></html>
"""

BLS_EMP_HTML = """
<html><body>
<div>Next Release</div>
<div>The Employment Situation is scheduled to be released on April 3, 2026, at 8:30 A.M.</div>
</body></html>
"""

BEA_HTML = """
<html><body>
Gross Domestic Product
April 30
8:30 AM
Personal Income and Outlays
May 1
10:00 AM
</body></html>
"""


class QuantBinanceMacroEventCalendarTests(unittest.TestCase):
    def test_fetch_fomc_events_parses_official_schedule(self) -> None:
        events = fetch_fomc_events(fetcher=lambda url: FOMC_HTML)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].name, "FOMC")
        self.assertEqual(events[0].impact, "high")

    def test_fetch_bls_macro_events_parses_cpi_ppi_and_jobs(self) -> None:
        def fetcher(url: str) -> str:
            if "cpi" in url:
                return BLS_CPI_HTML
            if "ppi" in url:
                return BLS_PPI_HTML
            return BLS_EMP_HTML

        events = fetch_bls_macro_events(fetcher=fetcher)
        self.assertEqual(len(events), 3)
        names = [event.name for event in events]
        self.assertIn("미국 CPI", names)
        self.assertIn("미국 PPI", names)
        self.assertIn("미국 고용지표", names)

    def test_fetch_bea_macro_events_parses_gdp_and_pce(self) -> None:
        events = fetch_bea_macro_events(fetcher=lambda url: BEA_HTML)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].name, "미국 GDP")
        self.assertEqual(events[1].name, "미국 개인소득/소비(PCE)")

    def test_write_official_macro_events_writes_json(self) -> None:
        def fetcher(url: str) -> str:
            if "federalreserve" in url:
                return FOMC_HTML
            if "bea.gov" in url:
                return BEA_HTML
            if "cpi" in url:
                return BLS_CPI_HTML
            if "ppi" in url:
                return BLS_PPI_HTML
            return BLS_EMP_HTML

        with tempfile.TemporaryDirectory() as tempdir:
            path = write_official_macro_events(
                output_path=Path(tempdir) / "official_macro_events.json",
                fetcher=fetcher,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("generated_at", payload)
            self.assertGreaterEqual(len(payload.get("events", [])), 5)


if __name__ == "__main__":
    unittest.main()
