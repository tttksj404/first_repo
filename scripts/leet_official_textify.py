#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zlib
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Iterable, Sequence

import pdfplumber

try:
    import olefile
except ImportError as exc:  # pragma: no cover - dependency presence varies by machine
    olefile = None
    OLEFILE_IMPORT_ERROR = exc
else:
    OLEFILE_IMPORT_ERROR = None

try:
    from hwp5.xmlmodel import Hwp5File
except ImportError as exc:  # pragma: no cover - dependency presence varies by machine
    Hwp5File = None
    HWP5_IMPORT_ERROR = exc
else:
    HWP5_IMPORT_ERROR = None

DEFAULT_VAULT_ROOT = Path("/Users/tttksj/Library/Mobile Documents/iCloud~md~obsidian/Documents/note")
OFFICIAL_PAST_EXAMS_REL = Path("02. Resources/LEET/00. Official_Past_Exams")
OFFICIAL_TEXTIFIED_REL = Path("02. Resources/LEET/01. Official_Textified")
SUPPORTED_SOURCE_SUFFIXES = {".pdf", ".hwp"}
QUESTION_RE = re.compile(r"^\d+\.\s")
RANGE_RE = re.compile(r"^\[\d+(?:~\d+)?\]\s")
CHOICE_RE = re.compile(r"^[①-⑤](?:\s|$)")
BOGI_ITEM_RE = re.compile(r"^[ㄱ-ㅎ]\.\s")
DIALOGUE_RE = re.compile(r"^(?:갑|을|병|정|무|A|B|C|D|甲|乙|丙|丁)\s*:")
LABEL_RE = re.compile(r"^<(?:보기|견해|규칙|사례|실험|표|그림|조건)>$")
TEXT_LINE_X_TOLERANCE = 2
TEXT_LINE_Y_TOLERANCE = 3
NOISE_LINE_RE = re.compile(
    r"^(?:\d+|제\s+\d\s+교시|성명(?:\s+수.*)?|수험번호|홀\s*수형|짝\s*수형|언어이해|추리논증|호)$"
)
SPACE_CONTROL_NAMES = {
    "FIXWIDTH_SPACE",
    "NONBREAK_SPACE",
    "HARD_SPACE",
    "TAB",
}
PLACEHOLDER_BY_TAG = {
    "TableControl": "<표>",
    "GShapeObjectControl": "<그림>",
}
PICTURE_OCR_MIN_VISIBLE_CHARS = 12
PICTURE_OCR_MAX_LINES = 8
PICTURE_OCR_PREFIX = "◦ OCR: "
PICTURE_OCR_MIN_ACCEPTED_LINES = 2
FRAGMENT_WRAP_WIDTH = 32
BARE_CHOICE_RE = re.compile(r"^[①-⑤]$")
OCR_EDGE_NOISE_RE = re.compile(r"^[~`'\".,;:]+|[~`'\".,;:]+$")
OCR_NOISE_GLYPH_RE = re.compile(r"[~_=|/\\<>`]")


@dataclass(frozen=True)
class TextLine:
    text: str
    top: float


@dataclass(frozen=True)
class GenerationResult:
    source_path: Path
    output_path: Path
    changed: bool


@dataclass(frozen=True)
class HwpBinDataRef:
    bindata_id: int
    storage_id: str
    ext: str


@dataclass(frozen=True)
class HwpPictureAsset:
    bindata_id: int
    storage_id: str
    ext: str
    data: bytes


def official_past_exams_root(vault_root: Path) -> Path:
    return vault_root / OFFICIAL_PAST_EXAMS_REL


def official_textified_root(vault_root: Path, override_root: Path | None = None) -> Path:
    return override_root or (vault_root / OFFICIAL_TEXTIFIED_REL)


def official_relative_source_path(source_path: Path, vault_root: Path) -> Path | None:
    try:
        relative_path = source_path.relative_to(official_past_exams_root(vault_root))
    except ValueError:
        return None
    if source_path.suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
        return None
    return relative_path


