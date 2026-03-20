from __future__ import annotations

import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zlib
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.leet_official_textify import (
    HwpBinDataRef,
    HwpPictureAsset,
    build_hwp_picture_ocr_lines_by_bindata_id,
    collect_supported_official_sources,
    decompress_hwp_embedded_data,
    derive_official_output_path,
    export_hwp,
    export_pdf,
    extract_hwp_bindata_refs,
    extract_hwp_lines_from_xml,
    extract_hwp_paragraph_lines,
    extract_text_lines,
    format_hwp_picture_ocr_lines,
    format_exam_lines,
    is_supported_official_source,
)


class LeetOfficialTextifyTests(unittest.TestCase):
    def test_extract_text_lines_uses_layout_gap_spacing_recovery(self) -> None:
        class FakeCrop:
            def __init__(self) -> None:
                self.calls: list[dict[str, int]] = []

            def extract_text_lines(self, **kwargs: int) -> list[dict[str, object]]:
                self.calls.append(kwargs)
                return [
                    {
                        "text": "기간을 사병과 동일한 수준으로 단축하는 내용의 ｢병역법｣ 개정안이",
                        "top": 100.0,
                    },
                    {
                        "text": "국방의 의무를 수행하는 성격과 헌법상 직업의 자유를 실현하는",
                        "top": 112.0,
                    },
                ]

        class FakePage:
            def __init__(self, crop: FakeCrop) -> None:
                self.crop = crop

            def within_bbox(self, _bbox: tuple[float, float, float, float]) -> FakeCrop:
                return self.crop

        crop = FakeCrop()
        lines = extract_text_lines(FakePage(crop), (0.0, 0.0, 100.0, 100.0))

        self.assertEqual(
            crop.calls,
            [{"x_tolerance": 2, "y_tolerance": 3}],
        )
        self.assertEqual(
            lines,
            [
                "기간을 사병과 동일한 수준으로 단축하는 내용의 ｢병역법｣ 개정안이",
                "국방의 의무를 수행하는 성격과 헌법상 직업의 자유를 실현하는",
            ],
        )

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

    def test_keeps_recovered_question_header_spacing_without_regressing_structure(self) -> None:
        lines = [
            "3. 다음으로부터 추론한 것으로 옳은 것만을 <보기>에서 있는 대로 고른",
            "것은?",
            "<보기>",
            "ㄱ. 첫 번째 진술",
            "ㄴ. 두 번째 진술",
            "① ㄱ ② ㄴ ③ ㄱ, ㄴ",
            "갑: 첫 번째 발화",
            "을: 두 번째 발화",
        ]

        formatted = format_exam_lines(lines)

        self.assertIn(
            "3. 다음으로부터 추론한 것으로 옳은 것만을 <보기>에서 있는 대로 고른 것은?",
            formatted,
        )
        self.assertIn("\n<보기>\nㄱ. 첫 번째 진술\nㄴ. 두 번째 진술\n", formatted)
        self.assertIn("\n① ㄱ\n② ㄴ\n③ ㄱ, ㄴ\n", formatted)
        self.assertIn("갑: 첫 번째 발화\n을: 두 번째 발화", formatted)

    def test_preserves_blank_question_boundaries_for_unnumbered_hwp_stems(self) -> None:
        lines = [
            "⑤ 애당초 정의(正義)를 의식적으로 부정할 목적으로 제정된 법은",
            "법으로서의 효력을 갖지 않는다는 것은 을의 논지를 강화하고",
            "병의 논지를 약화한다.",
            "",
            "다음 견해를 분석한 것으로 옳은 것을 <보기>에서 고른 것은?",
            "",
            "<표>",
            "",
            "갑：인간은 야수로부터 자신을 보호하기 위하여 사회를 구성하",
            "게 되었다.",
        ]

        formatted = format_exam_lines(lines)

        self.assertIn(
            "⑤ 애당초 정의(正義)를 의식적으로 부정할 목적으로 제정된 법은\n"
            "법으로서의 효력을 갖지 않는다는 것은 을의 논지를 강화하고 병의 논지를 약화한다.\n\n"
            "다음 견해를 분석한 것으로 옳은 것을 <보기>에서 고른 것은?\n",
            formatted,
        )
        self.assertIn("\n<표>\n", formatted)
        self.assertIn(
            "갑：인간은 야수로부터 자신을 보호하기 위하여 사회를 구성하 게 되었다.\n",
            formatted,
        )
        self.assertNotIn(
            "병의 논지를 약화한다. 다음 견해를 분석한 것으로 옳은 것을 <보기>에서 고른 것은?",
            formatted,
        )

    def test_compacts_blank_separated_symbolic_choice_fragments(self) -> None:
        lines = [
            "다음 논증의 구조를 가장 잘 표현한 것은?",
            "①",
            "",
            "ⓐ+ⓑ+ⓒ+ⓓ",
            "",
            "↓",
            "",
            "ⓔ",
            "",
            "↓",
            "",
            "ⓕ+ⓖ+ⓗ",
            "",
            "↓",
            "",
            "ⓘ",
            "",
            "②",
            "",
            "ⓐ+ⓑ",
            "",
            "↓",
            "",
            "ⓒ",
        ]

        formatted = format_exam_lines(lines)

        self.assertIn("① ⓐ+ⓑ+ⓒ+ⓓ ↓ ⓔ ↓ ⓕ+ⓖ+ⓗ ↓ ⓘ", formatted)
        self.assertIn("② ⓐ+ⓑ ↓ ⓒ", formatted)

    def test_compacts_blank_separated_table_fragments_into_readable_lines(self) -> None:
        lines = [
            "평가 결과표",
            "영역",
            "",
            "사원",
            "",
            "업무 능력",
            "",
            "리더십",
            "",
            "인화력",
            "",
            "A",
            "",
            "B",
            "",
            "C",
            "",
            "◦ 각자의 총점은 0이다.",
        ]

        formatted = format_exam_lines(lines)

        self.assertIn("영역 사원 업무 능력 리더십 인화력 A B C", formatted)
        self.assertIn("\n◦ 각자의 총점은 0이다.\n", formatted)

    def test_maps_supported_official_pdf_into_textified_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            vault_root = Path(tempdir)
            source_path = (
                vault_root
                / "02. Resources/LEET/00. Official_Past_Exams/2025학년도 추리논증 문제 및 정답/2025_LEET_추리논증(홀수형).pdf"
            )
            expected_output = (
                vault_root
                / "02. Resources/LEET/01. Official_Textified/2025학년도 추리논증 문제 및 정답/2025_LEET_추리논증(홀수형).md"
            )
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text("placeholder", encoding="utf-8")

            self.assertTrue(is_supported_official_source(source_path, vault_root))
            self.assertEqual(derive_official_output_path(source_path, vault_root), expected_output)

    def test_maps_supported_official_hwp_into_textified_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            vault_root = Path(tempdir)
            source_path = (
                vault_root
                / "02. Resources/LEET/00. Official_Past_Exams/2010학년도 추리논증 문제 및 정답/2010_LEET_추리논증(홀수형).hwp"
            )
            expected_output = (
                vault_root
                / "02. Resources/LEET/01. Official_Textified/2010학년도 추리논증 문제 및 정답/2010_LEET_추리논증(홀수형).md"
            )
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text("placeholder", encoding="utf-8")

            self.assertTrue(is_supported_official_source(source_path, vault_root))
            self.assertEqual(derive_official_output_path(source_path, vault_root), expected_output)

    def test_collects_supported_official_pdf_and_hwp_from_batch_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            vault_root = Path(tempdir)
            official_root = vault_root / "02. Resources/LEET/00. Official_Past_Exams"
            good_pdf = official_root / "2026학년도 언어이해 문제 및 정답/2026_LEET_언어이해(홀수형).pdf"
            good_hwp = official_root / "2020학년도 언어이해 문제 및 정답/2020_LEET_언어이해(홀수형).hwp"
            outside_pdf = vault_root / "misc/sample.pdf"
            for path in (good_pdf, good_hwp, outside_pdf):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("placeholder", encoding="utf-8")

            collected = collect_supported_official_sources([official_root, outside_pdf], vault_root)

            self.assertEqual(collected, [good_hwp, good_pdf])

    def test_export_pdf_writes_once_and_skips_identical_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            vault_root = Path(tempdir)
            source_path = (
                vault_root
                / "02. Resources/LEET/00. Official_Past_Exams/2025학년도 추리논증 문제 및 정답/2025_LEET_추리논증(홀수형).pdf"
            )
            output_path = (
                vault_root
                / "02. Resources/LEET/01. Official_Textified/2025학년도 추리논증 문제 및 정답/2025_LEET_추리논증(홀수형).md"
            )
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text("placeholder", encoding="utf-8")

            with mock.patch(
                "scripts.leet_official_textify.format_pdf_text",
                return_value="1. 테스트 문항\n\n① 정답\n",
            ):
                first = export_pdf(source_path, vault_root, output_path)
                second = export_pdf(source_path, vault_root, output_path)

            self.assertTrue(first.changed)
            self.assertFalse(second.changed)
            self.assertIn("# 2025_LEET_추리논증(홀수형)", output_path.read_text(encoding="utf-8"))

    def test_extract_hwp_paragraph_lines_preserves_placeholders_and_spacing(self) -> None:
        paragraph = ET.fromstring(
            """
            <Paragraph>
              <LineSeg>
                <Text>1. 다음 설명으로 옳은 것은?</Text>
                <ControlChar name="PARAGRAPH_BREAK" />
              </LineSeg>
              <LineSeg>
                <GShapeObjectControl />
              </LineSeg>
              <LineSeg>
                <Text>①</Text>
                <ControlChar name="NONBREAK_SPACE" />
                <Text>첫 번째 선택지</Text>
              </LineSeg>
              <LineSeg>
                <TableControl />
              </LineSeg>
            </Paragraph>
            """
        )

        self.assertEqual(
            extract_hwp_paragraph_lines(paragraph),
            [
                "1. 다음 설명으로 옳은 것은?",
                "<그림>",
                "① 첫 번째 선택지",
                "<표>",
            ],
        )

    def test_extract_hwp_paragraph_lines_skips_textful_table_placeholder(self) -> None:
        paragraph = ET.fromstring(
            """
            <Paragraph>
              <LineSeg>
                <TableControl>
                  <TableBody>
                    <TableRow>
                      <TableCell>
                        <Paragraph>
                          <LineSeg>
                            <Text>표 안 텍스트</Text>
                          </LineSeg>
                        </Paragraph>
                      </TableCell>
                    </TableRow>
                  </TableBody>
                </TableControl>
              </LineSeg>
            </Paragraph>
            """
        )

        self.assertEqual(extract_hwp_paragraph_lines(paragraph), [])

    def test_extract_hwp_paragraph_lines_skips_textbox_gshape_placeholder(self) -> None:
        paragraph = ET.fromstring(
            """
            <Paragraph>
              <LineSeg>
                <GShapeObjectControl>
                  <ShapeComponent chid="$rec" />
                  <TextboxParagraphList>
                    <Paragraph>
                      <LineSeg>
                        <Text>홀수형</Text>
                      </LineSeg>
                    </Paragraph>
                  </TextboxParagraphList>
                </GShapeObjectControl>
              </LineSeg>
            </Paragraph>
            """
        )

        self.assertEqual(extract_hwp_paragraph_lines(paragraph), [])

    def test_extract_hwp_paragraph_lines_skips_line_only_gshape_placeholder(self) -> None:
        paragraph = ET.fromstring(
            """
            <Paragraph>
              <LineSeg>
                <GShapeObjectControl>
                  <ShapeComponent chid="$lin" />
                </GShapeObjectControl>
              </LineSeg>
            </Paragraph>
            """
        )

        self.assertEqual(extract_hwp_paragraph_lines(paragraph), [])

    def test_extract_hwp_paragraph_lines_keeps_picture_gshape_placeholder(self) -> None:
        paragraph = ET.fromstring(
            """
            <Paragraph>
              <LineSeg>
                <GShapeObjectControl>
                  <ShapeComponent chid="$pic" />
                </GShapeObjectControl>
              </LineSeg>
            </Paragraph>
            """
        )

        self.assertEqual(extract_hwp_paragraph_lines(paragraph), ["<그림>"])

    def test_extract_hwp_paragraph_lines_appends_picture_ocr_lines_for_matching_bindata(self) -> None:
        paragraph = ET.fromstring(
            """
            <Paragraph>
              <LineSeg>
                <GShapeObjectControl>
                  <ShapeComponent chid="$pic" />
                  <ShapePicture>
                    <PictureInfo bindata-id="7" />
                  </ShapePicture>
                </GShapeObjectControl>
              </LineSeg>
            </Paragraph>
            """
        )

        self.assertEqual(
            extract_hwp_paragraph_lines(
                paragraph,
                picture_ocr_by_bindata_id={7: ["◦ OCR: 개혁의 이득", "◦ OCR: 신규 시장 부문 행위자"]},
            ),
            ["<그림>", "◦ OCR: 개혁의 이득", "◦ OCR: 신규 시장 부문 행위자"],
        )

    def test_extract_hwp_bindata_refs_uses_docinfo_order_as_bindata_id(self) -> None:
        root = ET.fromstring(
            """
            <HwpDoc>
              <DocInfo>
                <BinData>
                  <BinDataEmbedding storage-id="BIN0001" ext="jpg" />
                </BinData>
                <BinData>
                  <BinDataEmbedding storage-id="BIN0002" ext="png" />
                </BinData>
              </DocInfo>
            </HwpDoc>
            """
        )

        self.assertEqual(
            extract_hwp_bindata_refs(root),
            {
                1: HwpBinDataRef(bindata_id=1, storage_id="BIN0001", ext="jpg"),
                2: HwpBinDataRef(bindata_id=2, storage_id="BIN0002", ext="png"),
            },
        )

    def test_decompress_hwp_embedded_data_handles_raw_deflate_payload(self) -> None:
        payload = b"\xff\xd8fake-jpeg"
        compressed = zlib.compressobj(wbits=-15)
        encoded = compressed.compress(payload) + compressed.flush()

        self.assertEqual(decompress_hwp_embedded_data(encoded), payload)
        self.assertEqual(decompress_hwp_embedded_data(payload), payload)

    def test_format_hwp_picture_ocr_lines_rejects_short_label_only_text(self) -> None:
        self.assertEqual(format_hwp_picture_ocr_lines("A\nB\nC"), [])

    def test_format_hwp_picture_ocr_lines_drops_mixed_noise_and_keeps_useful_labels(self) -> None:
        self.assertEqual(
            format_hwp_picture_ocr_lines(
                "A Baa 구간 BoB 구간 C\n출발선 신발 교체\n갑(구두) 운동화\n을(등산화)\n병(운동화)\n"
            ),
            [
                "◦ OCR: 출발선 신발 교체",
                "◦ OCR: 갑(구두) 운동화",
                "◦ OCR: 을(등산화)",
                "◦ OCR: 병(운동화)",
            ],
        )

    def test_format_hwp_picture_ocr_lines_rejects_block_when_only_short_noise_survives(self) -> None:
        self.assertEqual(
            format_hwp_picture_ocr_lines("~\naN,\nFASS SE\n4222\n체내\n"),
            [],
        )

    def test_format_hwp_picture_ocr_lines_rejects_hybrid_latin_noise_lines(self) -> None:
        self.assertEqual(
            format_hwp_picture_ocr_lines(
                "개혁의 이득] 곡선\n"
                "시작점 RAE <_RL TR, 개혁의 진행 정도\n"
                "3ㆍ신규 시장 부문 행위자\n"
                "ci All 부문 (국영)노동자들\n"
            ),
            [
                "◦ OCR: 개혁의 이득] 곡선",
                "◦ OCR: 3ㆍ신규 시장 부문 행위자",
            ],
        )

    def test_build_hwp_picture_ocr_lines_by_bindata_id_formats_tesseract_output(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            xml_path = Path(tempdir) / "sample.xml"
            xml_path.write_text(
                """
                <HwpDoc>
                  <DocInfo>
                    <BinData>
                      <BinDataEmbedding storage-id="BIN0001" ext="jpg" />
                    </BinData>
                  </DocInfo>
                </HwpDoc>
                """,
                encoding="utf-8",
            )

            with mock.patch(
                "scripts.leet_official_textify.available_hwp_picture_ocr_backend",
                return_value="tesseract",
            ), mock.patch(
                "scripts.leet_official_textify.extract_hwp_picture_assets",
                return_value={
                    1: HwpPictureAsset(
                        bindata_id=1,
                        storage_id="BIN0001",
                        ext="jpg",
                        data=b"jpeg-bytes",
                    )
                },
            ), mock.patch(
                "scripts.leet_official_textify.run_tesseract_ocr",
                return_value="개혁의 이득\n신규 시장 부문 행위자\n",
            ):
                self.assertEqual(
                    build_hwp_picture_ocr_lines_by_bindata_id(Path("sample.hwp"), xml_path),
                    {
                        1: [
                            "◦ OCR: 개혁의 이득",
                            "◦ OCR: 신규 시장 부문 행위자",
                        ]
                    },
                )

    def test_extract_hwp_lines_from_xml_recovers_nested_table_text_without_placeholder(self) -> None:
        xml = """
        <HwpDoc>
          <BodyText>
            <Paragraph>
              <LineSeg>
                <Text>문항 앞 설명</Text>
              </LineSeg>
            </Paragraph>
            <Paragraph>
              <LineSeg>
                <TableControl>
                  <TableBody>
                    <TableRow>
                      <TableCell>
                        <Paragraph>
                          <LineSeg>
                            <Text>&lt;보기&gt;</Text>
                          </LineSeg>
                        </Paragraph>
                        <Paragraph>
                          <LineSeg>
                            <Text>ㄱ. 표 안 텍스트</Text>
                          </LineSeg>
                        </Paragraph>
                      </TableCell>
                    </TableRow>
                  </TableBody>
                </TableControl>
              </LineSeg>
            </Paragraph>
          </BodyText>
        </HwpDoc>
        """

        with tempfile.TemporaryDirectory() as tempdir:
            xml_path = Path(tempdir) / "sample.xml"
            xml_path.write_text(xml, encoding="utf-8")

            self.assertEqual(
                extract_hwp_lines_from_xml(xml_path),
                ["문항 앞 설명", "", "<보기>", "", "ㄱ. 표 안 텍스트", ""],
            )

    def test_export_hwp_writes_once_and_skips_identical_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            vault_root = Path(tempdir)
            source_path = (
                vault_root
                / "02. Resources/LEET/00. Official_Past_Exams/2010학년도 언어이해 문제 및 정답/2010_LEET_언어이해(홀수형).hwp"
            )
            output_path = (
                vault_root
                / "02. Resources/LEET/01. Official_Textified/2010학년도 언어이해 문제 및 정답/2010_LEET_언어이해(홀수형).md"
            )
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_text("placeholder", encoding="utf-8")

            with mock.patch(
                "scripts.leet_official_textify.format_hwp_text",
                return_value="1. 테스트 문항\n\n① 정답\n",
            ):
                first = export_hwp(source_path, vault_root, output_path)
                second = export_hwp(source_path, vault_root, output_path)

            self.assertTrue(first.changed)
            self.assertFalse(second.changed)
            self.assertIn("# 2010_LEET_언어이해(홀수형)", output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
