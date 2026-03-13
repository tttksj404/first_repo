from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen, Request

from quant_binance.telegram_intent import help_message_ko, parse_telegram_intent

ROOT = Path('/Users/tttksj/first_repo')
ENV_FILES = [ROOT / '.env', ROOT / '.env.local']
SSL_CONTEXT = ssl._create_unverified_context()
CODEX_TASKS = {'status-check', 'capital-report', 'latest-run-review', 'strategy-review'}
GEMINI_TASKS = {'status-check', 'capital-report', 'latest-run-review', 'strategy-review'}


def load_env_value(name: str) -> str:
    value = os.environ.get(name, '').strip()
    if value:
        return value
    for path in ENV_FILES:
        if not path.exists():
            continue
        for raw in path.read_text(encoding='utf-8').splitlines():
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, val = line.split('=', 1)
            if key.strip() == name:
                return val.strip().strip('"').strip("'")
    return ''


def telegram_api(method: str, params: dict[str, str | int]) -> dict:
    token = load_env_value('TELEGRAM_BOT_TOKEN')
    if not token:
        raise RuntimeError('TELEGRAM_BOT_TOKEN is required')
    url = f'https://api.telegram.org/bot{token}/{method}'
    data = urlencode(params).encode('utf-8')
    req = Request(url, data=data)
    with urlopen(req, timeout=60, context=SSL_CONTEXT) as resp:
        return json.loads(resp.read().decode('utf-8'))


def get_updates(offset: int | None) -> list[dict]:
    token = load_env_value('TELEGRAM_BOT_TOKEN')
    url = f'https://api.telegram.org/bot{token}/getUpdates?timeout=30'
    if offset is not None:
        url += f'&offset={offset}'
    with urlopen(url, timeout=60, context=SSL_CONTEXT) as resp:
        payload = json.loads(resp.read().decode('utf-8'))
    return payload.get('result', [])


def send_message(chat_id: int, text: str) -> None:
    telegram_api('sendMessage', {'chat_id': chat_id, 'text': text[:4000]})


def run_local_command(action: str) -> str:
    if action == 'help':
        return help_message_ko()
    if action == 'strategy-report':
        proc = subprocess.run(
            ['sh', 'scripts/quant_strategy_promotion.sh', 'report', 'quant_runtime'],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=600,
        )
        output = (proc.stdout or '') + ('\n' + proc.stderr if proc.stderr else '')
        return output.strip() or f'command finished with exit={proc.returncode}'
    if action == 'strategy-approve':
        proc = subprocess.run(
            ['sh', 'scripts/quant_strategy_promotion.sh', 'approve', 'quant_runtime'],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=900,
        )
        output = (proc.stdout or '') + ('\n' + proc.stderr if proc.stderr else '')
        return output.strip() or f'command finished with exit={proc.returncode}'
    if action == 'strategy-reject':
        proc = subprocess.run(
            ['sh', 'scripts/quant_strategy_promotion.sh', 'reject', 'quant_runtime'],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=600,
        )
        output = (proc.stdout or '') + ('\n' + proc.stderr if proc.stderr else '')
        return output.strip() or f'command finished with exit={proc.returncode}'
    proc = subprocess.run(
        ['sh', 'scripts/quant_remote_command.sh', action],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=600,
    )
    output = (proc.stdout or '') + ('\n' + proc.stderr if proc.stderr else '')
    output = output.strip() or f'command finished with exit={proc.returncode}'
    return output


def run_codex_task(task: str) -> str:
    proc = subprocess.run(
        ['sh', 'scripts/quant_codex_task.sh', task],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=900,
    )
    output = (proc.stdout or '') + ('\n' + proc.stderr if proc.stderr else '')
    output = output.strip() or f'codex task finished with exit={proc.returncode}'
    return output


def run_gemini_task(task: str) -> str:
    proc = subprocess.run(
        ['sh', 'scripts/quant_gemini_task.sh', task],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=900,
    )
    output = (proc.stdout or '') + ('\n' + proc.stderr if proc.stderr else '')
    output = output.strip() or f'gemini task finished with exit={proc.returncode}'
    return output


