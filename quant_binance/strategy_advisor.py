from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_binance.execution_quality_report import build_execution_quality_report
from quant_binance.macro_event_calendar import OfficialMacroEvent, fetch_official_macro_events
from quant_binance.overlays import load_macro_inputs
from quant_binance.performance_report import build_runtime_performance_report
from quant_binance.telegram_notify import send_telegram_message
from quant_binance.validation_report import build_weekly_validation_report


ROOT = Path("/Users/tttksj/first_repo")


@dataclass(frozen=True)
class MacroEventWindow:
    name: str
    start: str
    end: str = ""
    impact: str = "medium"
    summary_ko: str = ""
    strategy_hint_ko: str = ""
    assets: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReferenceDocument:
    path: str
    excerpt: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class StrategyAdvisorContext:
    generated_at: str
    base_dir: str
    latest_run_dir: str
    strategy_profile: str
    approved_override: dict[str, Any]
    pending_override: dict[str, Any]
    overview: dict[str, Any]
    summary: dict[str, Any]
    state: dict[str, Any]
    performance_report: dict[str, Any]
    validation_report: dict[str, Any]
    execution_quality_report: dict[str, Any]
    macro_inputs: dict[str, Any] | None
    macro_event_windows: tuple[MacroEventWindow, ...]
    official_macro_events: tuple[OfficialMacroEvent, ...]
    reference_documents: tuple[ReferenceDocument, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "base_dir": self.base_dir,
            "latest_run_dir": self.latest_run_dir,
            "strategy_profile": self.strategy_profile,
            "approved_override": self.approved_override,
            "pending_override": self.pending_override,
            "overview": self.overview,
            "summary": self.summary,
            "state": self.state,
            "performance_report": self.performance_report,
            "validation_report": self.validation_report,
            "execution_quality_report": self.execution_quality_report,
            "macro_inputs": self.macro_inputs,
            "macro_event_windows": [item.as_dict() for item in self.macro_event_windows],
            "official_macro_events": [item.as_dict() for item in self.official_macro_events],
            "reference_documents": [item.as_dict() for item in self.reference_documents],
        }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_env_file_value(name: str) -> str:
    direct = os.environ.get(name, "").strip()
    if direct:
        return direct
    for candidate in (ROOT / ".env", ROOT / ".env.local"):
        if not candidate.exists():
            continue
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip().strip('"').strip("'")
    return ""


