from __future__ import annotations

import unittest

from quant_binance.telegram_intent import help_message_ko, parse_telegram_intent


class QuantBinanceTelegramIntentTests(unittest.TestCase):
    def test_local_korean_natural_language(self) -> None:
        intent = parse_telegram_intent("지금 상태 알려줘")
        self.assertEqual(intent.kind, "local")
        self.assertEqual(intent.value, "status")

    def test_local_startlive_phrase(self) -> None:
        intent = parse_telegram_intent("실주문 시작해")
        self.assertEqual(intent.kind, "local")
        self.assertEqual(intent.value, "start-live")

    def test_codex_korean_phrase(self) -> None:
        intent = parse_telegram_intent("전략 검토해줘")
        self.assertEqual(intent.kind, "codex")
        self.assertEqual(intent.value, "strategy-review")

    def test_help_message_contains_korean(self) -> None:
        message = help_message_ko()
        self.assertIn("지금 상태 알려줘", message)
        self.assertIn("전략 검토해줘", message)

    def test_weekly_report_phrase(self) -> None:
        intent = parse_telegram_intent("주간 검증 리포트")
        self.assertEqual(intent.kind, "local")
        self.assertEqual(intent.value, "weekly-validation-report")

    def test_execution_report_phrase(self) -> None:
        intent = parse_telegram_intent("실행 품질 리포트")
        self.assertEqual(intent.kind, "local")
        self.assertEqual(intent.value, "execution-quality-report")

    def test_advisor_report_phrase(self) -> None:
        intent = parse_telegram_intent("거시 전략 리포트")
        self.assertEqual(intent.kind, "local")
        self.assertEqual(intent.value, "advisor-report")


if __name__ == "__main__":
    unittest.main()
