from __future__ import annotations

from dataclasses import dataclass


LOCAL_COMMAND_ALIASES = {
    "start": {"/start", "start", "시작", "실행", "돌려", "가동", "프로그램 시작", "봇 시작", "paper 시작"},
    "start-live": {
        "/startlive",
        "startlive",
        "실주문 시작",
        "실전 시작",
        "라이브 시작",
        "실주문 돌려",
        "실주문 실행",
        "자동매매 시작",
        "라이브 트레이딩 시작",
    },
    "status": {"/status", "status", "상태", "상태 알려줘", "지금 상태", "돌아가?", "살아있어?", "실행중이야?"},
    "report": {"/report", "report", "리포트", "보고", "결과", "요약", "투자 결과", "리포트 보여줘"},
    "stop": {"/stop", "stop", "중지", "정지", "멈춰", "그만", "꺼", "종료"},
    "smoke": {"/smoke", "smoke", "스모크", "점검", "체크", "전체 점검", "스모크 돌려"},
    "extract": {"/extract", "extract", "추출", "크롤링", "본문 추출", "사이트 크롤링", "자료 긁어와"},
}

CODEX_TASK_ALIASES = {
    "status-check": {"상태 분석", "실행 상태 분석", "런 상태 분석", "codex status", "status-check"},
    "capital-report": {"자본 보고", "자본 리포트", "잔고 분석", "capital-report", "capital report"},
    "latest-run-review": {"최근 실행 검토", "최신 실행 검토", "latest-run-review", "run review"},
    "strategy-review": {"전략 검토", "전략 분석", "strategy-review", "strategy review"},
}
GEMINI_TASK_ALIASES = {
    "status-check": {"제미나이 상태 분석", "gemini status", "gemini status-check"},
    "capital-report": {"제미나이 자본 리포트", "gemini capital", "gemini capital-report"},
    "latest-run-review": {"제미나이 최근 실행 검토", "gemini latest-run-review", "gemini run review"},
    "strategy-review": {"제미나이 전략 검토", "gemini strategy", "gemini strategy-review"},
}


@dataclass(frozen=True)
class ParsedIntent:
    kind: str
    value: str


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def parse_telegram_intent(text: str) -> ParsedIntent:
    normalized = _normalize(text)
    if not normalized:
        return ParsedIntent(kind="unknown", value="")

    prefer_gemini = "gemini" in normalized or "제미나이" in normalized
    prefer_codex = "codex" in normalized or "코덱스" in normalized

    if normalized.startswith("/codex"):
        parts = normalized.split()
        if len(parts) >= 2:
            task = parts[1]
            if task in CODEX_TASK_ALIASES:
                return ParsedIntent(kind="codex", value=task)
        return ParsedIntent(kind="unknown", value="")

    if normalized.startswith("/gemini"):
        parts = normalized.split()
        if len(parts) >= 2:
            task = parts[1]
            if task in GEMINI_TASK_ALIASES:
                return ParsedIntent(kind="gemini", value=task)
        return ParsedIntent(kind="unknown", value="")

    local_items = sorted(
        LOCAL_COMMAND_ALIASES.items(),
        key=lambda item: max(len(alias) for alias in item[1]),
        reverse=True,
    )
    for action, aliases in local_items:
        if normalized in aliases:
            return ParsedIntent(kind="local", value=action)
        if any(alias in normalized for alias in aliases if len(alias) > 1):
            return ParsedIntent(kind="local", value=action)

    codex_items = sorted(
        CODEX_TASK_ALIASES.items(),
        key=lambda item: max(len(alias) for alias in item[1]),
        reverse=True,
    )
    gemini_items = sorted(
        GEMINI_TASK_ALIASES.items(),
        key=lambda item: max(len(alias) for alias in item[1]),
        reverse=True,
    )

    if prefer_gemini:
        for task, aliases in gemini_items:
            if normalized in aliases:
                return ParsedIntent(kind="gemini", value=task)
            if any(alias in normalized for alias in aliases if len(alias) > 2):
                return ParsedIntent(kind="gemini", value=task)
    if prefer_codex:
        for task, aliases in codex_items:
            if normalized in aliases:
                return ParsedIntent(kind="codex", value=task)
            if any(alias in normalized for alias in aliases if len(alias) > 2):
                return ParsedIntent(kind="codex", value=task)
    for task, aliases in codex_items:
        if normalized in aliases:
            return ParsedIntent(kind="codex", value=task)
        if any(alias in normalized for alias in aliases if len(alias) > 2):
            return ParsedIntent(kind="codex", value=task)
    for task, aliases in gemini_items:
        if normalized in aliases:
            return ParsedIntent(kind="gemini", value=task)
        if any(alias in normalized for alias in aliases if len(alias) > 2):
            return ParsedIntent(kind="gemini", value=task)

    return ParsedIntent(kind="unknown", value="")


def help_message_ko() -> str:
    return (
        "가능한 명령:\n"
        "- /status 또는 '지금 상태 알려줘'\n"
        "- /report 또는 '리포트 보여줘'\n"
        "- /start 또는 '시작해'\n"
        "- /startlive 또는 '실주문 시작해'\n"
        "- /stop 또는 '멈춰'\n"
        "- /smoke 또는 '스모크 점검해'\n"
        "- /extract 또는 '사이트 크롤링해'\n"
        "- /codex status-check\n"
        "- /codex capital-report\n"
        "- /codex latest-run-review\n"
        "- /codex strategy-review\n"
        "- /gemini status-check\n"
        "- /gemini capital-report\n"
        "- /gemini latest-run-review\n"
        "- /gemini strategy-review\n"
        "- 또는 '전략 검토해줘', '자본 리포트 보여줘' 같은 한국어 자연어"
    )