def is_supported_official_source(source_path: Path, vault_root: Path) -> bool:
    return official_relative_source_path(source_path, vault_root) is not None


def derive_official_output_path(
    source_path: Path,
    vault_root: Path,
    textified_root_override: Path | None = None,
) -> Path:
    relative_source_path = official_relative_source_path(source_path, vault_root)
    if relative_source_path is None:
        raise ValueError(f"Unsupported official source path: {source_path}")
    return official_textified_root(vault_root, textified_root_override) / relative_source_path.with_suffix(".md")


def collect_supported_official_sources(paths: Sequence[Path], vault_root: Path) -> list[Path]:
    collected: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        candidates = (
            sorted(candidate for candidate in path.rglob("*") if candidate.suffix.lower() in SUPPORTED_SOURCE_SUFFIXES)
            if path.is_dir()
            else [path]
        )
        for candidate in candidates:
            if not is_supported_official_source(candidate, vault_root):
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            collected.append(candidate)
    return collected


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
    raw_lines = page.within_bbox(bbox).extract_text_lines(
        x_tolerance=TEXT_LINE_X_TOLERANCE,
        y_tolerance=TEXT_LINE_Y_TOLERANCE,
    )
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
        if not current:
            if merged and merged[-1] != "":
                merged.append("")
            index += 1
            continue
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


def prepare_exam_lines(lines: Iterable[str]) -> list[str]:
    prepared: list[str] = []
    for raw_line in lines:
        normalized = normalize_line_text(raw_line)
        if normalized:
            prepared.append(normalized)
            continue
        if prepared and prepared[-1] != "":
            prepared.append("")
    return prepared


def visible_char_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def is_compactable_fragment_line(text: str) -> bool:
    if not text:
        return False

    kind = line_kind(text)
    if kind in {"blank", "question", "range", "bogi_label", "label", "dialogue", "bullet", "bogi_item"}:
        return False
    if kind == "choice":
        return BARE_CHOICE_RE.match(text) is not None

    visible_count = visible_char_count(text)
    if visible_count > 18 and not re.search(r"[↓ⓐ-ⓩA-Za-z0-9+\-=/()]", text):
        return False
    if visible_count > FRAGMENT_WRAP_WIDTH:
        return False
    if re.search(r"[?!.]$", text) and visible_count > 6:
        return False
    return True


def wrap_fragment_tokens(tokens: Sequence[str]) -> list[str]:
    wrapped: list[str] = []
    current = ""
    for token in tokens:
        if current and BARE_CHOICE_RE.match(token):
            wrapped.append(current)
            current = token
            continue
        candidate = token if not current else f"{current} {token}"
        if current and visible_char_count(candidate) > FRAGMENT_WRAP_WIDTH:
            wrapped.append(current)
            current = token
            continue
        current = candidate
    if current:
        wrapped.append(current)
    return wrapped


def compact_fragmented_output(lines: Sequence[str]) -> list[str]:
    compacted: list[str] = []
    index = 0
    while index < len(lines):
        current = lines[index]
        if current == "":
            compacted.append(current)
            index += 1
            continue

        if is_compactable_fragment_line(current):
            run = [current]
            next_index = index + 1
            while next_index + 1 < len(lines) and lines[next_index] == "" and is_compactable_fragment_line(lines[next_index + 1]):
                run.append(lines[next_index + 1])
                next_index += 2

            if len(run) >= 3 and (
                any(BARE_CHOICE_RE.match(token) for token in run)
                or sum(visible_char_count(token) <= 4 for token in run) >= 2
            ):
                compacted.extend(wrap_fragment_tokens(run))
                index = next_index
                continue

        compacted.append(current)
        index += 1
    return compacted


def format_exam_lines(lines: Iterable[str]) -> str:
    prepared_lines = merge_wrapped_question_headers(prepare_exam_lines(lines))
    expanded_lines: list[str] = []
    for line in prepared_lines:
        if not line:
            expanded_lines.append("")
            continue
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
    cleaned = compact_fragmented_output(cleaned)
    return "\n".join(cleaned).strip() + "\n"


