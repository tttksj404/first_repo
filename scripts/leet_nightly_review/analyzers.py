"""LEET Nightly Review — 분석 엔진"""
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from .config import (
    ERROR_REPEAT_THRESHOLD, SCORE_LOOKBACK, SKIP_CONSECUTIVE_DAYS,
    COMPLETION_LOW_THRESHOLD, GATE_WARNING_DAYS, GATE_DATES, DAILY_DIR,
)
from .parsers import (
    parse_error_log, get_errors_in_range, parse_score_tracker,
    parse_daily_completion,
)


def analyze_error_patterns(errors: list[dict], today: date, lookback_days: int = 7) -> dict:
    """최근 N일 실수 코드 빈도 분석"""
    start = today - timedelta(days=lookback_days)
    recent = get_errors_in_range(errors, start, today)
    today_errors = [e['error_code'] for e in recent if e['date'] == today.isoformat()]

    week_freq = Counter(e['error_code'] for e in recent)
    repeated = [code for code, cnt in week_freq.items() if cnt >= ERROR_REPEAT_THRESHOLD]
    dominant = week_freq.most_common(1)[0][0] if week_freq else None

    # 추세: 최근 3일 vs 이전 4일 비교
    mid = today - timedelta(days=3)
    recent_3 = len(get_errors_in_range(errors, mid, today))
    older_4 = len(get_errors_in_range(errors, start, mid - timedelta(days=1)))
    if recent_3 > older_4:
        trend = 'worsening'
    elif recent_3 < older_4:
        trend = 'improving'
    else:
        trend = 'stable'

    return {
        'today_errors': today_errors,
        'week_frequency': dict(week_freq),
        'repeated_3plus': repeated,
        'dominant_error': dominant,
        'trend': trend,
        'total_recent': len(recent),
    }


def analyze_score_trend(scores: list[dict], window: int = SCORE_LOOKBACK) -> dict:
    """점수 3회 이동평균 추세"""
    # 날짜 역순 정렬 (최신 먼저)
    sorted_scores = sorted(scores, key=lambda s: s['date'], reverse=True)

    verbals = [s['verbal'] for s in sorted_scores if s['verbal'] is not None][:window * 2]
    reasonings = [s['reasoning'] for s in sorted_scores if s['reasoning'] is not None][:window * 2]

    def _avg(lst, n):
        subset = lst[:n]
        return sum(subset) / len(subset) if subset else None

    def _trend(lst, n):
        if len(lst) < n * 2:
            return 'insufficient'
        recent = sum(lst[:n]) / n
        older = sum(lst[n:n * 2]) / n
        if recent > older + 5:
            return 'up'
        elif recent < older - 5:
            return 'down'
        return 'flat'

    avg_v = _avg(verbals, window)
    avg_r = _avg(reasonings, window)

    v_trend = _trend(verbals, window)
    r_trend = _trend(reasonings, window)

    # 권장사항
    if v_trend == 'down' and r_trend == 'down':
        recommendation = 'reduce_volume'
    elif v_trend == 'down' or r_trend == 'down':
        recommendation = 'increase_review'
    else:
        recommendation = 'normal'

    return {
        'latest_verbal': verbals[0] if verbals else None,
        'latest_reasoning': reasonings[0] if reasonings else None,
        'avg_verbal': avg_v,
        'avg_reasoning': avg_r,
        'verbal_trend': v_trend,
        'reasoning_trend': r_trend,
        'recommendation': recommendation,
    }


def analyze_skip_patterns(today: date, lookback_days: int = 5) -> dict:
    """최근 N일 완료율 패턴 분석"""
    completions = []
    consecutive_zero = 0

    for i in range(lookback_days):
        d = today - timedelta(days=i)
        p = DAILY_DIR / f'{d.isoformat()}.md'
        c = parse_daily_completion(p)
        completions.append(c)
        if i == 0 or (consecutive_zero == i and c['completion_rate'] == 0.0):
            if c['completion_rate'] == 0.0:
                consecutive_zero = i + 1

    rates = [c['completion_rate'] for c in completions]
    avg_rate = sum(rates) / len(rates) if rates else 0.0

    # 일관되게 스킵되는 블록 탐지
    block_skips = {'morning': 0, 'lunch': 0, 'evening': 0}
    for c in completions:
        for block, done in c['blocks_completed'].items():
            if not done:
                block_skips[block] += 1
    consistently_skipped = [b for b, cnt in block_skips.items()
                            if cnt >= lookback_days - 1]

    # 간소화 권장
    if consecutive_zero >= SKIP_CONSECUTIVE_DAYS:
        recommendation = 'simplify'
    elif avg_rate < COMPLETION_LOW_THRESHOLD:
        recommendation = 'reduce'
    else:
        recommendation = 'normal'

    return {
        'avg_completion_rate': avg_rate,
        'consecutive_zero_days': consecutive_zero,
        'consistently_skipped_blocks': consistently_skipped,
        'recommendation': recommendation,
    }


def check_gate_proximity(today: date) -> Optional[dict]:
    """게이트 날짜 접근 체크"""
    for gate_date in GATE_DATES:
        days_until = (gate_date - today).days
        if 0 < days_until <= GATE_WARNING_DAYS:
            return {
                'gate_date': gate_date.isoformat(),
                'days_until': days_until,
            }
    return None
