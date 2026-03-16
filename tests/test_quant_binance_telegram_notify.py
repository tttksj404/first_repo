from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quant_binance import telegram_notify


class _FakeResponse:
    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return b'{"ok": true, "result": {"message_id": 1}}'


class QuantBinanceTelegramNotifyTests(unittest.TestCase):
    def test_resolve_telegram_chat_ids_falls_back_to_openclaw_allowfrom(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            allow_path = Path(tempdir) / "telegram-default-allowFrom.json"
            allow_path.write_text(
                json.dumps({"version": 1, "allowFrom": ["6768216338"]}),
                encoding="utf-8",
            )
            with patch.object(telegram_notify, "ENV_FILES", []), patch.object(
                telegram_notify, "OPENCLAW_ALLOWLIST_FILES", [allow_path]
            ), patch.dict("os.environ", {}, clear=True):
                self.assertEqual(telegram_notify.resolve_telegram_chat_ids(), ["6768216338"])

    def test_send_telegram_message_uses_fallback_chat_id(self) -> None:
        calls: list[object] = []

        def _fake_urlopen(req, timeout=0, context=None):  # type: ignore[no-untyped-def]
            calls.append(req)
            return _FakeResponse()

        with tempfile.TemporaryDirectory() as tempdir:
            allow_path = Path(tempdir) / "telegram-default-allowFrom.json"
            allow_path.write_text(
                json.dumps({"version": 1, "allowFrom": ["6768216338"]}),
                encoding="utf-8",
            )
            with patch.object(telegram_notify, "ENV_FILES", []), patch.object(
                telegram_notify, "OPENCLAW_ALLOWLIST_FILES", [allow_path]
            ), patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "token-1"}, clear=True), patch(
                "quant_binance.telegram_notify.urlopen",
                side_effect=_fake_urlopen,
            ):
                result = telegram_notify.send_telegram_message("runtime test")

        self.assertTrue(result["sent"])
        self.assertEqual(result["chat_ids"], ["6768216338"])
        self.assertEqual(len(calls), 1)

    def test_telegram_report_only_enabled_reads_env_flag(self) -> None:
        with patch.object(telegram_notify, "ENV_FILES", []), patch.dict(
            "os.environ",
            {"TELEGRAM_REPORT_ONLY": "1"},
            clear=True,
        ):
            self.assertTrue(telegram_notify.telegram_report_only_enabled())


if __name__ == "__main__":
    unittest.main()
