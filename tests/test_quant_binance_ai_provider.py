from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quant_binance.ai_provider import build_provider_command, normalize_provider, provider_choices


class QuantBinanceAiProviderTests(unittest.TestCase):
    def test_normalize_provider_aliases(self) -> None:
        self.assertEqual(normalize_provider("openai"), "codex")
        self.assertEqual(normalize_provider("google"), "gemini")
        self.assertEqual(normalize_provider("anthropic"), "claude")

    def test_provider_choices_include_claude(self) -> None:
        self.assertIn("claude", provider_choices())

    def test_build_codex_command_includes_model_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            output_path = Path(tempdir) / "out.txt"
            cmd = build_provider_command(
                provider="codex",
                prompt="hello",
                workspace_root=tempdir,
                model="gpt-5.4",
                output_path=output_path,
            )
        self.assertIn("--model", cmd)
        self.assertIn("gpt-5.4", cmd)
        self.assertIn(str(output_path.resolve()), cmd)

    def test_build_claude_command_uses_print_mode(self) -> None:
        cmd = build_provider_command(
            provider="claude",
            prompt="hello",
            workspace_root=".",
            model="opus",
        )
        self.assertIn("--print", cmd)
        self.assertIn("--output-format", cmd)
        self.assertIn("text", cmd)
        self.assertIn("--model", cmd)
        self.assertIn("opus", cmd)


if __name__ == "__main__":
    unittest.main()
