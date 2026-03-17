from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quant_binance import telegram_notify


class TelegramNotifyTests(unittest.TestCase):
    def test_prepare_outbound_text_suppresses_exact_duplicate_within_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "telegram_notify_state.json"
            with patch.object(telegram_notify, "_dedup_window_seconds", return_value=180), patch.object(
                telegram_notify, "_burst_window_seconds", return_value=45
            ), patch.object(telegram_notify, "_burst_threshold", return_value=3):
                first_text, first_meta = telegram_notify._prepare_outbound_text(
                    "same message", now_ts=1000.0, state_path=state_path
                )
                second_text, second_meta = telegram_notify._prepare_outbound_text(
                    "same message", now_ts=1010.0, state_path=state_path
                )

        self.assertEqual(first_text, "same message")
        self.assertTrue(first_meta["sent"])
        self.assertIsNone(second_text)
        self.assertEqual(second_meta["reason"], "dedup_suppressed")

    def test_prepare_outbound_text_compacts_burst_into_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "telegram_notify_state.json"
            with patch.object(telegram_notify, "_dedup_window_seconds", return_value=180), patch.object(
                telegram_notify, "_burst_window_seconds", return_value=45
            ), patch.object(telegram_notify, "_burst_threshold", return_value=3):
                telegram_notify._prepare_outbound_text("first update", now_ts=1000.0, state_path=state_path)
                telegram_notify._prepare_outbound_text("second update", now_ts=1005.0, state_path=state_path)
                third_text, third_meta = telegram_notify._prepare_outbound_text(
                    "third update", now_ts=1010.0, state_path=state_path
                )

        self.assertIsNotNone(third_text)
        assert third_text is not None
        self.assertIn("[AUTO_SUMMARY]", third_text)
        self.assertIn("first update", third_text)
        self.assertIn("second update", third_text)
        self.assertIn("third update", third_text)
        self.assertTrue(third_meta["sent"])

    def test_send_telegram_message_returns_suppressed_metadata_without_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "telegram_notify_state.json"
            deliveries: list[str] = []

            def fake_deliver(*, token: str, chat_ids: list[str], text: str) -> dict[str, object]:
                deliveries.append(text)
                return {"sent": True, "chat_ids": chat_ids, "responses": []}

            with patch.object(telegram_notify, "TELEGRAM_NOTIFY_STATE_PATH", state_path), patch.object(
                telegram_notify, "load_env_value", side_effect=lambda name: "token" if name == "TELEGRAM_BOT_TOKEN" else "123"
            ), patch.object(telegram_notify, "resolve_telegram_chat_ids", return_value=["123"]), patch.object(
                telegram_notify, "_deliver_message", side_effect=fake_deliver
            ), patch.object(telegram_notify, "time") as mocked_time:
                mocked_time.time.side_effect = [1000.0, 1010.0]
                first = telegram_notify.send_telegram_message("same message")
                second = telegram_notify.send_telegram_message("same message")

        self.assertTrue(first["sent"])
        self.assertEqual(len(deliveries), 1)
        self.assertFalse(second["sent"])
        self.assertEqual(second["reason"], "dedup_suppressed")


if __name__ == "__main__":
    unittest.main()