def _load_latest_jsonl_rows(path: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows[-limit:]


def _resolve_latest_run_dir(base_dir: Path) -> Path:
    latest = base_dir / "output" / "paper-live-shell" / "latest"
    if latest.exists():
        return latest
    mode_root = base_dir / "output" / "paper-live-shell"
    runs = sorted([p for p in mode_root.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
    if not runs:
        raise FileNotFoundError(f"no live runtime runs found under {mode_root}")
    return runs[0]


def _macro_event_windows_from_payload(payload: dict[str, Any]) -> tuple[MacroEventWindow, ...]:
    rows: list[MacroEventWindow] = []
    for item in payload.get("events", []) or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            MacroEventWindow(
                name=str(item.get("name", "")),
                start=str(item.get("start", "")),
                end=str(item.get("end", "")),
                impact=str(item.get("impact", "medium")),
                summary_ko=str(item.get("summary_ko", "")),
                strategy_hint_ko=str(item.get("strategy_hint_ko", "")),
                assets=tuple(str(asset) for asset in (item.get("assets") or [])),
            )
        )
    return tuple(rows)


def load_macro_event_windows() -> tuple[MacroEventWindow, ...]:
    path_value = _load_env_file_value("MACRO_STRATEGY_EVENTS_PATH")
    json_value = _load_env_file_value("MACRO_STRATEGY_EVENTS_JSON")
    payload: dict[str, Any] | None = None
    if json_value:
        payload = json.loads(json_value)
    elif path_value:
        payload = json.loads(Path(path_value).read_text(encoding="utf-8"))
    if payload is None:
        return ()
    return _macro_event_windows_from_payload(payload)


def _reference_paths() -> list[Path]:
    raw = _load_env_file_value("STRATEGY_ADVISOR_REFERENCE_PATHS")
    paths: list[Path] = []
    if raw:
        for item in raw.split(","):
            candidate = Path(item.strip())
            if candidate.exists():
                paths.append(candidate)
    default_openclaw = ROOT / "quant_runtime" / "artifacts" / "openclaw_naver_strategy.md"
    if default_openclaw.exists():
        paths.append(default_openclaw)
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve())
        if key in seen:
            continue
        deduped.append(path)
        seen.add(key)
    return deduped


def load_reference_documents(*, max_chars_per_file: int = 6000) -> tuple[ReferenceDocument, ...]:
    rows: list[ReferenceDocument] = []
    for path in _reference_paths():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        excerpt = text[:max_chars_per_file].strip()
        if not excerpt:
            continue
        rows.append(ReferenceDocument(path=str(path.resolve()), excerpt=excerpt))
    return tuple(rows)


def build_strategy_advisor_context(
    *,
    base_dir: str | Path = "quant_runtime",
    lookback_days: int = 7,
) -> StrategyAdvisorContext:
    base = Path(base_dir)
    latest_run_dir = _resolve_latest_run_dir(base)
    summary = _load_json(latest_run_dir / "summary.json")
    state = _load_json(latest_run_dir / "summary.state.json")
    overview = _load_json(latest_run_dir / "overview.json")
    performance = build_runtime_performance_report(run_dir=latest_run_dir).as_dict()
    validation = build_weekly_validation_report(base_dir=base, lookback_days=lookback_days).as_dict()
    execution_quality = build_execution_quality_report(base_dir=base, lookback_days=lookback_days).as_dict()
    approved_override = _load_json(base / "artifacts" / "strategy_override.approved.json")
    pending_override = _load_json(base / "artifacts" / "strategy_override.pending.json")
    macro_inputs = load_macro_inputs()

    summary.setdefault("recent_live_orders", _load_latest_jsonl_rows(latest_run_dir / "logs" / "live_orders.jsonl", limit=5))
    summary.setdefault("recent_order_errors", _load_latest_jsonl_rows(latest_run_dir / "logs" / "order_errors.jsonl", limit=5))
    summary.setdefault("recent_closed_trades", _load_latest_jsonl_rows(latest_run_dir / "logs" / "closed_trades.jsonl", limit=5))
    summary.setdefault("recent_decision_rows", _load_latest_jsonl_rows(latest_run_dir / "logs" / "decisions.jsonl", limit=25))

    return StrategyAdvisorContext(
        generated_at=datetime.now(UTC).isoformat(),
        base_dir=str(base.resolve()),
        latest_run_dir=str(latest_run_dir.resolve()),
        strategy_profile=str(approved_override.get("strategy_profile") or _load_env_file_value("STRATEGY_PROFILE") or "live-ultra-aggressive"),
        approved_override=approved_override,
        pending_override=pending_override,
        overview=overview,
        summary=summary,
        state=state,
        performance_report=performance,
        validation_report=validation,
        execution_quality_report=execution_quality,
        macro_inputs=asdict(macro_inputs) if macro_inputs is not None else None,
        macro_event_windows=load_macro_event_windows(),
        official_macro_events=fetch_official_macro_events(),
        reference_documents=load_reference_documents(),
    )


def strategy_advisor_artifact_paths(base_dir: str | Path = "quant_runtime") -> dict[str, Path]:
    root = Path(base_dir) / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    return {
        "context": root / "strategy_advisor.context.json",
        "prompt": root / "strategy_advisor.prompt.md",
        "latest": root / "strategy_advisor.latest.md",
        "summary": root / "strategy_advisor.summary.txt",
    }


def write_strategy_advisor_context(
    *,
    context: StrategyAdvisorContext,
    base_dir: str | Path = "quant_runtime",
) -> dict[str, Path]:
    paths = strategy_advisor_artifact_paths(base_dir)
    paths["context"].write_text(json.dumps(context.as_dict(), indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    return paths


def build_strategy_advisor_prompt(
    *,
    context_path: str | Path,
    mode: str = "advisor",
) -> str:
    path = Path(context_path).resolve()
    return (
        "당신은 실거래 자동매매 엔진을 직접 수정하지 않는 상위 전략 자문가입니다.\n"
        "반드시 한국어로만 답하고, 수익성 중심으로 분석하세요.\n"
        "중요: 전략을 자동 적용하라고 지시하지 말고 제안만 하세요.\n"
        f"읽어야 할 핵심 컨텍스트 파일: {path}\n"
        "이 파일에는 최신 런타임 상태, 성과 리포트, 실행 품질, 현재 override, 거시 입력, 거시 이벤트 윈도우, 공식 거시 일정, 참고문서가 들어 있습니다.\n"
        "참고문서가 있으면 그 내용도 함께 반영하세요.\n"
        "\n"
        "리포트 작성 원칙:\n"
        "1. 수익성 중심으로 판단할 것\n"
        "2. 메이저 코인은 거시 이벤트와 유동성 환경을 반드시 함께 해석할 것\n"
        "3. '언제까지는 이런 전략, 이후에는 기존 전략 복귀'처럼 시간 구간을 제시할 것\n"
        "4. 확실하지 않은 부분은 불확실성으로 명시할 것\n"
        "5. 직접 전략 변경 대신 pending override 아이디어 수준으로만 제안할 것\n"
        "\n"
        "필수 섹션:\n"
        "1. 현재 시장 요약\n"
        "2. 주요 거시 이벤트와 영향 기간\n"
        "3. 현재 전략 적합성 평가\n"
        "4. 수익성 기준 우선 관찰/투자 후보 코인 3~5개\n"
        "5. 현재 기간 전략 제안\n"
        "6. 그 이후 기간 전략 제안\n"
        "7. 지금 당장 건드리지 말아야 할 것\n"
        "8. 다음 개선 후보 3개\n"
        "\n"
        "형식:\n"
        "- 제목 포함 한국어 전략 리포트\n"
        "- 과도하게 길지 않게, 하지만 실행 판단에 필요한 근거는 남길 것\n"
        "- 필요한 경우 날짜/시간을 명시할 것\n"
        f"- 모드는 {mode}이며, mode가 suggestion이면 맨 끝에 'pending override 아이디어'를 짧게 추가할 것\n"
    )


def run_strategy_advisor_provider(
    *,
    provider: str,
    prompt: str,
    root: str | Path = ROOT,
) -> str:
    workspace_root = Path(root).resolve()
    if provider == "prepare":
        return "전략 자문 리포트 컨텍스트와 프롬프트를 준비했습니다. 실제 분석은 Codex/Gemini 실행 시 생성됩니다."
    if provider == "codex":
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            output_path = Path(handle.name)
        try:
            subprocess.run(
                ["./codex", "exec", "-C", str(workspace_root), "-o", str(output_path), prompt],
                cwd=workspace_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=300,
            )
            return output_path.read_text(encoding="utf-8").strip() or "전략 자문 리포트를 생성하지 못했습니다."
        finally:
            output_path.unlink(missing_ok=True)
    if provider == "gemini":
        proc = subprocess.run(
            ["gemini", "-p", prompt, "--output-format", "text"],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        output = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()
        return output or "Gemini 전략 자문 리포트를 생성하지 못했습니다."
    raise ValueError(f"unsupported provider: {provider}")


def summarize_strategy_advisor_report(report_text: str, *, max_chars: int = 1800) -> str:
    lines = [line.rstrip() for line in report_text.strip().splitlines() if line.strip()]
    if not lines:
        return "전략 자문 리포트가 비어 있습니다."
    selected: list[str] = []
    total = 0
    for line in lines:
        candidate_total = total + len(line) + 1
        if candidate_total > max_chars:
            break
        selected.append(line)
        total = candidate_total
    if not selected:
        return report_text[:max_chars]
    return "\n".join(selected)


def generate_strategy_advisor_report(
    *,
    base_dir: str | Path = "quant_runtime",
    provider: str = "codex",
    mode: str = "advisor",
    lookback_days: int = 7,
    send_telegram: bool = False,
) -> dict[str, Any]:
    context = build_strategy_advisor_context(base_dir=base_dir, lookback_days=lookback_days)
    paths = write_strategy_advisor_context(context=context, base_dir=base_dir)
    prompt = build_strategy_advisor_prompt(context_path=paths["context"], mode=mode)
    paths["prompt"].write_text(prompt, encoding="utf-8")
    report = run_strategy_advisor_provider(provider=provider, prompt=prompt, root=ROOT)
    paths["latest"].write_text(report, encoding="utf-8")
    summary = summarize_strategy_advisor_report(report)
    paths["summary"].write_text(summary, encoding="utf-8")
    telegram_result: dict[str, Any] | None = None
    if send_telegram:
        telegram_result = send_telegram_message(summary)
    return {
        "provider": provider,
        "mode": mode,
        "context_path": str(paths["context"]),
        "prompt_path": str(paths["prompt"]),
        "report_path": str(paths["latest"]),
        "summary_path": str(paths["summary"]),
        "telegram": telegram_result,
    }
