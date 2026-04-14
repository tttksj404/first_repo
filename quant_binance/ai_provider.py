from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


PROVIDER_ALIASES = {
    "openai": "codex",
    "openai-codex": "codex",
    "google": "gemini",
    "anthropic": "claude",
}

SUPPORTED_PROVIDERS = ("codex", "gemini", "claude", "prepare")
CLAUDE_BIN = Path.home() / ".local" / "bin" / "claude"


def provider_choices() -> tuple[str, ...]:
    return SUPPORTED_PROVIDERS


def normalize_provider(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if not normalized:
        return "codex"
    return PROVIDER_ALIASES.get(normalized, normalized)


def build_provider_command(
    *,
    provider: str,
    prompt: str,
    workspace_root: str | Path,
    model: str | None = None,
    output_path: str | Path | None = None,
) -> list[str]:
    normalized = normalize_provider(provider)
    root = Path(workspace_root).resolve()
    if normalized == "codex":
        if output_path is None:
            raise ValueError("codex provider requires output_path")
        cmd = ["codex", "exec", "-C", str(root), "-o", str(Path(output_path).resolve())]
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)
        return cmd
    if normalized == "gemini":
        cmd = ["gemini"]
        if model:
            cmd.extend(["--model", model])
        cmd.extend(["--prompt", prompt, "--output-format", "text"])
        return cmd
    if normalized == "claude":
        cmd = [
            str(CLAUDE_BIN),
            "--print",
            "--output-format",
            "text",
            "--dangerously-skip-permissions",
            "--no-session-persistence",
        ]
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)
        return cmd
    if normalized == "prepare":
        return []
    raise ValueError(f"unsupported provider: {provider}")


def run_provider_prompt(
    *,
    provider: str,
    prompt: str,
    root: str | Path,
    model: str | None = None,
    timeout: int = 300,
) -> str:
    normalized = normalize_provider(provider)
    workspace_root = Path(root).resolve()
    if normalized == "prepare":
        return "전략 자문 리포트 컨텍스트와 프롬프트를 준비했습니다. 실제 분석은 Codex/Gemini/Claude 실행 시 생성됩니다."
    if normalized == "codex":
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            output_path = Path(handle.name)
        try:
            cmd = build_provider_command(
                provider=normalized,
                prompt=prompt,
                workspace_root=workspace_root,
                model=model,
                output_path=output_path,
            )
            subprocess.run(
                cmd,
                cwd=workspace_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=timeout,
            )
            return output_path.read_text(encoding="utf-8").strip() or "Codex가 응답을 생성하지 못했습니다."
        finally:
            output_path.unlink(missing_ok=True)
    env = os.environ.copy()
    if normalized == "claude":
        env.pop("CLAUDECODE", None)
        env["PATH"] = f"{CLAUDE_BIN.parent}:{env.get('PATH', '/usr/bin:/bin')}"
    cmd = build_provider_command(
        provider=normalized,
        prompt=prompt,
        workspace_root=workspace_root,
        model=model,
    )
    proc = subprocess.run(
        cmd,
        cwd=workspace_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout,
    )
    output = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()
    if output:
        return output
    provider_label = normalized.capitalize()
    return f"{provider_label}가 응답을 생성하지 못했습니다."