def format_pdf_text(pdf_path: Path) -> str:
    page_lines: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_lines.extend(extract_page_lines(page))
            page_lines.append("")
    return format_exam_lines(page_lines)


def xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def normalize_hwp_line(line: str) -> str:
    normalized = normalize_line_text(line)
    if normalized == "<보 기>":
        return "<보기>"
    return normalized


def iter_hwp_control_text(control: ET.Element) -> Iterable[str]:
    for node in control.iter():
        if node is control:
            continue
        if xml_local_name(node.tag) != "Text":
            continue
        text = normalize_hwp_line(node.text or "")
        if text:
            yield text


def gshape_component_kind(control: ET.Element) -> str | None:
    for node in control.iter():
        if xml_local_name(node.tag) != "ShapeComponent":
            continue
        kind = node.attrib.get("chid")
        if kind:
            return kind
    return None


def hwp_control_placeholder(control: ET.Element) -> str | None:
    local_name = xml_local_name(control.tag)
    placeholder = PLACEHOLDER_BY_TAG.get(local_name)
    if placeholder is None:
        return None

    if local_name == "TableControl":
        return None if any(iter_hwp_control_text(control)) else placeholder

    if local_name == "GShapeObjectControl":
        kind = gshape_component_kind(control)
        if kind == "$lin":
            return None
        if kind != "$pic" and any(iter_hwp_control_text(control)):
            return None
        return placeholder

    return placeholder


def hwp_picture_bindata_id(control: ET.Element) -> int | None:
    for node in control.iter():
        if xml_local_name(node.tag) != "PictureInfo":
            continue
        bindata_id = node.attrib.get("bindata-id")
        if bindata_id is None:
            continue
        try:
            return int(bindata_id)
        except ValueError:
            return None
    return None


def extract_hwp_bindata_refs(root: ET.Element) -> dict[int, HwpBinDataRef]:
    refs: dict[int, HwpBinDataRef] = {}
    next_bindata_id = 1
    for node in root.iter():
        if xml_local_name(node.tag) != "BinData":
            continue
        embedding = next((child for child in node if xml_local_name(child.tag) == "BinDataEmbedding"), None)
        if embedding is None:
            next_bindata_id += 1
            continue
        storage_id = embedding.attrib.get("storage-id")
        if storage_id:
            refs[next_bindata_id] = HwpBinDataRef(
                bindata_id=next_bindata_id,
                storage_id=storage_id,
                ext=(embedding.attrib.get("ext") or "bin").lower(),
            )
        next_bindata_id += 1
    return refs


def decompress_hwp_embedded_data(data: bytes) -> bytes:
    try:
        return zlib.decompress(data, -15)
    except zlib.error:
        return data


def resolve_hwp_bindata_stream_name(
    ole: "olefile.OleFileIO",
    storage_id: str,
    ext: str,
) -> tuple[str, str] | None:
    candidates = [f"{storage_id}.{ext}", f"{storage_id}.{ext.lower()}", f"{storage_id}.{ext.upper()}", storage_id]
    for candidate in dict.fromkeys(candidates):
        if ole.exists(["BinData", candidate]):
            resolved_ext = Path(candidate).suffix.lstrip(".").lower() or ext
            return candidate, resolved_ext

    prefix = f"{storage_id}."
    for entry in ole.listdir():
        if len(entry) != 2 or entry[0] != "BinData":
            continue
        if not entry[1].startswith(prefix):
            continue
        resolved_ext = Path(entry[1]).suffix.lstrip(".").lower() or ext
        return entry[1], resolved_ext
    return None


def extract_hwp_picture_assets(
    hwp_path: Path,
    bindata_refs: dict[int, HwpBinDataRef],
) -> dict[int, HwpPictureAsset]:
    if olefile is None:
        return {}

    assets: dict[int, HwpPictureAsset] = {}
    with olefile.OleFileIO(str(hwp_path)) as ole:
        for bindata_id, ref in bindata_refs.items():
            resolved = resolve_hwp_bindata_stream_name(ole, ref.storage_id, ref.ext)
            if resolved is None:
                continue
            stream_name, resolved_ext = resolved
            raw_data = ole.openstream(["BinData", stream_name]).read()
            assets[bindata_id] = HwpPictureAsset(
                bindata_id=bindata_id,
                storage_id=ref.storage_id,
                ext=resolved_ext,
                data=decompress_hwp_embedded_data(raw_data),
            )
    return assets