def explain_latest_runtime() -> str:
    base = ROOT / 'quant_runtime'
    state_candidates = sorted(base.rglob('summary.state.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    summary_candidates = sorted(base.rglob('summary.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    state_path = state_candidates[0] if state_candidates else None
    summary_path = summary_candidates[0] if summary_candidates else None
    if state_path is None or summary_path is None or not summary_path.exists() or not state_path.exists():
        return '최신 런타임 요약 파일이 없습니다.'
    summary = json.loads(summary_path.read_text(encoding='utf-8'))
    state = json.loads(state_path.read_text(encoding='utf-8'))
    lines = [
        f"최신 상태: decision_count={summary.get('decision_count')} live_order_count={summary.get('live_order_count')} tested_order_count={summary.get('tested_order_count')}",
        f"kill_switch={summary.get('kill_switch')}",
    ]
    top_reasons = summary.get('top_rejection_reasons') or {}
    if top_reasons:
        top_text = ', '.join(f'{k}:{v}' for k, v in list(top_reasons.items())[:5])
        lines.append(f"주요 차단 사유: {top_text}")
    recent = summary.get('recent_decisions') or []
    if recent:
        lines.append("최근 판단:")
        for item in recent[-3:]:
            reasons = ','.join(item.get('reasons', []))
            lines.append(f"- {item.get('symbol')} {item.get('mode')} side={item.get('side')} score={item.get('score')} reasons={reasons}")
    paper_count = summary.get('paper_open_futures_position_count', len(summary.get('open_futures_positions') or []))
    exchange_count = summary.get('exchange_live_futures_position_count', len(summary.get('exchange_live_futures_positions') or []))
    lines.append(
        f"열린 spot 포지션={len(summary.get('open_spot_positions') or [])}, "
        f"paper futures={paper_count}, exchange futures={exchange_count}"
    )
    if summary.get('futures_position_mismatch'):
        details = summary.get('futures_position_mismatch_details') or {}
        lines.append(
            "futures 불일치: "
            f"missing_in_paper={details.get('missing_in_paper') or []}, "
            f"missing_on_exchange={details.get('missing_on_exchange') or []}"
        )
    lines.append(f"last_decision_timestamp={state.get('last_decision_timestamp')}")
    return '\\n'.join(lines)


def main() -> int:
    allowed = load_env_value('TELEGRAM_CHAT_ID_ALLOWLIST')
    allowlist = {item.strip() for item in allowed.split(',') if item.strip()}
    offset = None
    print('telegram bridge started', flush=True)
    while True:
        try:
            updates = get_updates(offset)
            for item in updates:
                offset = item['update_id'] + 1
                message = item.get('message') or item.get('edited_message')
                if not message:
                    continue
                chat_id = str(message['chat']['id'])
                full_text = (message.get('text') or '').strip()
                if allowlist and chat_id not in allowlist:
                    send_message(int(chat_id), '허용되지 않은 채팅입니다.')
                    continue
                if full_text in {'/help', 'help', '도움말', '명령어', '사용법'}:
                    send_message(int(chat_id), help_message_ko())
                    continue
                if full_text in {'왜 거래 안돼', '왜 거래 안 돼', '왜 주문 안돼', '왜 주문 안 돼', '왜 변동이 없어', '왜 변동이 없지'}:
                    send_message(int(chat_id), explain_latest_runtime())
                    continue
                if full_text.lower().startswith('/codex'):
                    parts = full_text.split()
                    if len(parts) < 2:
                        send_message(int(chat_id), '사용법: /codex <status-check|capital-report|latest-run-review|strategy-review>')
                        continue
                    task = parts[1].strip().lower()
                    if task not in CODEX_TASKS:
                        send_message(int(chat_id), '알 수 없는 Codex 작업입니다.')
                        continue
                    send_message(int(chat_id), f"Codex 분석을 실행합니다: {task}")
                    result = run_codex_task(task)
                    send_message(int(chat_id), result)
                    continue
                if full_text.lower().startswith('/gemini'):
                    parts = full_text.split()
                    if len(parts) < 2:
                        send_message(int(chat_id), '사용법: /gemini <status-check|capital-report|latest-run-review|strategy-review>')
                        continue
                    task = parts[1].strip().lower()
                    if task not in GEMINI_TASKS:
                        send_message(int(chat_id), '알 수 없는 Gemini 작업입니다.')
                        continue
                    send_message(int(chat_id), f"Gemini 분석을 실행합니다: {task}")
                    result = run_gemini_task(task)
                    send_message(int(chat_id), result)
                    continue
                intent = parse_telegram_intent(full_text)
                if intent.kind == 'local':
                    send_message(int(chat_id), f"요청을 실행합니다: {intent.value}")
                    result = run_local_command(intent.value)
                    send_message(int(chat_id), result)
                    continue
                if intent.kind == 'codex':
                    if intent.value not in CODEX_TASKS:
                        send_message(int(chat_id), '알 수 없는 Codex 작업입니다.')
                        continue
                    send_message(int(chat_id), f"Codex 분석을 실행합니다: {intent.value}")
                    result = run_codex_task(intent.value)
                    send_message(int(chat_id), result)
                    continue
                if intent.kind == 'gemini':
                    if intent.value not in GEMINI_TASKS:
                        send_message(int(chat_id), '알 수 없는 Gemini 작업입니다.')
                        continue
                    send_message(int(chat_id), f"Gemini 분석을 실행합니다: {intent.value}")
                    result = run_gemini_task(intent.value)
                    send_message(int(chat_id), result)
                    continue
                send_message(int(chat_id), '명령을 이해하지 못했습니다.\n\n' + help_message_ko())
        except Exception as exc:
            print(f'bridge error: {exc}', flush=True)
            time.sleep(5)


if __name__ == '__main__':
    raise SystemExit(main())
