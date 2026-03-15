#!/usr/bin/env python3
from __future__ import annotations

import json
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BRIDGE_SCRIPTS_DIR = Path(__file__).resolve().parent
BRIDGE_ROOT = BRIDGE_SCRIPTS_DIR.parent
AGENT_STACK_ROOT = BRIDGE_ROOT.parent
TOOLS_ROOT = AGENT_STACK_ROOT.parent
REPO_ROOT = TOOLS_ROOT.parent

WRAPPER_BY_PROVIDER = {
    "codex": REPO_ROOT / "scripts" / "delegate_to_codex.sh",
    "gemini": REPO_ROOT / "scripts" / "delegate_to_gemini.sh",
}


class SpecError(ValueError):
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)
        handle.write("\n")


def load_json_input(spec_text: str | None, spec_file: str | None) -> Any:
    if bool(spec_text) == bool(spec_file):
        raise SpecError("Provide exactly one of --spec or --spec-file.")
    if spec_text:
        try:
            return json.loads(spec_text)
        except json.JSONDecodeError as exc:
            raise SpecError(f"Invalid inline JSON: {exc}") from exc
    assert spec_file is not None
    path = Path(spec_file).expanduser()
    if not path.is_file():
        raise SpecError(f"Spec file not found: {path}")
    try:
        return read_json_file(path)
    except json.JSONDecodeError as exc:
        raise SpecError(f"Invalid JSON file {path}: {exc}") from exc


def normalize_cwd(raw_cwd: Any) -> str:
    if not isinstance(raw_cwd, str) or not raw_cwd.strip():
        raise SpecError("Task spec must include a non-empty string 'cwd'.")
    cwd_path = Path(raw_cwd).expanduser()
    if not cwd_path.is_absolute():
        cwd_path = (REPO_ROOT / cwd_path).resolve()
    if not cwd_path.is_dir():
        raise SpecError(f"cwd does not exist: {cwd_path}")
    return str(cwd_path)


def normalize_task_spec(spec: Any) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise SpecError("Task spec must be a JSON object.")
    provider = spec.get("provider")
    if provider not in WRAPPER_BY_PROVIDER:
        allowed = ", ".join(sorted(WRAPPER_BY_PROVIDER))
        raise SpecError(f"Unsupported provider '{provider}'. Expected one of: {allowed}.")
    prompt = spec.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise SpecError("Task spec must include a non-empty string 'prompt'.")
    model = spec.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise SpecError("'model' must be a non-empty string when provided.")
    json_mode = spec.get("json", False)
    if not isinstance(json_mode, bool):
        raise SpecError("'json' must be a boolean when provided.")
    output_path = spec.get("output_path")
    if output_path is not None and (not isinstance(output_path, str) or not output_path.strip()):
        raise SpecError("'output_path' must be a non-empty string when provided.")

    normalized = dict(spec)
    normalized["provider"] = provider
    normalized["cwd"] = normalize_cwd(spec.get("cwd"))
    normalized["prompt"] = prompt
    normalized["model"] = model.strip() if isinstance(model, str) else None
    normalized["json"] = json_mode
    normalized["output_path"] = output_path.strip() if isinstance(output_path, str) else None
    return normalized


def build_provider_command(task_spec: dict[str, Any]) -> list[str]:
    wrapper = WRAPPER_BY_PROVIDER[task_spec["provider"]]
    if not wrapper.is_file():
        raise SpecError(f"Wrapper not found for provider '{task_spec['provider']}': {wrapper}")

    command = [str(wrapper), "--cwd", task_spec["cwd"]]
    if task_spec.get("model"):
        command.extend(["--model", task_spec["model"]])
    if task_spec.get("json"):
        command.append("--json")
    command.extend(["--", task_spec["prompt"]])
    return command


def maybe_parse_json(text: str) -> tuple[Any | None, str | None]:
    stripped = text.strip()
    if not stripped:
        return None, None
    try:
        return json.loads(stripped), None
    except json.JSONDecodeError as exc:
        return None, str(exc)


def run_provider_task(task_spec: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_task_spec(task_spec)
    command = build_provider_command(normalized)
    started_at = utc_now_iso()

    completed = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    completed_at = utc_now_iso()
    parsed_output, parse_error = maybe_parse_json(completed.stdout) if normalized["json"] else (None, None)
    result = {
        "ok": completed.returncode == 0,
        "provider": normalized["provider"],
        "cwd": normalized["cwd"],
        "prompt": normalized["prompt"],
        "model": normalized["model"],
        "json_mode": normalized["json"],
        "output_path": normalized["output_path"],
        "command": command,
        "command_text": shlex.join(command),
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "parsed_output": parsed_output,
        "parse_error": parse_error,
        "started_at": started_at,
        "completed_at": completed_at,
    }

    if normalized["output_path"]:
        output_path = Path(normalized["output_path"]).expanduser()
        if not output_path.is_absolute():
            output_path = (Path(normalized["cwd"]) / output_path).resolve()
        write_json_file(output_path, result)
        result["output_path"] = str(output_path)

    return result


def print_json(payload: Any, pretty: bool = False) -> None:
    json.dump(payload, sys.stdout, indent=2 if pretty else None, ensure_ascii=True)
    sys.stdout.write("\n")
