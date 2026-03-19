from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.leet_official_textify import format_exam_lines


class LeetOfficialTextifyTests(unittest.TestCase):
    def test_restores_question_bogi_and_choices(self) -> None:
        lines = [
            "1. 다음 논쟁에 대한 분석으로 옳은 것만을 <보 기>에서 있는 대로 고른",
            "것은?",
            "의무복무제를 운영하는 X국의 ｢병역법｣은 병역의무를 이행해야",
            "하는 자의 의무복무기간을 사병은 3년, 부사관은 7년, 장교는 10년",
            "으로 정하고 있다.",
            "",
            "<보 기>",
            "ㄱ. 정보기술의 발달로 군의 자동화 및 첨단화가 빠르게 진행되어 갑의 견해는 약화된다. ㄴ. X국의 ｢병역법｣에 따르면 을의 의견해를 강화한다. ㄷ. 헌법재판소가 합헌이라고 판단하였다면 갑의 견해는 강화되고 을의 견해는 약화된다.",
            "① ㄱ ② ㄴ ③ ㄱ, ㄷ ④ ㄴ, ㄷ ⑤ ㄱ, ㄴ, ㄷ",
        ]

        formatted = format_exam_lines(lines)

        self.assertIn(
            "1. 다음 논쟁에 대한 분석으로 옳은 것만을 <보기>에서 있는 대로 고른 것은?",
            formatted,
        )
        self.assertIn(
            "\n<보기>\nㄱ. 정보기술의 발달로 군의 자동화 및 첨단화가 빠르게 진행되어 갑의 견해는 약화된다.\nㄴ. X국의 ｢병역법｣에 따르면 을의 의견해를 강화한다.\nㄷ. 헌법재판소가 합헌이라고 판단하였다면 갑의 견해는 강화되고 을의 견해는 약화된다.\n",
            formatted,
        )
        self.assertIn(
            "\n① ㄱ\n② ㄴ\n③ ㄱ, ㄷ\n④ ㄴ, ㄷ\n⑤ ㄱ, ㄴ, ㄷ\n",
            formatted,
        )

    def test_keeps_dialogue_and_blank_boundaries(self) -> None:
        lines = [
            "2. <견해>에 대한 분석으로 옳은 것만을 <보기>에서 있는 대로 고른 것은?",
            "<견해>",
            "갑: 나는 개정안에 반대해.",
            "을: 나는 생각이 달라.",
            "",
            "부모는 미성년 자녀의 교육 과정에 참여할 권리가 있으므로",
            "학교가 학생에게 불리한 조치를 할 경우 이에 대한 의견을 제시할 권리도 갖는다.",
        ]

        formatted = format_exam_lines(lines)

        self.assertIn("2. <견해>에 대한 분석으로 옳은 것만을 <보기>에서 있는 대로 고른 것은?", formatted)
        self.assertIn("<견해>\n갑: 나는 개정안에 반대해.\n을: 나는 생각이 달라.", formatted)
        self.assertIn(
            "부모는 미성년 자녀의 교육 과정에 참여할 권리가 있으므로 학교가 학생에게 불리한 조치를 할 경우 이에 대한 의견을 제시할 권리도 갖는다.",
            formatted,
        )


if __name__ == "__main__":
    unittest.main()
