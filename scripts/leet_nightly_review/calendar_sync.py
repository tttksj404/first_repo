"""LEET Nightly Review — macOS 캘린더 AppleScript 연동"""
import subprocess
from datetime import date, datetime


def get_calendar_events(target_date: date) -> list[dict]:
    """특정 날짜의 LEET 140 캘린더 이벤트 조회"""
    script = f'''
    tell application "Calendar"
        tell calendar "LEET 140"
            set dayStart to date "{_format_as_date(target_date)} 00:00:00"
            set dayEnd to dayStart + 1 * days
            set evts to (every event whose start date >= dayStart and start date < dayEnd)
            set output to ""
            repeat with e in evts
                set output to output & (summary of e) & "|||" & ((start date of e) as string) & "|||" & ((end date of e) as string) & "\\n"
            end repeat
            return output
        end tell
    end tell
    '''
    result = _run_applescript(script)
    events = []
    for line in result.strip().split('\n'):
        parts = line.split('|||')
        if len(parts) >= 3:
            events.append({
                'summary': parts[0].strip(),
                'start': parts[1].strip(),
                'end': parts[2].strip(),
            })
    return events


def update_event_title(target_date: date, old_keyword: str, new_title: str) -> bool:
    """이벤트 제목 업데이트 (키워드로 매칭)"""
    script = f'''
    tell application "Calendar"
        tell calendar "LEET 140"
            set dayStart to date "{_format_as_date(target_date)} 00:00:00"
            set dayEnd to dayStart + 1 * days
            set evts to (every event whose start date >= dayStart and start date < dayEnd and summary contains "{old_keyword}")
            if (count of evts) > 0 then
                set summary of (item 1 of evts) to "{new_title}"
                return "OK"
            end if
            return "NOT_FOUND"
        end tell
    end tell
    '''
    result = _run_applescript(script)
    return 'OK' in result


def update_event_time(target_date: date, keyword: str,
                       new_start_hour: int, new_start_min: int,
                       new_end_hour: int, new_end_min: int) -> bool:
    """이벤트 시간 변경"""
    ds = _format_as_date(target_date)
    script = f'''
    tell application "Calendar"
        tell calendar "LEET 140"
            set dayStart to date "{ds} 00:00:00"
            set dayEnd to dayStart + 1 * days
            set evts to (every event whose start date >= dayStart and start date < dayEnd and summary contains "{keyword}")
            if (count of evts) > 0 then
                set theEvent to item 1 of evts
                set newStart to date "{ds} {new_start_hour:02d}:{new_start_min:02d}:00"
                set newEnd to date "{ds} {new_end_hour:02d}:{new_end_min:02d}:00"
                set start date of theEvent to newStart
                set end date of theEvent to newEnd
                return "OK"
            end if
            return "NOT_FOUND"
        end tell
    end tell
    '''
    result = _run_applescript(script)
    return 'OK' in result


def apply_calendar_adaptations(tomorrow: date, adaptations: dict) -> list[str]:
    """적응 결과를 캘린더에 반영"""
    changes = []

    # 집중 교정 → 아침 이벤트 제목에 반영
    if adaptations.get('focus_correction'):
        error_code = adaptations['focus_correction']
        if update_event_title(tomorrow, '아침', f'LEET 아침 | 집중교정: {error_code}'):
            changes.append(f'아침 이벤트: 집중교정 {error_code}')

    # 양 축소 → 저녁 이벤트 시간 단축
    if adaptations.get('reduce_volume'):
        # 22:30 → 22:00 (30분 단축)
        if update_event_time(tomorrow, '저녁', 21, 0, 22, 0):
            changes.append('저녁 블록: 22:30 → 22:00 (양 축소)')

    # 간소화 → 모든 이벤트 제목에 "(간소화)" 추가
    if adaptations.get('simplify'):
        for keyword in ['아침', '점심', '저녁']:
            events = get_calendar_events(tomorrow)
            for evt in events:
                if keyword in evt['summary'] and '간소화' not in evt['summary']:
                    update_event_title(tomorrow, keyword,
                                       evt['summary'] + ' (간소화)')
        changes.append('전체 블록: 간소화 모드')

    return changes


# ─── 내부 헬퍼 ────────────────────────────────────────────
def _format_as_date(d: date) -> str:
    """AppleScript 날짜 포맷"""
    weekdays_kr = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']
    return f"{d.year}년 {d.month}월 {d.day}일 {weekdays_kr[d.weekday()]}"


def _run_applescript(script: str) -> str:
    """AppleScript 실행"""
    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0 and result.stderr:
            print(f"[WARN] AppleScript stderr: {result.stderr[:200]}")
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        print("[WARN] AppleScript timed out (30s)")
        return ''
    except Exception as e:
        print(f"[ERROR] AppleScript failed: {e}")
        return ''
