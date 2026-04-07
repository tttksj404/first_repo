"""LEET Nightly Review — 알림 시스템 (Telegram + macOS)"""
import json
import ssl
import subprocess
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from .config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    WEEKDAY_FOCUS, DAILY_DIR, EXAM_DATE, WEEKDAY_CBT_TYPE,
)
from .parsers import parse_daily_completion, was_file_edited


# ─── Telegram 전송 ────────────────────────────────────────
def send_telegram(message: str) -> bool:
    """Telegram 메시지 전송 (iPhone + Mac 동시)"""
    if not TELEGRAM_BOT_TOKEN:
        print("[WARN] TELEGRAM_BOT_TOKEN not set")
        return False

    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    data = json.dumps({
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML',
    }).encode('utf-8')

    req = urllib.request.Request(url, data=data,
                                 headers={'Content-Type': 'application/json'})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[ERROR] Telegram send failed: {e}")
        return False


# ─── macOS 네이티브 알림 ──────────────────────────────────
def send_macos_notification(title: str, message: str) -> None:
    """macOS Notification Center 알림"""
    escaped_msg = message.replace('"', '\\"').replace('\n', '\\n')
    escaped_title = title.replace('"', '\\"')
    subprocess.run([
        'osascript', '-e',
        f'display notification "{escaped_msg}" with title "{escaped_title}" sound name "Glass"'
    ], capture_output=True)


# ─── 아침 브리핑 (08:00) ──────────────────────────────────
def morning_briefing(target_date: date = None) -> None:
    """오늘 할당량 브리핑 전송"""
    today = target_date or date.today()
    dow = today.weekday()
    focus = WEEKDAY_FOCUS.get(dow, {})
    dday = (EXAM_DATE - today).days
    label = focus.get('label', '?')

    # CBT 파일 존재 확인
    cbt_type = WEEKDAY_CBT_TYPE.get(dow, '추리논증')
    cbt_status = "준비됨" if True else "없음"  # TODO: 실제 파일 체크

    # 코치노트에서 집중교정 읽기
    coach_dir = DAILY_DIR / 'Coach Notes'
    yesterday = today - timedelta(days=1)
    coach_file = coach_dir / f'{yesterday.isoformat()}_coach.md'
    focus_correction = ""
    if coach_file.exists():
        text = coach_file.read_text(encoding='utf-8')
        import re
        m = re.search(r'집중 교정.*?:\s*(.+)', text)
        if m:
            focus_correction = f"\n⚡ 집중교정: {m.group(1).strip()}"

    msg = (
        f"📚 LEET D-{dday} ({label}요일)\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔹 추리: {focus.get('reasoning', '-')}\n"
        f"🔹 언어: {focus.get('verbal', '-')}\n"
        f"🔹 CBT: {cbt_type} {cbt_status}"
        f"{focus_correction}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"화이팅! 오늘도 원칙대로."
    )

    send_telegram(msg)
    send_macos_notification(f"LEET D-{dday}", f"{label}: {focus.get('reasoning', '-')}")
    print(f"[OK] Morning briefing sent for {today}")


# ─── 저녁 마감 경고 (22:00) ───────────────────────────────
def evening_warning(target_date: date = None) -> None:
    """미수행 시 마감 2시간 전 경고"""
    today = target_date or date.today()
    note_path = DAILY_DIR / f'{today.isoformat()}.md'

    completion = parse_daily_completion(note_path)
    edited = was_file_edited(note_path, today)

    if completion['completion_rate'] > 0 or edited:
        # 이미 무언가 했음 → 경고 안 보냄
        print(f"[SKIP] Already active today ({completion['completion_rate']:.0%})")
        return

    msg = (
        f"⚠️ LEET 경고: 오늘 학습 미수행\n"
        f"━━━━━━━━━━━━━━━\n"
        f"마감까지 2시간 남음!\n"
        f"최소한 아침 블록(30분)이라도 하세요.\n"
        f"━━━━━━━━━━━━━━━\n"
        f"미수행 시 내일로 전체 이월됩니다."
    )

    send_telegram(msg)
    send_macos_notification("LEET 경고", "오늘 학습 미수행! 마감 2시간 전")
    print(f"[WARN] Evening warning sent for {today}")


# ─── 리뷰 결과 알림 (00:03) ───────────────────────────────
def review_result_notification(
    today: date,
    completion: dict,
    error_analysis: dict,
    score_analysis: dict,
    adaptations: list[str],
    cbt_generated: bool,
    deferred: bool,
) -> None:
    """야간 리뷰 결과 알림"""
    dday = (EXAM_DATE - today).days
    rate = completion['completion_rate']
    total = completion['total_tasks']
    done = completion['completed_tasks']

    if deferred and rate == 0:
        msg = (
            f"🚨 LEET D-{dday}: 오늘 0% — 전체 내일 이월\n"
            f"━━━━━━━━━━━━━━━\n"
            f"내일 분량이 2배가 됩니다.\n"
            f"3일 연속 미수행 시 플랜 간소화됩니다."
        )
    elif deferred:
        msg = (
            f"⚠️ LEET D-{dday}: {rate:.0%} 수행 ({done}/{total})\n"
            f"━━━━━━━━━━━━━━━\n"
            f"미완료 항목 내일 이월됨\n"
            f"{''.join('• ' + a + chr(10) for a in adaptations[:3])}"
        )
    else:
        # 정상 수행
        errors = ', '.join(error_analysis.get('today_errors', [])) or '없음'
        v_trend = _trend_arrow(score_analysis.get('verbal_trend', ''))
        r_trend = _trend_arrow(score_analysis.get('reasoning_trend', ''))

        adapt_lines = '\n'.join(f'• {a}' for a in adaptations[:3]) if adaptations else '변경 없음'
        cbt_line = "CBT 생성됨" if cbt_generated else ""

        msg = (
            f"✅ LEET D-{dday} 야간 리뷰 완료\n"
            f"━━━━━━━━━━━━━━━\n"
            f"수행률: {rate:.0%} ({done}/{total})\n"
            f"오답: {errors}\n"
            f"추세: 추리 {r_trend} / 언어 {v_trend}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{adapt_lines}"
            f"{chr(10) + cbt_line if cbt_line else ''}"
        )

    send_telegram(msg)
    send_macos_notification("LEET 야간 리뷰", f"수행률 {rate:.0%}")
    print(f"[OK] Review notification sent for {today}")


def _trend_arrow(trend: str) -> str:
    return {'up': '↑', 'down': '↓', 'flat': '→'}.get(trend, '?')


# ─── CLI 진입점 ───────────────────────────────────────────
def main():
    """python3 -m scripts.leet_nightly_review.notifier {morning|evening_check}"""
    if len(sys.argv) < 2:
        print("Usage: notifier {morning|evening_check}")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == 'morning':
        morning_briefing()
    elif cmd == 'evening_check':
        evening_warning()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == '__main__':
    main()
