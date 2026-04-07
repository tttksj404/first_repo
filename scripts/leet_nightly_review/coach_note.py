"""LEET Nightly Review — 코치 노트 생성"""
from datetime import date
from pathlib import Path

from .config import COACH_NOTES_DIR, EXAM_DATE, WEEKDAY_FOCUS


def generate_coach_note(
    today: date,
    completion: dict,
    error_analysis: dict,
    score_analysis: dict,
    skip_analysis: dict,
    adaptations_made: list[str],
) -> str:
    """코치 노트 마크다운 생성"""
    dday = (EXAM_DATE - today).days
    focus = WEEKDAY_FOCUS.get(today.weekday(), {})
    label = focus.get('label', '?')
    rate = completion['completion_rate']
    done = completion['completed_tasks']
    total = completion['total_tasks']

    # ── 오늘 요약 ──
    summary_lines = [
        f"- 완료율: {done}/{total} ({rate:.0%})",
        f"- 리뷰 작성: {completion['reviews_filled']}개",
        f"- Error Log: {'기록됨' if completion['error_log_recorded'] else '미기록'}",
        f"- Score Tracker: {'기록됨' if completion['score_recorded'] else '미기록'}",
    ]
    if completion['habit_note']:
        summary_lines.append(f"- 교정 습관: {completion['habit_note']}")

    # ── 패턴 분석 ──
    freq = error_analysis.get('week_frequency', {})
    freq_str = ', '.join(f"{k}({v})" for k, v in
                          sorted(freq.items(), key=lambda x: -x[1])[:5])
    pattern_lines = [f"- 주간 실수 빈도: {freq_str or '데이터 없음'}"]

    repeated = error_analysis.get('repeated_3plus', [])
    if repeated:
        pattern_lines.append(f"- **{', '.join(repeated)} 3회+ 반복 중** → 집중교정 추가")

    trend = error_analysis.get('trend', 'stable')
    trend_map = {'improving': '개선 중', 'stable': '유지', 'worsening': '악화 중'}
    pattern_lines.append(f"- 실수 추세: {trend_map.get(trend, trend)}")

    # 점수
    v_trend = _arrow(score_analysis.get('verbal_trend', ''))
    r_trend = _arrow(score_analysis.get('reasoning_trend', ''))
    pattern_lines.append(f"- 점수 추세: 언어 {v_trend} / 추리 {r_trend}")

    if score_analysis.get('avg_verbal'):
        pattern_lines.append(
            f"- 3회 평균: 언어 {score_analysis['avg_verbal']:.0f} / "
            f"추리 {score_analysis.get('avg_reasoning', 0):.0f}"
        )

    # ── 적응 내용 ──
    adapt_lines = [f"- {a}" for a in adaptations_made] if adaptations_made else ["- 변경 없음"]

    # ── 한 줄 조언 ──
    oneliner = _coach_oneliner(error_analysis, score_analysis, skip_analysis, rate)

    note = f"""# 코치 노트 — {today.isoformat()} ({label}) D-{dday}

## 오늘 요약
{chr(10).join(summary_lines)}

## 패턴 분석
{chr(10).join(pattern_lines)}

## 내일 적응 내용
{chr(10).join(adapt_lines)}

## 한 줄 조언
> {oneliner}
"""
    return note


def save_coach_note(today: date, content: str) -> Path:
    """코치 노트 파일 저장"""
    COACH_NOTES_DIR.mkdir(parents=True, exist_ok=True)
    path = COACH_NOTES_DIR / f'{today.isoformat()}_coach.md'
    path.write_text(content, encoding='utf-8')
    return path


def _arrow(trend: str) -> str:
    return {'up': '↑', 'down': '↓', 'flat': '→', 'insufficient': '?'}.get(trend, '?')


def _coach_oneliner(error_analysis, score_analysis, skip_analysis, rate):
    if rate == 0:
        return "내일은 10분이라도. 시작이 반입니다."
    if skip_analysis.get('recommendation') == 'simplify':
        return "완벽을 버리세요. 오늘 10분이라도 손 대는 게 승리입니다."
    if score_analysis.get('recommendation') == 'reduce_volume':
        return "양을 줄이세요. 틀린 2문제 완벽 분석 > 10문제 풀기."
    repeated = error_analysis.get('repeated_3plus', [])
    if repeated:
        from .adaptor import _get_fix_advice
        return _get_fix_advice(repeated[0])
    if error_analysis.get('trend') == 'improving':
        return "실수가 줄고 있습니다. 이 페이스 유지!"
    return "원칙대로. 스캐너 읽기 + 선지 세모 + 10초 탈출."
