from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_leet_textify_regressions import scan_paths


class CheckLeetTextifyRegressionsTests(unittest.TestCase):
    def test_detects_known_noise_and_stack_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            sample = Path(tempdir) / "suspect.md"
            sample.write_text(
                "A Baa 구간 BoB 구간 C\n"
                "업무\n\n능력\n\n리더십\n\n인화력\n\nA\n\nB\n\nC\n"
                "확인하십\n시오\n",
                encoding="utf-8",
            )

            result = scan_paths([sample])
            rules = {finding.rule for finding in result.findings}

            self.assertIn("ocr-noise-token", rules)
            self.assertIn("long-vertical-stack", rules)
            self.assertIn("broken-eojeol", rules)
            self.assertIn("singleton-stack-token", rules)

    def test_passes_clean_markdown_without_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            sample = Path(tempdir) / "clean.md"
            sample.write_text(
                "1. 다음 설명으로 옳은 것은?\n\n"
                "① 첫 번째 진술\n"
                "② 두 번째 진술\n\n"
                "영역 사원 업무 능력 리더십 인화력 A B C\n",
                encoding="utf-8",
            )

            result = scan_paths([sample])

            self.assertEqual(result.files_scanned, 1)
            self.assertEqual(result.findings, [])


if __name__ == "__main__":
    unittest.main()