def available_hwp_picture_ocr_backend() -> str | None:
    if shutil.which("tesseract"):
        return "tesseract"
    return None


def run_tesseract_ocr(image_path: Path) -> str | None:
    result = subprocess.run(
        [
            "tesseract",
            str(image_path),
            "stdout",
            "-l",
            "kor+eng",
            "--psm",
            "6",
            "quiet",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def is_useful_hwp_picture_ocr_line(line: str) -> bool:
    visible_text = re.sub(r"\s+", "", line)
    if len(visible_text) < 2:
        return False

    hangul_count = len(re.findall(r"[가-힣]", line))
    if hangul_count < 2:
        return False

    latin_count = len(re.findall(r"[A-Za-z]", line))
    latin_tokens = re.findall(r"[A-Za-z]{2,}", line)
    noise_count = len(OCR_NOISE_GLYPH_RE.findall(line))
    if re.search(r"[A-Za-z]{3,}", line) and hangul_count * 2 < latin_count:
        return False
    if latin_count >= 4 and hangul_count < latin_count:
        return False
    if len(latin_tokens) >= 2 and hangul_count < latin_count * 3:
        return False
    if latin_tokens and noise_count and hangul_count < 12:
        return False
    if noise_count >= 2 and hangul_count < 5:
        return False

    tokens = re.findall(r"[A-Za-z가-힣0-9]+", line)
    if tokens and len(tokens) == 1 and len(tokens[0]) < 3 and hangul_count < 3:
        return False
    return True


def format_hwp_picture_ocr_lines(text: str) -> list[str]:
    normalized_lines: list[str] = []
    for raw_line in text.splitlines():
        normalized = OCR_EDGE_NOISE_RE.sub("", normalize_hwp_line(raw_line)).strip()
        if not normalized:
            continue
        if normalized_lines and normalized_lines[-1] == normalized:
            continue
        normalized_lines.append(normalized)

    if not normalized_lines:
        return []

    visible_text = re.sub(r"\s+", "", "".join(normalized_lines))
    if len(visible_text) < PICTURE_OCR_MIN_VISIBLE_CHARS:
        return []

    if not re.search(r"[가-힣]", "".join(normalized_lines)) and len(re.findall(r"[A-Za-z0-9]", visible_text)) < 12:
        return []

    accepted_lines = [line for line in normalized_lines if is_useful_hwp_picture_ocr_line(line)]
    if not accepted_lines:
        return []
    if len(accepted_lines) < PICTURE_OCR_MIN_ACCEPTED_LINES:
        hangul_total = sum(len(re.findall(r"[가-힣]", line)) for line in accepted_lines)
        if hangul_total < 8:
            return []

    return [f"{PICTURE_OCR_PREFIX}{line}" for line in accepted_lines[:PICTURE_OCR_MAX_LINES]]


def build_hwp_picture_ocr_lines_by_bindata_id(hwp_path: Path, xml_path: Path) -> dict[int, list[str]]:
    backend = available_hwp_picture_ocr_backend()
    if backend is None:
        return {}

    root = ET.parse(xml_path).getroot()
    bindata_refs = extract_hwp_bindata_refs(root)
    if not bindata_refs:
        return {}

    assets = extract_hwp_picture_assets(hwp_path, bindata_refs)
    if not assets:
        return {}

    recovered_lines: dict[int, list[str]] = {}
    with tempfile.TemporaryDirectory() as tempdir:
        tempdir_path = Path(tempdir)
        for bindata_id, asset in assets.items():
            image_path = tempdir_path / f"{asset.storage_id}.{asset.ext}"
            image_path.write_bytes(asset.data)
            if backend == "tesseract":
                ocr_text = run_tesseract_ocr(image_path)
            else:  # pragma: no cover - unreachable until a second backend is added
                ocr_text = None
            if not ocr_text:
                continue
            formatted_lines = format_hwp_picture_ocr_lines(ocr_text)
            if formatted_lines:
                recovered_lines[bindata_id] = formatted_lines
    return recovered_lines


def append_hwp_text_line(text_parts: list[str], output: list[str]) -> None:
    text = normalize_hwp_line("".join(text_parts))
    text_parts.clear()
    if not text or NOISE_LINE_RE.match(text):
        return
    output.append(text)


def extract_hwp_paragraph_lines(
    paragraph: ET.Element,
    picture_ocr_by_bindata_id: dict[int, list[str]] | None = None,
) -> list[str]:
    lines: list[str] = []
    for child in paragraph:
        if xml_local_name(child.tag) != "LineSeg":
            continue
        text_parts: list[str] = []
        for node in child:
            local_name = xml_local_name(node.tag)
            if local_name == "Text":
                text_parts.append(node.text or "")
                continue
            if local_name == "ControlChar":
                if node.attrib.get("name") in SPACE_CONTROL_NAMES:
                    text_parts.append(" ")
                continue
            placeholder = hwp_control_placeholder(node)
            if placeholder is None:
                continue
            append_hwp_text_line(text_parts, lines)
            lines.append(placeholder)
            if placeholder == "<그림>" and picture_ocr_by_bindata_id:
                bindata_id = hwp_picture_bindata_id(node)
                if bindata_id is not None:
                    lines.extend(picture_ocr_by_bindata_id.get(bindata_id, []))
        append_hwp_text_line(text_parts, lines)
    return lines


def extract_hwp_lines_from_xml(
    xml_path: Path,
    picture_ocr_by_bindata_id: dict[int, list[str]] | None = None,
) -> list[str]:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    body = next((node for node in root if xml_local_name(node.tag) == "BodyText"), None)
    if body is None:
        return []

    lines: list[str] = []
    for paragraph in body.iter():
        if xml_local_name(paragraph.tag) != "Paragraph":
            continue
        paragraph_lines = extract_hwp_paragraph_lines(
            paragraph,
            picture_ocr_by_bindata_id=picture_ocr_by_bindata_id,
        )
        if not paragraph_lines:
            continue
        lines.extend(paragraph_lines)
        lines.append("")
    return lines


def dump_hwp_xml(hwp_path: Path, xml_path: Path) -> None:
    if Hwp5File is None:
        raise RuntimeError(
            "HWP support requires the optional 'hwp5' package, which is not installed on this machine."
        ) from HWP5_IMPORT_ERROR

    with closing(Hwp5File(str(hwp_path))) as hwp5_file:
        with xml_path.open("wb") as stream:
            hwp5_file.xmlevents(embedbin=False).dump(stream)


def format_hwp_text(hwp_path: Path) -> str:
    with tempfile.TemporaryDirectory() as tempdir:
        xml_path = Path(tempdir) / f"{hwp_path.stem}.xml"
        dump_hwp_xml(hwp_path, xml_path)
        picture_ocr_by_bindata_id = build_hwp_picture_ocr_lines_by_bindata_id(hwp_path, xml_path)
        return format_exam_lines(
            extract_hwp_lines_from_xml(
                xml_path,
                picture_ocr_by_bindata_id=picture_ocr_by_bindata_id,
            )
        )


def format_source_text(source_path: Path) -> str:
    suffix = source_path.suffix.lower()
    if suffix == ".pdf":
        return format_pdf_text(source_path)
    if suffix == ".hwp":
        return format_hwp_text(source_path)
    raise ValueError(f"Unsupported source format: {source_path}")


def build_source_link(source_path: Path, vault_root: Path) -> str:
    try:
        rel = source_path.relative_to(vault_root)
        rel_posix = rel.as_posix()
        return f"[[{rel_posix}|{source_path.name}]]"
    except ValueError:
        return source_path.as_posix()


def build_markdown(source_path: Path, body_text: str, vault_root: Path) -> str:
    return (
        f"# {source_path.stem}\n\n"
        f"- 원본 파일: {build_source_link(source_path, vault_root)}\n"
        f"- 형식: {source_path.suffix.lstrip('.')}\n\n"
        "## 추출 텍스트\n\n"
        f"{body_text}"
    )


def render_markdown(source_path: Path, vault_root: Path) -> str:
    body_text = format_source_text(source_path)
    return build_markdown(source_path, body_text, vault_root)


def write_markdown_output(output_path: Path, markdown: str) -> bool:
    if output_path.exists():
        existing = output_path.read_text(encoding="utf-8")
        if existing == markdown:
            return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return True


def export_pdf(
    pdf_path: Path,
    vault_root: Path,
    output_path: Path,
) -> GenerationResult:
    markdown = render_markdown(pdf_path, vault_root)
    changed = write_markdown_output(output_path, markdown)
    return GenerationResult(source_path=pdf_path, output_path=output_path, changed=changed)


def export_hwp(
    hwp_path: Path,
    vault_root: Path,
    output_path: Path,
) -> GenerationResult:
    markdown = render_markdown(hwp_path, vault_root)
    changed = write_markdown_output(output_path, markdown)
    return GenerationResult(source_path=hwp_path, output_path=output_path, changed=changed)


def export_source(
    source_path: Path,
    vault_root: Path,
    output_path: Path,
) -> GenerationResult:
    suffix = source_path.suffix.lower()
    if suffix == ".pdf":
        return export_pdf(source_path, vault_root, output_path)
    if suffix == ".hwp":
        return export_hwp(source_path, vault_root, output_path)
    raise ValueError(f"Unsupported source format: {source_path}")


def export_supported_official_sources(
    paths: Sequence[Path],
    vault_root: Path,
    textified_root_override: Path | None = None,
) -> list[GenerationResult]:
    sources = collect_supported_official_sources(paths, vault_root)
    if not sources:
        raise SystemExit("No supported official PDF/HWP sources were found under the provided path(s).")
    return [
        export_source(
            source_path=source_path,
            vault_root=vault_root,
            output_path=derive_official_output_path(source_path, vault_root, textified_root_override),
        )
        for source_path in sources
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Format LEET official PDFs/HWPs into exam-like markdown."
    )
    parser.add_argument("inputs", nargs="+", type=Path, help="Source PDF/HWP path(s) or supported official tree directories")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Markdown output path for a single explicit input; prints to stdout when omitted outside the supported official tree",
    )
    parser.add_argument(
        "--vault-root",
        type=Path,
        default=DEFAULT_VAULT_ROOT,
        help="Vault root used to build Obsidian source links",
    )
    parser.add_argument(
        "--official-textified-root",
        type=Path,
        help="Override the destination root used when mirroring supported official exam sources into Official_Textified markdown",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    inputs = [path.expanduser() for path in args.inputs]

    if args.output and len(inputs) != 1:
        raise SystemExit("--output can only be used with a single input path.")

    batch_mode = len(inputs) > 1 or any(path.is_dir() for path in inputs)
    if batch_mode:
        if args.output:
            raise SystemExit("--output is not supported for batch or directory inputs.")
        results = export_supported_official_sources(
            paths=inputs,
            vault_root=args.vault_root,
            textified_root_override=args.official_textified_root,
        )
        for result in results:
            print(result.output_path)
        return

    input_path = inputs[0]
    if input_path.suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
        raise SystemExit("Only PDF and HWP inputs are supported by this formatter.")

    if args.output:
        result = export_source(input_path, args.vault_root, args.output)
        print(result.output_path)
        return

    if is_supported_official_source(input_path, args.vault_root):
        result = export_source(
            source_path=input_path,
            vault_root=args.vault_root,
            output_path=derive_official_output_path(
                input_path,
                args.vault_root,
                args.official_textified_root,
            ),
        )
        print(result.output_path)
        return

    markdown = render_markdown(input_path, args.vault_root)
    print(markdown, end="")


if __name__ == "__main__":
    main()
