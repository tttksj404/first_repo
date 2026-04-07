"""LEET Nightly Review — 적응 콘텐츠 생성 + 데일리노트 주입"""
from datetime import date
from pathlib import Path
from typing import Optional

from .config import (
    SENTINEL_START, SENTINEL_END, WEEKDAY_FOCUS,
    COMPLETION_LOW_THRESHOLD, ERROR_CODES,
)


def generate_adaptive_content(
    tomorrow: date,
    error_analysis: dict,
    score_analysis: dict,
    skip_analysis: dict,
    gate_info: Optional[dict],
    deferred_tasks: list[str],
    cbt_link: Optional[str],
) -> str:
    """적응 콘텐츠 마크다운 생성"""
    sections = []
    dow = tomorrow.weekday()
    focus = WEEKDAY_FOCUS.get(dow, {})
    dday = (date(2026, 7, 19) - tomorrow).days

    # ── 이월 항목 ──
    if deferred_tasks:
        lines = [f'- [ ] [이월] {t}' for t in deferred_tasks]
        sections.append(f"## 어제 이월 항목\n" + '\n'.join(lines))

    # ── 집중 교정 (실수 3회+) ──
    repeated = error_analysis.get('repeated_3plus', [])
    if repeated:
        top_error = repeated[0]
        freq = error_analysis['week_frequency'].get(top_error, 0)
        fix_advice = _get_fix_advice(top_error)
        sections.append(
            f"## 집중 교정: {top_error} ({freq}회/주)\n"
            f"- {fix_advice}\n"
            f"- 오늘 문제 풀 때 이것만 의식하세요."
        )

    # ── 점수 하락 경고 ──
    if score_analysis['recommendation'] == 'reduce_volume':
        sections.append(
            "## 점수 추세 경고\n"
            "언어+추리 모두 하락 중입니다. **양보다 질에 집중하세요.**\n"
            "- 저녁 블록: 10문항 → 7문항으로 축소\n"
            "- 남은 시간은 오답 근거 분석에 투자"
        )
    elif score_analysis['recommendation'] == 'increase_review':
        declining = []
        if score_analysis['verbal_trend'] == 'down':
            declining.append('언어이해')
        if score_analysis['reasoning_trend'] == 'down':
            declining.append('추리논증')
        sections.append(
            f"## 점수 주의: {', '.join(declining)} 하락 중\n"
            f"- 해당 과목 리뷰 시간 15분 추가\n"
            f"- 근거 회수에 집중하세요."
        )

    # ── 간소화 (연속 미수행) ──
    if skip_analysis['recommendation'] == 'simplify':
        days = skip_analysis['consecutive_zero_days']
        sections.append(
            f"## 플랜 간소화 ({days}일 연속 미수행)\n"
            "**작게 시작하세요. 10분이라도 하는 게 안 하는 것보다 낫습니다.**\n"
            "- 아침: 치트시트 훑기만 (5분)\n"
            "- 점심: 지문 구조만 훑기 (5분)\n"
            "- 저녁: 추리 3문항만 (15분)"
        )

    # ── 게이트 카운트다운 ──
    if gate_info:
        sections.append(
            f"## 게이트 D-{gate_info['days_until']} ({gate_info['gate_date']})\n"
            "게이트 체크포인트가 다가옵니다. Gate Tracker에서 목표 달성률을 확인하세요."
        )

    # ── CBT 연습 ──
    if cbt_link:
        sections.append(
            f"## 오늘의 CBT 연습\n"
            f"- {cbt_link}\n"
            f"- 제한시간 내에 풀고 점수를 확인하세요."
        )

    # ── 코치 한마디 ──
    coach_line = _generate_coach_oneliner(error_analysis, score_analysis, skip_analysis)
    if coach_line:
        sections.append(f"## 코치 한마디\n> {coach_line}")

    return '\n\n'.join(sections) if sections else ''


def inject_into_daily_note(filepath: Path, adaptive_content: str) -> bool:
    """sentinel 마커 사이에 적응 콘텐츠 주입 (멱등)"""
    if not filepath.exists():
        return False

    text = filepath.read_text(encoding='utf-8')

    # 기존 sentinel 영역 제거
    if SENTINEL_START in text and SENTINEL_END in text:
        before = text[:text.index(SENTINEL_START)]
        after = text[text.index(SENTINEL_END) + len(SENTINEL_END):]
        text = before.rstrip('\n') + '\n\n' + after.lstrip('\n')

    if not adaptive_content.strip():
        filepath.write_text(text, encoding='utf-8')
        return True

    # 삽입 위치: "## 오늘 반드시 남길 것" 앞
    insertion_point = text.find('## 오늘 반드시 남길 것')
    if insertion_point == -1:
        # 대안: 파일 끝에 추가
        insertion_point = len(text)

    block = f"\n{SENTINEL_START}\n{adaptive_content}\n{SENTINEL_END}\n\n"

    new_text = text[:insertion_point] + block + text[insertion_point:]
    filepath.write_text(new_text, encoding='utf-8')
    return True


def extract_deferred_tasks(completion: dict) -> list[str]:
    """미완료 체크박스에서 이월할 항목 추출"""
    tasks = []
    for line in completion.get('unchecked_tasks', []):
        # "- [ ] ..." → 텍스트 부분만
        cleaned = line.lstrip('- [ ] ').strip()
        if cleaned and not cleaned.startswith('[이월]'):
            tasks.append(cleaned)
    return tasks


# ─── 내부 헬퍼 ────────────────────────────────────────────
def _get_fix_advice(error_code: str) -> str:
    """실수 코드별 교정 조언"""
    advices = {
        '과잉추론': '지문에 없는 내용을 추론하지 마세요. "지문에 근거가 있는가?"만 확인.',
        '조건누락': '문제의 조건을 먼저 전부 마킹하세요. 마킹 안 한 조건이 함정입니다.',
        '범위확대': '선지가 지문보다 넓은 범위를 말하면 오답입니다. 범위를 비교하세요.',
        '입장전도': 'A의 입장과 B의 입장을 바꿔 놓은 선지에 주의. 누구의 입장인지 확인.',
        '변수관리실패': '변수가 3개 이상이면 표를 그리세요. 머릿속으로 하지 마세요.',
        '시간압박': '10초 이상 막히면 △ 표시하고 다음으로. 돌아올 시간은 있습니다.',
        '계산집착': '계산에 빠지지 마세요. 선지를 먼저 보고 역추적이 가능한지 확인.',
        '버리기실패': '모르는 문제는 버리세요. 3분 이상 한 문제에 쓰지 마세요.',
    }
    return advices.get(error_code, f'{error_code} 유형에 주의하세요.')


def _generate_coach_oneliner(error_analysis: dict, score_analysis: dict,
                              skip_analysis: dict) -> str:
    """상황별 코치 한 줄 조언"""
    if skip_analysis['recommendation'] == 'simplify':
        return "완벽을 버리세요. 오늘 10분이라도 손 대는 게 승리입니다."
    if score_analysis['recommendation'] == 'reduce_volume':
        return "양을 줄이세요. 틀린 문제 2개를 완벽히 분석하는 게 10문제 풀기보다 낫습니다."
    repeated = error_analysis.get('repeated_3plus', [])
    if repeated:
        return _get_fix_advice(repeated[0])
    if error_analysis.get('trend') == 'improving':
        return "실수가 줄고 있습니다. 이 페이스 유지하세요."
    return "원칙대로. 스캐너 읽기 + 선지 세모 + 10초 탈출."
