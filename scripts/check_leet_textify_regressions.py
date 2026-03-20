#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

SUSPICIOUS_OCR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bA\s+Baa\b", re.IGNORECASE),
    re.compile(r"\bBoB\b", re.IGNORECASE),
    re.compile(r"\bFASS\s+SE\b", re.IGNORECASE),
)

BROKEN_EOJEOL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"확인하십\s*$"),
    re.compile(r"^\s*시오\b"),
)

STACK_TOKEN_RE = re.compile(r"^(?:[①-⑤]|[A-C]|[가-힣]{1,4}|[ⓐ-ⓩ↓+\-=()/0-9]+)$")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    text: str


@dataclass(frozen=True)
class ScanResult:
    files_scanned: int
    findings: list[Finding]


def iter_target_files(paths: Iterable[Path]) -> Iterable[Path]:
    seen: set[Path] = set()
    for path in paths:
        if path.is_file() and path.suffix.lower() == ".md":
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield path
            continue
        if not path.exists() or not path.is_dir():
            continue
        for candidate in sorted(path.rglob("*.md")):
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield candidate


def find_vertical_stack(lines: list[str], start_index: int) -> int:
    count = 0
    index = start_index
    while index < len(lines):
        if lines[index].strip() == "":
            index += 1
            continue
        if STACK_TOKEN_RE.fullmatch(lines[index].strip()):
            count += 1
            index += 1
            continue
        break
    return count


def scan_markdown(path: Path) -> list[Finding]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    findings: list[Finding] = []

    for line_no, line in enumerate(lines, 1):
        stripped = line.strip()
        for pattern in SUSPICIOUS_OCR_PATTERNS:
            if pattern.search(line):
                findings.append(Finding(str(path), line_no, "ocr-noise-token", stripped))
        for pattern in BROKEN_EOJEOL_PATTERNS:
            if pattern.search(line):
                findings.append(Finding(str(path), line_no, "broken-eojeol", stripped))
        if re.fullmatch(r"[①-⑤A-C]", stripped):
            findings.append(Finding(str(path), line_no, "singleton-stack-token", stripped))

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if not STACK_TOKEN_RE.fullmatch(stripped):
            continue
        stack_len = find_vertical_stack(lines, index)
        if stack_len >= 5:
            findings.append(Finding(str(path), index + 1, "long-vertical-stack", stripped))

    deduped: list[Finding] = []
    seen_keys: set[tuple[str, int, str, str]] = set()
    for finding in findings:
        key = (finding.path, finding.line, finding.rule, finding.text)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(finding)
    return deduped


def scan_paths(paths: list[Path]) -> ScanResult:
    findings: list[Finding] = []
    files = list(iter_target_files(paths))
    for path in files:
        findings.extend(scan_markdown(path))
    return ScanResult(files_scanned=len(files), findings=findings)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan LEET markdown for likely textify regressions.")
    parser.add_argument("paths", nargs="+", type=Path, help="Markdown file(s) or directory roots to scan")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = scan_paths([path.expanduser() for path in args.paths])

    if args.json:
        print(json.dumps({"files_scanned": result.files_scanned, "findings": [asdict(f) for f in result.findings]}, ensure_ascii=False, indent=2))
        return

    print(f"files_scanned={result.files_scanned}")
    print(f"findings={len(result.findings)}")
    for finding in result.findings:
        print(f"{finding.path}:{finding.line}:{finding.rule}:{finding.text}")

    if result.findings:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
