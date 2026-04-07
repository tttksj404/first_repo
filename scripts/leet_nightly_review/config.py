"""LEET Nightly Review — 설정 및 상수"""
from pathlib import Path
from datetime import date
import os

# ─── 경로 ───────────────────────────────────────────────
VAULT = Path('/Users/tttksj/Library/Mobile Documents/iCloud~md~obsidian/Documents/note')
LEET_BASE = VAULT / '01. Areas' / 'LEET'
DAILY_DIR = LEET_BASE / 'Daily'
TRACKERS_DIR = LEET_BASE / 'Trackers'
COACH_NOTES_DIR = DAILY_DIR / 'Coach Notes'
CBT_DIR = VAULT / '02. Resources' / 'LEET' / '05. CBT_실전연습'

REPO = Path('/Users/tttksj/first_repo')
LOG_DIR = REPO / 'logs'
ENV_FILE = REPO / '.env'

ERROR_LOG = TRACKERS_DIR / 'LEET Error Log.md'
SCORE_TRACKER = TRACKERS_DIR / 'LEET Score Tracker.md'
WEAKNESS_DASHBOARD = TRACKERS_DIR / 'LEET Weakness Dashboard.md'
GATE_TRACKER = TRACKERS_DIR / 'LEET Gate Tracker.md'

# ─── 시험 정보 ───────────────────────────────────────────
EXAM_DATE = date(2026, 7, 19)
START_DATE = date(2026, 3, 17)

# ─── 실수 코드 ───────────────────────────────────────────
ERROR_CODES = [
    '과잉추론', '조건누락', '범위확대', '입장전도',
    '변수관리실패', '시간압박', '계산집착', '버리기실패',
]

# ─── 요일별 루틴 (0=Mon … 6=Sun) ─────────────────────────
WEEKDAY_FOCUS = {
    0: {'label': '월', 'reasoning': '실험평가형', 'verbal': '지문 1편 복습'},
    1: {'label': '화', 'reasoning': '견해평가형', 'verbal': '지문 1편 복습'},
    2: {'label': '수', 'reasoning': '추론형', 'verbal': '지문 1편 복습'},
    3: {'label': '목', 'reasoning': '규칙적용형', 'verbal': '지문 1편 복습'},
    4: {'label': '금', 'reasoning': '오답재풀이', 'verbal': '지문 1편 복습'},
    5: {'label': '토', 'reasoning': 'B군 2문항', 'verbal': '-'},
    6: {'label': '일', 'reasoning': '기출 1세트 or 오답정리', 'verbal': '-'},
}

WEEKDAY_CBT_TYPE = {
    0: '추리논증',
    1: '언어이해',
    2: '추리논증',
    3: '언어이해',
    4: '추리논증',  # 금: 오답 유형 기반
    5: '추리논증',
    6: '언어이해',
}

# ─── 게이트 체크포인트 ────────────────────────────────────
GATE_DATES = [
    date(2026, 4, 13),
    date(2026, 5, 11),
    date(2026, 6, 15),
    date(2026, 7, 5),
]

# ─── Telegram ─────────────────────────────────────────────
def _load_env():
    """간단한 .env 로더"""
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env

_env = _load_env()
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN') or _env.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = '6768216338'

# ─── 적응 규칙 임계값 ────────────────────────────────────
ERROR_REPEAT_THRESHOLD = 3       # 실수 코드 N회 이상 → 집중교정
SCORE_LOOKBACK = 3               # 점수 추세 판단 윈도우
SKIP_CONSECUTIVE_DAYS = 3        # N일 연속 미수행 → 간소화
COMPLETION_LOW_THRESHOLD = 0.5   # 50% 미만 → 부분 이월
GATE_WARNING_DAYS = 5            # 게이트 D-N 이내 → 카운트다운

# ─── 센티넬 마커 ──────────────────────────────────────────
SENTINEL_START = '<!-- nightly-review-start -->'
SENTINEL_END = '<!-- nightly-review-end -->'
