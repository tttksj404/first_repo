#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Iterable, Sequence

import pdfplumber

DEFAULT_VAULT_ROOT = Path("/Users/tttksj/Library/Mobile Documents/iCloud~md~obsidian/Documents/note")
QUESTION_RE = re.compile(r"^\d+\.\s")
RANGE_RE = re.compile(r"^\[\d+(?:~\d+)?\]\s")
CHOICE_RE = re.compile(r"^[①-⑤]\s")
BOGI_ITEM_RE = re.compile(r"^[ㄱ-ㅎ]\.\s")
DIALOGUE_RE = re.compile(r"^(?:갑|을|병|정|무|A|B|C|D|甲|乙|丙|丁)\s*:")
LABEL_RE = re.compile(r"^<(?:보기|견해|규칙|사례|실험|표|그림|조건)>$")
NOISE_LINE_RE = re.compile(
    r"^(?:\d+|제\s+\d\s+교시|성명(?:\s+수.*)?|수험번호|홀\s*수형|짝\s*수형|언어이해|추리논증|호)$"
)


@dataclass(frozen=True)
class TextLine:
    text: str
    top: float


def normalize_line_text(text: str) -> str:
    normalized = " ".join(text.split())
    normalized = normalized.replace("＜", "<").replace("＞", ">")
    normalized = normalized.replace("<보 기>", "<보기>")
    normalized = normalized.replace("＜보기＞", "<보기>")
    normalized = normalized.replace("＜견해＞", "<견해>")
    normalized = normalized.replace("＜규칙＞", "<규칙>")
    normalized = normalized.replace("＜사례＞", "<사례>")
    normalized = re.sub(r"\s+([,.;:?!%])", r"\1", normalized)
    normalized = re.sub(r"([(<\[]) ", r"\1", normalized)
    normalized = re.sub(r" ([>\])])", r"\1", normalized)
    normalized = re.sub(r"(?<!\d)(\d+)\.(?=\S)", r"\1. ", normalized)
    normalized = re.sub(r"([①-⑤])(?=\S)", r"\1 ", normalized)
    normalized = re.sub(r"([ㄱ-ㅎ])\.(?=\S)", r"\1. ", normalized)
    normalized = re.sub(r"^(홀수형|짝수형)\s+\d+$", "", normalized)
    normalized = re.sub(r"^\d+\s+(언어이해|추리논증)\s+(홀수형|짝수형)$", "", normalized)
    return normalized.strip()


def split_inline_choices(text: str) -> list[str]:
    if len(re.findall(r"[①-⑤]", text)) < 2:
        return [text]
    parts = re.findall(r"[①-⑤]\s*.*?(?=(?:\s*[①-⑤])|$)", text)
    cleaned = [part.strip() for part in parts if part.strip()]
    return cleaned or [text]


def split_inline_bogi_items(text: str) -> list[str]:
    if len(re.findall(r"[ㄱ-ㅎ]\.", text)) < 2:
        return [text]
    parts = re.findall(r"[ㄱ-ㅎ]\.\s*.*?(?=(?:\s*[ㄱ-ㅎ]\.)|$)", text)
    cleaned = [part.strip() for part in parts if part.strip()]
    return cleaned or [text]


def split_inline_bullets(text: str) -> list[str]:
    if text.count("◦") < 2:
        return [text]
    parts = [part.strip() for part in re.split(r"(?=◦)", text) if part.strip()]
    return parts or [text]


def expand_structured_line(text: str) -> list[str]:
    expanded = [normalize_line_text(text)]
    for splitter in (split_inline_bullets, split_inline_choices, split_inline_bogi_items):
        next_lines: list[str] = []
        for line in expanded:
            next_lines.extend(splitter(line))
        expanded = next_lines
    return [line for line in expanded if line]


def line_kind(text: str) -> str:
    if not text:
        return "blank"
    if RANGE_RE.match(text):
        return "range"
    if QUESTION_RE.match(text):
        return "question"
    if text == "<보기>":
        return "bogi_label"
    if CHOICE_RE.match(text):
        return "choice"
    if BOGI_ITEM_RE.match(text):
        return "bogi_item"
    if LABEL_RE.match(text):
        return "label"
    if text.startswith("◦"):
        return "bullet"
    if DIALOGUE_RE.match(text):
        return "dialogue"
    return "paragraph"


def infer_gap_threshold(lines: Sequence[TextLine]) -> float:
    if len(lines) < 2:
        return 24.0
    gaps = [
        second.top - first.top
        for first, second in zip(lines, lines[1:])
        if 4.0 <= second.top - first.top <= 40.0
    ]
    if not gaps:
        return 24.0
    return max(median(gaps) * 1.4, 21.0)


def extract_text_lines(page: pdfplumber.page.Page, bbox: tuple[float, float, float, float]) -> list[str]:
    raw_lines = page.within_bbox(bbox).extract_text_lines()
    filtered: list[TextLine] = []
    for raw_line in raw_lines:
        normalized = normalize_line_text(raw_line["text"])
        if not normalized or NOISE_LINE_RE.match(normalized):
            continue
        filtered.append(TextLine(text=normalized, top=raw_line["top"]))

    if not filtered:
        return []

    threshold = infer_gap_threshold(filtered)
    output: list[str] = []
    for index, line in enumerate(filtered):
        output.append(line.text)
        if index == len(filtered) - 1:
            continue
        if filtered[index + 1].top - line.top > threshold:
            output.append("")
    return output


