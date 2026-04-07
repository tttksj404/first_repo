"""LEET Nightly Review — 메인 오케스트레이터

매일 밤 00:00 실행:
1. 오늘 데일리노트 분석
2. 미완료 이월 처리
3. 적응 콘텐츠 생성 → 내일 노트 주입
4. CBT 자동 생성
5. 캘린더 업데이트
6. 코치 노트 생성
7. 결과 알림 (Telegram + macOS)
"""
import sys
import logging
from datetime import date, timedelta
from pathlib import Path

from .config import (
    DAILY_DIR, ERROR_LOG, SCORE_TRACKER, EXAM_DATE, LOG_DIR,
    COMPLETION_LOW_THRESHOLD,
)
from .parsers import (
    parse_daily_completion, parse_error_log, parse_score_tracker,
    was_file_edited,
)
from .analyzers import (
    analyze_error_patterns, analyze_score_trend,
    analyze_skip_patterns, check_gate_proximity,
)
from .adaptor import (
    generate_adaptive_content, inject_into_daily_note,
    extract_deferred_tasks,
)
from .calendar_sync import apply_calendar_adaptations
from .cbt_integration import generate_daily_cbt
from .coach_note import generate_coach_note, save_coach_note
from .notifier import review_result_notification, send_macos_notification

# ─── 로깅 ─────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_DIR / 'leet_nightly.log'),
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
log = logging.getLogger('leet_nightly')


def nightly_review(target_date: date | None = None) -> None:
    """야간 리뷰 메인 실행"""
    today = target_date or date.today()
    tomorrow = today + timedelta(days=1)

    # 시험 날짜 지났으면 중단
    if tomorrow > EXAM_DATE:
        log.info(f"Exam date passed. Skipping review for {today}")
        return

    log.info(f"=== Nightly review start: {today} ===")
    send_macos_notification("LEET", "야간 리뷰 실행 중...")

    # ── 1. 오늘 데일리노트 파싱 ──
    today_path = DAILY_DIR / f'{today.isoformat()}.md'
    completion = parse_daily_completion(today_path)
    edited = was_file_edited(today_path, today)
    log.info(f"Completion: {completion['completion_rate']:.0%} "
             f"({completion['completed_tasks']}/{completion['total_tasks']}), "
             f"edited={edited}")

    # ── 2. 트래커 파싱 ──
    errors = parse_error_log(ERROR_LOG)
    scores = parse_score_tracker(SCORE_TRACKER)
    log.info(f"Errors total: {len(errors)}, Scores total: {len(scores)}")

    # ── 3. 분석 ──
    error_analysis = analyze_error_patterns(errors, today)
    score_analysis = analyze_score_trend(scores)
    skip_analysis = analyze_skip_patterns(today)
    gate_info = check_gate_proximity(tomorrow)

    log.info(f"Error trend: {error_analysis['trend']}, "
             f"Score rec: {score_analysis['recommendation']}, "
             f"Skip rec: {skip_analysis['recommendation']}")

    # ── 4. 이월 처리 ──
    deferred_tasks = []
    is_deferred = False

    if completion['completion_rate'] == 0 and not edited:
        # 전체 이월
        deferred_tasks = extract_deferred_tasks(completion)
        if not deferred_tasks:
            # 체크박스가 없는 경우 (노트가 아예 비어있음)
            deferred_tasks = ["전체 할당량 이월 (어제 미수행)"]
        is_deferred = True
        log.warning(f"FULL DEFERRAL: {len(deferred_tasks)} tasks")
    elif completion['completion_rate'] < COMPLETION_LOW_THRESHOLD:
        # 부분 이월
        deferred_tasks = extract_deferred_tasks(completion)
        is_deferred = True
        log.info(f"Partial deferral: {len(deferred_tasks)} tasks")

    # ── 5. CBT 생성 ──
    cbt_link = None
    try:
        cbt_link = generate_daily_cbt(tomorrow, error_analysis)
        if cbt_link:
            log.info(f"CBT generated: {cbt_link}")
    except Exception as e:
        log.error(f"CBT generation failed: {e}")

    # ── 6. 적응 콘텐츠 생성 + 주입 ──
    adaptive_content = generate_adaptive_content(
        tomorrow=tomorrow,
        error_analysis=error_analysis,
        score_analysis=score_analysis,
        skip_analysis=skip_analysis,
        gate_info=gate_info,
        deferred_tasks=deferred_tasks,
        cbt_link=cbt_link,
    )

    tomorrow_path = DAILY_DIR / f'{tomorrow.isoformat()}.md'
    if tomorrow_path.exists():
        inject_into_daily_note(tomorrow_path, adaptive_content)
        log.info(f"Injected adaptive content into {tomorrow_path.name}")
    else:
        log.warning(f"Tomorrow's note not found: {tomorrow_path}")

    # ── 7. 캘린더 업데이트 ──
    cal_adaptations = {}
    adaptations_list = []

    if error_analysis.get('repeated_3plus'):
        cal_adaptations['focus_correction'] = error_analysis['repeated_3plus'][0]
        adaptations_list.append(f"집중교정: {error_analysis['repeated_3plus'][0]}")

    if score_analysis['recommendation'] == 'reduce_volume':
        cal_adaptations['reduce_volume'] = True
        adaptations_list.append("저녁 블록 양 축소")

    if skip_analysis['recommendation'] == 'simplify':
        cal_adaptations['simplify'] = True
        adaptations_list.append("전체 간소화 모드")

    if is_deferred:
        adaptations_list.append(f"미완료 {len(deferred_tasks)}개 이월")

    if cbt_link:
        adaptations_list.append("CBT 생성됨")

    try:
        cal_changes = apply_calendar_adaptations(tomorrow, cal_adaptations)
        log.info(f"Calendar changes: {cal_changes}")
    except Exception as e:
        log.error(f"Calendar sync failed: {e}")

    # ── 8. 코치 노트 생성 ──
    coach_content = generate_coach_note(
        today, completion, error_analysis, score_analysis,
        skip_analysis, adaptations_list,
    )
    coach_path = save_coach_note(today, coach_content)
    log.info(f"Coach note saved: {coach_path}")

    # ── 9. 결과 알림 ──
    review_result_notification(
        today=today,
        completion=completion,
        error_analysis=error_analysis,
        score_analysis=score_analysis,
        adaptations=adaptations_list,
        cbt_generated=bool(cbt_link),
        deferred=is_deferred,
    )

    log.info(f"=== Nightly review complete: {today} ===")


def main():
    """CLI 진입점"""
    target = None
    if len(sys.argv) > 1:
        try:
            target = date.fromisoformat(sys.argv[1])
        except ValueError:
            print(f"Invalid date: {sys.argv[1]}")
            sys.exit(1)

    nightly_review(target)


if __name__ == '__main__':
    main()
