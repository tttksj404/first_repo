#!/usr/bin/env python3
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

VAULT = Path('/Users/tttksj/Library/Mobile Documents/iCloud~md~obsidian/Documents/note')
BASE = VAULT / '01. Areas' / 'LEET'
DAILY = BASE / 'Daily'
PLANS = BASE / 'Plans'
TRACKERS = BASE / 'Trackers'

START_DATE = date(2026, 3, 17)
EXAM_DATE = date(2026, 7, 26)
TOTAL_DAYS = (EXAM_DATE - START_DATE).days + 1

VERBAL_SETS = [
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_51_문언중심적_법해석론_비판]]',
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_52_문언을_넘는_해석과_문언에_반하는_해석의_구별]]',
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_53_법적_추론의_기능과_판단_정당화]]',
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_54_법문의_가능한_의미와_실재론_논쟁]]',
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_55_수사학적_법이론과_법적_논증의_설득구조]]',
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_56_신수사학과_판결문_이유제시의_기준]]',
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_57_유추와_목적론적_축소의_경계설정]]',
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_58_유추금지_원칙과_형벌법규_명확성]]',
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_59_형법해석의_한계와_법방법론]]',
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_60_행정법_해석원리와_기본권_통제]]',
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_61_제도적_자연법과_헌법해석의_정당화_구조]]',
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_62_표현의_자유_위험심사와_사전억제_기준]]',
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_63_법적_구제를_받을_권리와_복층_권리구제_모델]]',
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_64_데이터_기반_정책결정과_설명가능성의_조건]]',
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_65_인공지능_비의도적_법익침해와_보충적_형사개입]]',
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_66_초기_양자역학과_인과성의_재구성]]',
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_67_언어능력의_생득성_논쟁과_경험적_구성]]',
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_68_자유의지와_결정론의_양립가능성]]',
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_69_하이데거의_죽음_개념과_현존재의_개별화]]',
    '[[02. Resources/LEET/01. 실전지문_트레이닝/LEET_실전지문_70_최저임금_인상과_고용효과의_조건부_메커니즘]]',
]

REASONING_SETS = [
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_01_생태적_합리성과_탐색_규칙]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_02_소수영향과_일관성]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_03_전망이론과_기준점_이동]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_04_프레이밍_효과_실험_평가]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_05_법다원주의와_불복경로_규칙_적용]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_06_전제수용과_설득효과]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_07_확장된_마음과_결합구성_구분]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_08_예측처리와_4E_관계_논증구조]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_09_문화진화와_유전가능성_해석]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_10_어포던스와_조건충족_사례판단]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_11_다원적_무지와_공적_순응]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_12_심슨의_역설과_부분집단_비교]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_13_멘털어카운팅과_지출판단]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_14_현상유지편향과_디폴트_효과_실험평가]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_15_조건부_독립성과_추론의_오류]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_16_집단행위자와_공적_표명의_조건]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_17_평균으로의_회귀와_평가오류]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_18_인과적_이질성과_평균효과의_해석]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_19_앵커링과_전망이론의_상호작용]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_20_법정확률과_DNA증거의_해석]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_21_reference_dependent_SEU와_선택수정]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_22_사회적_기준점과_위험선택]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_23_정신적_어포던스와_과제선택]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_24_예측처리와_체화명제_논쟁분석]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_25_표집비용과_생태적_합리성]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_26_다원적_무지와_집합행동]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_27_법치보편주의_비판과_평가기준]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_28_추이성_자료선택과_조건부독립]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_29_프레이밍과_범주화_효과]]',
    '[[02. Resources/LEET/04. 추리논증_트레이닝/LEET_추리논증_실전문항_30_간접통제와_사회적의미]]',
]

def ensure_dirs() -> None:
    for p in [BASE, DAILY, PLANS, TRACKERS]:
        p.mkdir(parents=True, exist_ok=True)

def phase_for(day: date) -> str:
    if day <= date(2026, 4, 15): return 'Phase 1 — 기초 체력 + 스캔 습관 고정'
    if day <= date(2026, 5, 31): return 'Phase 2 — 기출 회독 + 실전지문 병행'
    if day <= date(2026, 6, 30): return 'Phase 3 — 시간 압박 + 오답 교정'
    return 'Phase 4 — 실전 모드 + 140점 피크 조정'

def verbal_focus(offset: int) -> str:
    return ['기출 언어이해 1세트 시간 재고 풀이','실전지문 2개 스캐너 읽기 + 선지 판단','오답 언어이해 3문항 재풀이 + 근거 회수','고난도 철학/과학 지문 느슨한 재독'][offset % 4]

def reasoning_focus(offset: int) -> str:
    return ['기출 추리논증 1세트 시간 재고 풀이','실전문항 10~15개 조건 마킹 훈련','논개매/강약매 적용 오답 복기','계산/조건추론 문제 속도전'][offset % 4]

