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
