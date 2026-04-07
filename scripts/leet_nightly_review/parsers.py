"""LEET Nightly Review — 마크다운 파서"""
import re
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Optional


# ─── 데일리 노트 파싱 ─────────────────────────────────────
def parse_daily_completion(filepath: Path) -> dict:
    """데일리노트 체크박스 완료율 + 리뷰 작성 여부 파싱"""
    if not filepath.exists():
        return _empty_completion()

    text = filepath.read_text(encoding='utf-8')
    lines = text.splitlines()

    # 체크박스 파싱
    checked = sum(1 for l in lines if re.match(r'^- \[x\]', l.strip()))
    unchecked_lines = [l.strip() for l in lines if re.match(r'^- \[ \]', l.strip())]
    total = checked + len(unchecked_lines)

    # 블록별 완료 감지
    blocks = {'morning': False, 'lunch': False, 'evening': False}
    current_block = None
    for line in lines:
        if '아침' in line and ('###' in line or '08:30' in line):
            current_block = 'morning'
        elif '점심' in line and ('###' in line or '13:' in line):
            current_block = 'lunch'
        elif '저녁' in line and ('###' in line or '21:' in line):
            current_block = 'evening'
        if current_block and re.match(r'^- \[x\]', line.strip()):
            blocks[current_block] = True

    # 리뷰 섹션 파싱
    reviews_filled = 0
    for section in ['Review 1', 'Review 2']:
        idx = text.find(section)
        if idx != -1:
            section_text = text[idx:idx + 500]
            # "문항:" 뒤에 내용이 있는지 체크
            m = re.search(r'문항:\s*(.+)', section_text)
            if m and m.group(1).strip():
                reviews_filled += 1

    # Error Log 기록 여부
    error_log_recorded = bool(re.search(r'\[x\].*Error Log', text))
    # Score Tracker 기록 여부
    score_recorded = bool(re.search(r'\[x\].*Score Tracker', text))

    # 내일 교정 습관
    habit_match = re.search(r'내일 바로 교정할 습관 1개:\s*(.+)', text)
    habit_note = habit_match.group(1).strip() if habit_match else None

    return {
        'total_tasks': total,
        'completed_tasks': checked,
        'completion_rate': checked / total if total > 0 else 0.0,
        'unchecked_tasks': unchecked_lines,
        'reviews_filled': reviews_filled,
        'error_log_recorded': error_log_recorded,
        'score_recorded': score_recorded,
        'habit_note': habit_note,
        'blocks_completed': blocks,
    }


def was_file_edited(filepath: Path, reference_date: Optional[date] = None) -> bool:
    """파일이 해당 날짜에 수정되었는지 mtime으로 판단"""
    if not filepath.exists():
        return False
    ref = reference_date or date.today()
    mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
    return mtime.date() == ref


def _empty_completion() -> dict:
    return {
        'total_tasks': 0,
        'completed_tasks': 0,
        'completion_rate': 0.0,
        'unchecked_tasks': [],
        'reviews_filled': 0,
        'error_log_recorded': False,
        'score_recorded': False,
        'habit_note': None,
        'blocks_completed': {'morning': False, 'lunch': False, 'evening': False},
    }


# ─── Error Log 파싱 ───────────────────────────────────────
def parse_error_log(filepath: Path) -> list[dict]:
    """Error Log 마크다운 테이블 파싱"""
    if not filepath.exists():
        return []

    text = filepath.read_text(encoding='utf-8')
    rows = []

    for line in text.splitlines():
        line = line.strip()
        if not line.startswith('|') or '---' in line:
            continue
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if len(cells) >= 5 and re.match(r'\d{4}-\d{2}-\d{2}', cells[0]):
            rows.append({
                'date': cells[0],
                'subject': cells[1],
                'problem': cells[2],
                'error_code': cells[3],
                'fix': cells[4],
            })

    return rows


def get_errors_in_range(errors: list[dict], start: date, end: date) -> list[dict]:
    """날짜 범위 내 에러 필터"""
    result = []
    for e in errors:
        try:
            d = date.fromisoformat(e['date'])
            if start <= d <= end:
                result.append(e)
        except (ValueError, KeyError):
            continue
    return result


# ─── Score Tracker 파싱 ───────────────────────────────────
def parse_score_tracker(filepath: Path) -> list[dict]:
    """Score Tracker 마크다운 테이블 파싱"""
    if not filepath.exists():
        return []

    text = filepath.read_text(encoding='utf-8')
    rows = []

    for line in text.splitlines():
        line = line.strip()
        if not line.startswith('|') or '---' in line:
            continue
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if len(cells) >= 5 and re.match(r'\d{4}-\d{2}-\d{2}', cells[0]):
            # 점수 추출 (e.g., "7/10" → 70, "85" → 85)
            verbal = _extract_score(cells[2])
            reasoning = _extract_score(cells[3])
            rows.append({
                'date': cells[0],
                'type': cells[1],
                'verbal': verbal,
                'reasoning': reasoning,
                'verbal_raw': cells[2],
                'reasoning_raw': cells[3],
                'summary': cells[4] if len(cells) > 4 else '',
            })

    return rows


def _extract_score(raw: str) -> Optional[float]:
    """점수 문자열에서 숫자 추출 (7/10 → 70.0, 85 → 85.0)"""
    raw = raw.strip()
    if not raw or raw == '-':
        return None
    # "7/10" 형태
    m = re.match(r'(\d+)\s*/\s*(\d+)', raw)
    if m:
        numer, denom = int(m.group(1)), int(m.group(2))
        return (numer / denom * 100) if denom > 0 else None
    # 숫자만
    m = re.match(r'(\d+(?:\.\d+)?)', raw)
    if m:
        return float(m.group(1))
    return None