def daily_note(day: date, offset: int) -> str:
    verbal = VERBAL_SETS[offset % len(VERBAL_SETS)]
    reasoning = REASONING_SETS[offset % len(REASONING_SETS)]
    next_verbal = VERBAL_SETS[(offset + 7) % len(VERBAL_SETS)]
    next_reasoning = REASONING_SETS[(offset + 7) % len(REASONING_SETS)]
    phase = phase_for(day)
    dday = (EXAM_DATE - day).days
    return f'''# {day.isoformat()} LEET Daily

- D-{dday}
- Phase: {phase}
- Goal: 7월 LEET 140점 / 언어이해 + 추리논증 동시 상향

## 오늘의 메인 루프
### 1) 언어이해
- [ ] {verbal_focus(offset)}
- [ ] 오늘 메인 자료: {verbal}
- [ ] 추가 보강 자료: {next_verbal}
- [ ] 목표: 완벽 이해가 아니라 **정보 위치 파악 + 선지 판단 속도**

### 2) 추리논증
- [ ] {reasoning_focus(offset)}
- [ ] 오늘 메인 자료: {reasoning}
- [ ] 추가 보강 자료: {next_reasoning}
- [ ] 목표: **조건 마킹 / 변수 정리 / 함정 선지 제거 속도**

### 3) 오답 교정
- [ ] 오늘 가장 결정적이었던 오답 2개 기록
- [ ] `[[01. Areas/LEET/Trackers/LEET Error Log]]`에 실수 유형 남기기
- [ ] `[[01. Areas/LEET/Trackers/LEET Score Tracker]]` 갱신

### 4) 생성 지문/문항 활용
- [ ] 필요 시 `[[01. Areas/LEET/Plans/LEET Problem Writing Principles]]` 확인
- [ ] 기존 생성 자원에서 1세트 추가 훈련

## 시간 가이드
- 아침: 언어이해 1지문 or 추리 10문항 가볍게 예열
- 낮: 기출 또는 생성 세트 1회
- 밤: 오답 복기 + 기록

## 오늘 체크할 태도
- [ ] 언어이해에서 멈춰 읽지 않았는가?
- [ ] 추리논증에서 조건을 먼저 마킹했는가?
- [ ] 오답 이유를 몰라서가 아니라 논리 오류로 적었는가?

## 링크
- [[01. Areas/LEET/LEET_140_July_Execution_System]]
- [[01. Areas/LEET/Plans/LEET Problem Writing Principles]]
- [[01. Areas/LEET/Trackers/LEET Error Log]]
- [[01. Areas/LEET/Trackers/LEET Score Tracker]]
'''

def _write_if_missing(path: Path, content: str) -> None:
    """파일이 없을 때만 생성 (이미 존재하면 스킵)"""
    if not path.exists():
        path.write_text(content, encoding='utf-8')

def write_static_files() -> None:
    _write_if_missing(BASE / 'LEET_140_July_Execution_System.md', '# LEET 140 July Execution System\n\n## 목표\n- 시험: 2026-07 LEET\n- 목표 점수: 140+\n- 핵심 전략: 기출 회독 + 생성 실전지문/실전문항 + 오답 논리 교정\n')
    _write_if_missing(PLANS / 'LEET Problem Writing Principles.md', '# LEET Problem Writing Principles\n\n## 언어이해 지문 작성 원리\n- 5~7단락 수준의 밀도 유지\n- 통설→한계→대안 / 개념→조건→사례 / 쟁점→견해 비교→조건부 결론 구조\n\n## 추리논증 문항 작성 원리\n- 조건 제시형, 논증 분석형, 사례 판단형 혼합\n- 배경지식보다 조건 정리와 변수 통제 능력을 묻기\n')
    _write_if_missing(PLANS / 'LEET July Roadmap.md', f'# LEET July Roadmap\n\n- 시작일: {START_DATE.isoformat()}\n- 시험일: {EXAM_DATE.isoformat()}\n- 총 {TOTAL_DAYS}일\n')
    _write_if_missing(TRACKERS / 'LEET Error Log.md', '# LEET Error Log\n\n- 과잉추론 / 조건 누락 / 범위 확대 / 입장 전도 / 변수 관리 실패 / 시간 압박으로 근거 회수 실패 중 하나로 적기\n')
    _write_if_missing(TRACKERS / 'LEET Score Tracker.md', '# LEET Score Tracker\n\n- 날짜 / 언어이해 / 추리논증 / 총평 기록\n')

def write_daily_notes() -> None:
    for offset in range(TOTAL_DAYS):
        day = START_DATE + timedelta(days=offset)
        path = DAILY / f'{day.isoformat()}.md'
        if not path.exists():
            path.write_text(daily_note(day, offset), encoding='utf-8')

def update_today(target: date | None = None) -> None:
    current = target or datetime.now().date()
    if current < START_DATE:
        current = START_DATE
    if current > EXAM_DATE:
        current = EXAM_DATE
    nxt = current + timedelta(days=1)
    nxt_link = f'[[01. Areas/LEET/Daily/{nxt.isoformat()}]]' if nxt <= EXAM_DATE else '(시험일 이후)'
    (DAILY / 'Today.md').write_text(f'# Today\n\n오늘 바로 볼 LEET 노트:\n- [[01. Areas/LEET/Daily/{current.isoformat()}]]\n\n## 빠른 링크\n- [[01. Areas/LEET/LEET_140_July_Execution_System]]\n- [[01. Areas/LEET/Plans/LEET Problem Writing Principles]]\n- [[01. Areas/LEET/Trackers/LEET Error Log]]\n- [[01. Areas/LEET/Trackers/LEET Score Tracker]]\n\n## 다음 날\n- {nxt_link}\n\n## 갱신 시각\n- {datetime.now().isoformat(timespec="seconds")}\n', encoding='utf-8')

def main() -> None:
    ensure_dirs()
    write_static_files()
    write_daily_notes()
    update_today()
    print(DAILY / 'Today.md')

if __name__ == '__main__':
    main()
