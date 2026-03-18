from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quant_binance import telegram_notify


class TelegramNotifyTests(unittest.TestCase):
    def test_prepare_outbound_text_disables_auto_summary_when_flag_off(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "telegram_notify_state.json"
            with patch.object(telegram_notify, "load_env_value") as mock_load_env:
                def _fake(name: str) -> str:
                    if name == "TELEGRAM_NOTIFY_AUTO_SUMMARY":
                        return "0"
                    if name == "TELEGRAM_NOTIFY_BURST_THRESHOLD":
                        return "3"
                    if name == "TELEGRAM_NOTIFY_BURST_WINDOW_SECONDS":
                        return "45"
                    if name == "TELEGRAM_NOTIFY_DEDUP_WINDOW_SECONDS":
                        return "180"
                    return ""

                mock_load_env.side_effect = _fake
                first, _ = telegram_notify._prepare_outbound_text("alpha", now_ts=100.0, state_path=state_path)
                second, _ = telegram_notify._prepare_outbound_text("beta", now_ts=110.0, state_path=state_path)
                third, meta = telegram_notify._prepare_outbound_text("gamma", now_ts=120.0, state_path=state_path)

            self.assertEqual(first, "alpha")
            self.assertEqual(second, "beta")
            self.assertEqual(third, "gamma")
            self.assertEqual(meta["burst_count"], 3)
            self.assertFalse(third.startswith("[AUTO_SUMMARY]"))


if __name__ == "__main__":
    unittest.main()
