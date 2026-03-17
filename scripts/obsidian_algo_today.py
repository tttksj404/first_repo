#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

VAULT = Path('/Users/tttksj/Library/Mobile Documents/iCloud~md~obsidian/Documents/note')
BASE = VAULT / 'Algorithms'
DAILY = BASE / 'Daily'
PLANS = BASE / 'Plans'
TRACKERS = BASE / 'Trackers'

START_DATE = date(2026, 3, 17)
TOTAL_DAYS = 90

WEEKLY_PATTERNS = {
    0: [('Warm-up', 'BOJ 1260 DFS와 BFS', '[[BFS]] / [[DFS & Backtracking]]'), ('Main 1', 'BOJ 14502 연구소', '[[Simulation]] / [[DFS & Backtracking]] / [[BFS]]'), ('Main 2', 'BOJ 14891 톱니바퀴', '[[Simulation]] / [[Implementation]]'), ('Review', '직전 구현/BFS 오답 1개 재풀이', '복습')],
    1: [('Warm-up', 'Programmers 완주하지 못한 선수', '해시'), ('Main 1', 'BOJ 13460 구슬 탈출 2', '[[Simulation]] / [[BFS]]'), ('Main 2', 'BOJ 15686 치킨 배달', '[[DFS & Backtracking]] / 구현'), ('Review', '전날 구현 문제 복습', '복습')],
    2: [('Warm-up', 'BOJ 1920 수 찾기', '[[Binary Search]]'), ('Main 1', 'BOJ 12865 평범한 배낭', '[[DP]]'), ('Main 2', 'BOJ 11053 가장 긴 증가하는 부분 수열', '[[DP]]'), ('Review', 'BFS 기본 문제 1개', '복습')],
    3: [('Warm-up', 'BOJ 10816 숫자 카드 2', '이분탐색/해시'), ('Main 1', 'BOJ 16236 아기 상어', '[[Simulation]] / [[BFS]]'), ('Main 2', 'BOJ 12100 2048 (Easy)', '[[Simulation]] / [[DFS & Backtracking]]'), ('Review', '배낭/DP 기초 복습', '복습')],
    4: [('Warm-up', 'BOJ 9012 괄호', '스택'), ('Main 1', 'BOJ 17144 미세먼지 안녕!', '[[Simulation]] / [[Implementation]]'), ('Main 2', 'BOJ 14500 테트로미노', '[[DFS & Backtracking]] / 구현'), ('Review', '이분탐색 문제 1개', '복습')],
    5: [('Warm-up', 'BOJ 17608 막대기', '구현'), ('Main 1', '삼성형 실전 세트 - 구현 2문제 연속', '실전'), ('Main 2', '삼성형 실전 세트 - 그래프/시뮬레이션', '실전'), ('Review', '이번 주 오답 2개', '복습')],
    6: [('Warm-up', '쉬운 문자열/배열 문제 1개', '워밍업'), ('Main 1', '오답 복습 1', '복습'), ('Main 2', '오답 복습 2', '복습'), ('Review', '패턴 노트 정리', '복습')],
}

PHASE_LABELS = [
    (0, 27, 'Phase 1 — Foundation'),
    (28, 55, 'Phase 2 — Expansion'),
    (56, 89, 'Phase 3 — Exam Mode'),
]


def ensure_dirs() -> None:
    for p in [BASE, DAILY, PLANS, TRACKERS]:
        p.mkdir(parents=True, exist_ok=True)


def phase_for(offset: int) -> str:
    for start, end, label in PHASE_LABELS:
        if start <= offset <= end:
            return label
    return PHASE_LABELS[-1][2]


def daily_note(day: date, offset: int) -> str:
    items = WEEKLY_PATTERNS[offset % 7]
    phase = phase_for(offset)
    lines = [
        f'# {day.isoformat()} Daily Coding Test',
        '',
        f'- Phase: {phase}',
        '- Goal: 삼성 A형 + 기업 코테 공통 역량 동시 강화',
        '',
        '## 오늘의 루프',
    ]
    for section, title, pattern in items:
        lines += [f'### {section}', f'- [ ] {title}', f'- 패턴: {pattern}', '']
    lines += [
        '## 패턴 보강',
        '- [ ] 오늘 가장 많이 막힌 패턴 노트 업데이트',
        '',
        '## 템플릿 손코딩',
        '- [ ] BFS / DFS / DP / 구현 템플릿 중 1개',
        '',
        '## 회고',
        '- 오늘 막힌 것:',
        '- 반복 실수:',
        '- 내일 보완할 것:',
        '',
        '## 링크',
        '- [[Algorithms/00 Master Index]]',
        '- [[Algorithms/Trackers/Daily Loop]]',
        '- [[Algorithms/Trackers/Weekly Tracker]]',
    ]
    return '\n'.join(lines) + '\n'


def write_daily_notes() -> None:
    for offset in range(TOTAL_DAYS):
        day = START_DATE + timedelta(days=offset)
        path = DAILY / f'{day.isoformat()}.md'
        if not path.exists():
            path.write_text(daily_note(day, offset), encoding='utf-8')


def write_master_plan() -> None:
    plan = BASE / 'Plans/90-Day Execution Map.md'
    lines = ['# 90-Day Execution Map', '', '## 개요', '- 삼성 A형 + 기업 코테 합격용 90일 루프', '']
    for offset in range(TOTAL_DAYS):
        day = START_DATE + timedelta(days=offset)
        lines.append(f'- Day {offset+1:02d} — [[Algorithms/Daily/{day.isoformat()}]] ({phase_for(offset)})')
    plan.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def update_today(target: date | None = None) -> Path:
    current = target or datetime.now().date()
    if current < START_DATE:
        current = START_DATE
    if current > START_DATE + timedelta(days=TOTAL_DAYS - 1):
        current = START_DATE + timedelta(days=TOTAL_DAYS - 1)
    today_path = DAILY / 'Today.md'
    relative = f'[[Algorithms/Daily/{current.isoformat()}]]'
    next_day = current + timedelta(days=1)
    next_link = f'[[Algorithms/Daily/{next_day.isoformat()}]]' if next_day <= START_DATE + timedelta(days=TOTAL_DAYS - 1) else '(90일 플랜 종료)'
    text = f'''# Today

오늘 바로 열어야 할 노트:
- {relative}

## 오늘 루프
- 워밍업 1문제
- 메인 2문제
- 복습 1문제
- 패턴 보강 1개
- 템플릿 손코딩 1개

## 다음 날
- {next_link}

## 갱신 시각
- {datetime.now().isoformat(timespec='seconds')}
'''
    today_path.write_text(text, encoding='utf-8')
    return today_path


def write_manifest() -> None:
    manifest = {
        'start_date': START_DATE.isoformat(),
        'total_days': TOTAL_DAYS,
        'vault': str(VAULT),
        'generated_at': datetime.now().isoformat(timespec='seconds'),
    }
    (BASE / 'Plans/automation_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


def main() -> None:
    ensure_dirs()
    write_daily_notes()
    write_master_plan()
    write_manifest()
    today_path = update_today()
    print(today_path)


if __name__ == '__main__':
    main()
