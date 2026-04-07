"""LEET Nightly Review — CBT 생성기 연동 (Claude Code CLI via OAuth)"""
import os
import subprocess
import logging
from datetime import date
from pathlib import Path

from .config import CBT_DIR, WEEKDAY_CBT_TYPE, REPO

log = logging.getLogger('leet_nightly')

CLAUDE_BIN = Path.home() / '.local' / 'bin' / 'claude'


def generate_daily_cbt(tomorrow: date, error_analysis: dict) -> str | None:
    """내일 요일/약점 기반 CBT 자동 생성 — Claude Code CLI (OAuth) 사용"""
    dow = tomorrow.weekday()
    cbt_type = WEEKDAY_CBT_TYPE.get(dow, '추리논증')

    # 약점 기반 토픽 선택
    topic = _select_topic(error_analysis, cbt_type)

    # 기존 Day 번호 파악해서 중복 방지
    before_files = set(_list_cbt_files(cbt_type))

    # Claude Code CLI로 /generate-leet 스킬 호출 (OAuth 인증, API 키 불필요)
    prompt_parts = [f'/generate-leet {cbt_type} 1']
    if topic:
        prompt_parts[0] += f' {topic}'

    cmd = [
        str(CLAUDE_BIN),
        '-p',                              # non-interactive print mode
        '--dangerously-skip-permissions',   # nightly 자동화이므로 권한 스킵
        '--no-session-persistence',         # 세션 저장 불필요
        '--max-budget-usd', '1.0',         # 안전장치: 최대 $1
        prompt_parts[0],
    ]

    log.info(f"CBT generation: type={cbt_type}, topic={topic}, cmd={' '.join(cmd[:4])}...")

    # CLAUDECODE 환경변수 제거 (중첩 실행 방지 우회)
    env = {k: v for k, v in os.environ.items() if k != 'CLAUDECODE'}
    env['PATH'] = f"{CLAUDE_BIN.parent}:{env.get('PATH', '/usr/bin:/bin')}"

    try:
        result = subprocess.run(
            cmd,
            cwd=str(REPO),
            env=env,
            capture_output=True, text=True,
            timeout=600,  # Claude Code: 웹검색+생성+검증까지 최대 10분
        )
        if result.returncode == 0:
            # 새로 생성된 파일 찾기
            after_files = set(_list_cbt_files(cbt_type))
            new_files = after_files - before_files
            if new_files:
                newest = max(new_files, key=lambda f: f.stat().st_mtime)
                rel = newest.relative_to(
                    Path('/Users/tttksj/Library/Mobile Documents/iCloud~md~obsidian/Documents/note')
                )
                log.info(f"CBT created: {newest.name}")
                return f'[[{rel}]]'
            else:
                log.warning("Claude Code completed but no new CBT file found")
        else:
            log.error(f"Claude Code exit {result.returncode}: {result.stderr[:300]}")
            print(f"[WARN] CBT generation failed: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        log.error("CBT generation timed out (600s)")
        print("[WARN] CBT generation timed out")
    except FileNotFoundError:
        log.error(f"Claude CLI not found at {CLAUDE_BIN}")
        print(f"[WARN] Claude CLI not found at {CLAUDE_BIN}")

    return None


def _select_topic(error_analysis: dict, cbt_type: str) -> str | None:
    """실수 패턴 기반 토픽 추천"""
    repeated = error_analysis.get('repeated_3plus', [])
    if not repeated:
        return None

    # 실수 코드 → 토픽 매핑
    topic_map = {
        '과잉추론': '논증 구조 분석' if cbt_type == '추리논증' else '철학적 논변',
        '조건누락': '조건 추리 게임' if cbt_type == '추리논증' else '법규범 해석',
        '범위확대': '논리적 오류 판별' if cbt_type == '추리논증' else '과학 이론 비교',
        '입장전도': '다중 입장 분석' if cbt_type == '추리논증' else '사회과학 논쟁',
        '변수관리실패': '수리 추론' if cbt_type == '추리논증' else None,
        '시간압박': None,  # 토픽보다 전략 문제
        '계산집착': '확률/통계 추론' if cbt_type == '추리논증' else None,
        '버리기실패': None,
    }

    for code in repeated:
        topic = topic_map.get(code)
        if topic:
            return topic

    return None


def _list_cbt_files(cbt_type: str) -> list[Path]:
    """해당 유형의 CBT 파일 목록"""
    subdir = CBT_DIR / ('언어이해' if cbt_type == '언어이해' else '추리논증')
    if not subdir.exists():
        return []
    return list(subdir.glob('CBT_*.md'))


def _find_latest_cbt(cbt_type: str) -> Path | None:
    """가장 최근 생성된 CBT 파일 찾기"""
    files = _list_cbt_files(cbt_type)
    if not files:
        return None
    return max(files, key=lambda f: f.stat().st_mtime)