def detect_multi_column(page: pdfplumber.page.Page, body_top: float, body_bottom: float, margin_x: float) -> bool:
    midpoint = page.width / 2
    body_words = page.within_bbox((margin_x, body_top, page.width - margin_x, body_bottom)).extract_words(
        x_tolerance=1,
        y_tolerance=3,
        keep_blank_chars=False,
    )
    left = [word for word in body_words if word["x0"] < midpoint - 24]
    right = [word for word in body_words if word["x1"] > midpoint + 24]
    if len(left) < 40 or len(right) < 40:
        return False
    left_tops = {round(word["top"] / 8) for word in left}
    right_tops = {round(word["top"] / 8) for word in right}
    return len(left_tops & right_tops) >= 6


def extract_page_lines(page: pdfplumber.page.Page) -> list[str]:
    body_top = max(145.0, page.height * 0.12)
    body_bottom = page.height - max(105.0, page.height * 0.08)
    margin_x = max(72.0, page.width * 0.08)
    gutter = max(8.0, page.width * 0.01)

    if detect_multi_column(page, body_top, body_bottom, margin_x):
        midpoint = page.width / 2
        left_bbox = (margin_x, body_top, midpoint - gutter, body_bottom)
        right_bbox = (midpoint + gutter, body_top, page.width - margin_x, body_bottom)
        return extract_text_lines(page, left_bbox) + extract_text_lines(page, right_bbox)

    full_bbox = (margin_x, body_top, page.width - margin_x, body_bottom)
    return extract_text_lines(page, full_bbox)


def ensure_blank_line(output: list[str]) -> None:
    if output and output[-1] != "":
        output.append("")


def flush_paragraph(paragraph: list[str], output: list[str]) -> None:
    if not paragraph:
        return
    output.append(" ".join(paragraph).strip())
    paragraph.clear()


def merge_wrapped_question_headers(lines: Sequence[str]) -> list[str]:
    merged: list[str] = []
    index = 0
    while index < len(lines):
        current = normalize_line_text(lines[index])
        if line_kind(current) not in {"question", "range"}:
            merged.append(current)
            index += 1
            continue

        parts = [current]
        index += 1
        while index < len(lines):
            candidate = normalize_line_text(lines[index])
            if not candidate:
                break
            candidate_kind = line_kind(candidate)
            if candidate_kind != "paragraph" or len(candidate) > 28:
                break
            parts.append(candidate)
            index += 1
            if re.search(r"[?!.]$", candidate):
                break
        merged.append(" ".join(parts))
    return merged


def format_exam_lines(lines: Iterable[str]) -> str:
    prepared_lines = merge_wrapped_question_headers([line for line in lines if normalize_line_text(line)])
    expanded_lines: list[str] = []
    for line in prepared_lines:
        expanded_lines.extend(expand_structured_line(line))
    output: list[str] = []
    paragraph: list[str] = []

    for raw_line in expanded_lines:
        text = normalize_line_text(raw_line)
        kind = line_kind(text)

        if kind == "blank":
            flush_paragraph(paragraph, output)
            ensure_blank_line(output)
            continue

        if kind in {"range", "question"}:
            flush_paragraph(paragraph, output)
            ensure_blank_line(output)
            output.append(text)
            ensure_blank_line(output)
            continue

        if kind == "label":
            flush_paragraph(paragraph, output)
            ensure_blank_line(output)
            output.append(text)
            continue

        if kind == "bogi_label":
            flush_paragraph(paragraph, output)
            ensure_blank_line(output)
            output.append(text)
            continue

        if kind in {"bogi_item", "choice", "dialogue", "bullet"}:
            flush_paragraph(paragraph, output)
            output.append(text)
            continue

        paragraph.append(text)

    flush_paragraph(paragraph, output)

    cleaned: list[str] = []
    for line in output:
        if line == "" and (not cleaned or cleaned[-1] == ""):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip() + "\n"


def format_pdf_text(pdf_path: Path) -> str:
    page_lines: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_lines.extend(extract_page_lines(page))
            page_lines.append("")
    return format_exam_lines(page_lines)


def build_source_link(source_path: Path, vault_root: Path) -> str:
    try:
        rel = source_path.relative_to(vault_root)
        rel_posix = rel.as_posix()
        return f"[[{rel_posix}|{source_path.name}]]"
    except ValueError:
        return source_path.as_posix()


def build_markdown(pdf_path: Path, body_text: str, vault_root: Path) -> str:
    return (
        f"# {pdf_path.stem}\n\n"
        f"- 원본 파일: {build_source_link(pdf_path, vault_root)}\n"
        f"- 형식: {pdf_path.suffix.lstrip('.')}\n\n"
        "## 추출 텍스트\n\n"
        f"{body_text}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Format LEET official PDFs into exam-like markdown."
    )
    parser.add_argument("input", type=Path, help="Source PDF path")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Markdown output path; prints to stdout when omitted",
    )
    parser.add_argument(
        "--vault-root",
        type=Path,
        default=DEFAULT_VAULT_ROOT,
        help="Vault root used to build Obsidian source links",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.input.suffix.lower() != ".pdf":
        raise SystemExit("Only PDF inputs are supported by this formatter.")

    body_text = format_pdf_text(args.input)
    markdown = build_markdown(args.input, body_text, args.vault_root)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
        print(args.output)
        return

    print(markdown, end="")


if __name__ == "__main__":
    main()
