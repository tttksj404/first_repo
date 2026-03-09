from __future__ import annotations

import unittest

from quant_binance.telegram_intent import parse_telegram_intent


class QuantGeminiBridgeTests(unittest.TestCase):
    def test_gemini_explicit_command_parses(self) -> None:
        intent = parse_telegram_intent("제미나이 전략 검토")
        self.assertEqual(intent.kind, "gemini")
        self.assertEqual(intent.value, "strategy-review")


if __name__ == "__main__":
    unittest.main()
