import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


DEFAULT_GEMINI_CMD = "gemini.cmd"
DEFAULT_CLAUDE_CMD = "claude"
DEFAULT_CODEX_CMD = "codex"

ALL_PROVIDERS = ("gemini", "codex")

DEFAULT_GEMINI_MODELS = [
    "gemini-3.1-pro-preview",
    "gemini-3-pro-preview",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
]

DEFAULT_CLAUDE_MODELS = []


class CliCallError(RuntimeError):
    pass


def _load_env_file(path: Path, env: dict[str, str], override: bool = False) -> None:
    if not path.exists() or not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        if not key or not value:
            continue
        if override or key not in env:
            env[key] = value


def build_cli_env() -> dict[str, str]:
    env = dict(os.environ)
    root = Path(__file__).resolve().parent
    _load_env_file(root / ".env", env, override=False)
    # Force latest token from local file even if OS-level env has old value.
    _load_env_file(root / ".env.notion", env, override=True)
    _load_env_file(root / "notion_automation" / ".env.notion", env, override=True)
    return env


def run_cli(args: list[str], timeout: int, cli_env: dict[str, str]) -> str:
    proc: Optional[subprocess.Popen[str]] = None
    try:
        proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=cli_env,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        stdout, stderr = proc.communicate(timeout=timeout)
        if proc.returncode != 0:
            details = (stderr or "").strip() or (stdout or "").strip()
            raise CliCallError(f"Command failed: {' '.join(args)}\n{details}")
        return (stdout or "").strip()
    except subprocess.TimeoutExpired as exc:
        if proc is not None:
            terminate_process_tree(proc.pid)
            try:
                proc.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        raise CliCallError(f"Timeout: {' '.join(args)}") from exc


def terminate_process_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def require_command(command: str) -> None:
    if shutil.which(command) is None:
        raise CliCallError(f"Command not found: {command}")


def is_capacity_error(message: str) -> bool:
    text = message.lower()
    hints = (
        "no capacity available",
        "model_capacity_exhausted",
        "resource_exhausted",
        "ratelimitexceeded",
        "status 429",
        "code\": 429",
        "overloaded",
        "rate limit",
    )
    return any(hint in text for hint in hints)


def is_timeout_error(message: str) -> bool:
    return message.startswith("Timeout:")


def parse_csv_models(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def short_error_text(error: Exception, limit: int = 220) -> str:
    text = str(error).strip().splitlines()[0] if str(error).strip() else "unknown error"
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def parse_codex_jsonl(raw: str) -> str:
    messages: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "item.completed":
            continue
        item = event.get("item") or {}
        if item.get("type") == "agent_message":
            text = item.get("text") or ""
            if text:
                messages.append(text.strip())
    return "\n".join(messages).strip()


def parse_claude_json(raw: str) -> str:
    # Claude can output single-line JSON result in print/json mode.
    for line in reversed(raw.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "result":
            result = obj.get("result")
            if isinstance(result, str) and result.strip():
                return result.strip()
    return raw.strip()


def ask_gemini(
    prompt: str,
    gemini_cmd: str,
    timeout: int,
    gemini_models: list[str],
    cli_env: dict[str, str],
) -> str:
    last_error: Optional[Exception] = None
    models = gemini_models if gemini_models else [""]

    for model in models:
        args = [gemini_cmd]
        if model:
            args.extend(["--model", model])
        args.extend(["--prompt", prompt, "--output-format", "text"])

        try:
            output = run_cli(args, timeout=timeout, cli_env=cli_env)
            if not output:
                raise CliCallError("Gemini returned empty output.")
            if model:
                print(f"[GEMINI] selected model: {model}")
            return output
        except CliCallError as exc:
            last_error = exc
            err_text = str(exc)
            if model and (is_capacity_error(err_text) or is_timeout_error(err_text)):
                print(f"[GEMINI] model '{model}' failed. Trying next model.")
                continue
            raise

    if last_error is not None:
        raise CliCallError(str(last_error))
    raise CliCallError("Gemini failed without a specific error.")


def ask_claude(
    prompt: str,
    claude_cmd: str,
    timeout: int,
    claude_models: list[str],
    cli_env: dict[str, str],
) -> str:
    last_error: Optional[Exception] = None
    models = claude_models if claude_models else [""]

    for model in models:
        args = [claude_cmd, "--print", "--output-format", "json"]
        if model:
            args.extend(["--model", model])
        args.append(prompt)

        try:
            raw = run_cli(args, timeout=timeout, cli_env=cli_env)
            parsed = parse_claude_json(raw)
            if not parsed:
                raise CliCallError("Claude returned empty output.")
            if model:
                print(f"[CLAUDE] selected model: {model}")
            return parsed
        except CliCallError as exc:
            last_error = exc
            err_text = str(exc)
            if model and (is_capacity_error(err_text) or is_timeout_error(err_text)):
                print(f"[CLAUDE] model '{model}' failed. Trying next model.")
                continue
            raise

    if last_error is not None:
        raise CliCallError(str(last_error))
    raise CliCallError("Claude failed without a specific error.")


def ask_codex(
    prompt: str, codex_cmd: str, timeout: int, cli_env: dict[str, str]
) -> str:
    raw = run_cli(
        [codex_cmd, "exec", "--json", prompt], timeout=timeout, cli_env=cli_env
    )
    parsed = parse_codex_jsonl(raw)
    if parsed:
        return parsed
    if raw:
        return raw
    raise CliCallError("Codex returned empty output.")


def ask_provider_text(
    provider: str,
    prompt: str,
    gemini_cmd: str,
    gemini_models: list[str],
    claude_cmd: str,
    claude_models: list[str],
    codex_cmd: str,
    timeout: int,
    cli_env: dict[str, str],
) -> str:
    if provider == "gemini":
        return ask_gemini(prompt, gemini_cmd, timeout, gemini_models, cli_env)
    if provider == "claude":
        return ask_claude(prompt, claude_cmd, timeout, claude_models, cli_env)
    if provider == "codex":
        return ask_codex(prompt, codex_cmd, timeout, cli_env)
    raise CliCallError(f"Unsupported provider: {provider}")


def normalize_first_line(text: str) -> str:
    if not text.strip():
        return ""
    return text.strip().splitlines()[0].strip().upper()


def build_review_prompt(code: str) -> str:
    return (
        "Review the following Python code.\n"
        "If there is no issue, print PASS on the first line.\n"
        "If there are issues, print FIX on the first line and then provide reasons and a fixed code block.\n\n"
        f"{code}"
    )


def reviewers_for(starter: str) -> list[str]:
    return [provider for provider in ALL_PROVIDERS if provider != starter]


def autonomous_collaboration(
    user_goal: str,
    starter: str,
    gemini_cmd: str,
    gemini_models: list[str],
    claude_cmd: str,
    claude_models: list[str],
    codex_cmd: str,
    rounds: int,
    provider_timeout: int,
    cli_env: dict[str, str],
) -> str:
    print(f"[START] goal: {user_goal}")
    print(f"[STARTER] {starter}")

    current_code = ask_provider_text(
        provider=starter,
        prompt=f"Write Python code for this goal: {user_goal}. Output code only.",
        gemini_cmd=gemini_cmd,
        gemini_models=gemini_models,
        claude_cmd=claude_cmd,
        claude_models=claude_models,
        codex_cmd=codex_cmd,
        timeout=provider_timeout,
        cli_env=cli_env,
    )

    reviewers = reviewers_for(starter)

    for idx in range(1, rounds + 1):
        print(f"[ROUND] {idx}")
        combined_fixes: list[str] = []
        all_pass = True
        successful_reviews = 0

        for reviewer in reviewers:
            print(f"[REVIEW:{reviewer}] running")
            try:
                review_result = ask_provider_text(
                    provider=reviewer,
                    prompt=build_review_prompt(current_code),
                    gemini_cmd=gemini_cmd,
                    gemini_models=gemini_models,
                    claude_cmd=claude_cmd,
                    claude_models=claude_models,
                    codex_cmd=codex_cmd,
                    timeout=provider_timeout,
                    cli_env=cli_env,
                )
            except CliCallError as exc:
                print(f"[REVIEW:{reviewer}] unavailable: {short_error_text(exc)}")
                continue

            successful_reviews += 1
            decision = normalize_first_line(review_result)
            if decision == "PASS":
                print(f"[REVIEW:{reviewer}] PASS")
                continue

            all_pass = False
            combined_fixes.append(f"[{reviewer.upper()} REVIEW]\n{review_result}")
            print(f"[REVIEW:{reviewer}] FIX")

        if successful_reviews == 0:
            print("[DONE] no reviewer responded successfully; keeping current code")
            return current_code

        if all_pass:
            print("[DONE] all reviewers PASS")
            return current_code

        patch_prompt = (
            "Revise the code using all reviews below. Output runnable final code only.\n\n"
            f"[REVIEWS]\n{chr(10).join(combined_fixes)}\n\n"
            f"[CURRENT_CODE]\n{current_code}"
        )

        current_code = ask_provider_text(
            provider=starter,
            prompt=patch_prompt,
            gemini_cmd=gemini_cmd,
            gemini_models=gemini_models,
            claude_cmd=claude_cmd,
            claude_models=claude_models,
            codex_cmd=codex_cmd,
            timeout=provider_timeout,
            cli_env=cli_env,
        )

    print("[DONE] max rounds reached")
    return current_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gemini + Claude + Codex collaboration runner (login-session based)"
    )
    parser.add_argument("goal", help="Work goal")
    parser.add_argument(
        "--starter",
        default="gemini",
        choices=list(ALL_PROVIDERS),
        help="Which provider writes first. Other providers review each round.",
    )
    parser.add_argument("--gemini-cmd", default=DEFAULT_GEMINI_CMD)
    parser.add_argument(
        "--gemini-models",
        default=",".join(DEFAULT_GEMINI_MODELS),
        help="Comma-separated Gemini model fallback chain",
    )
    parser.add_argument("--claude-cmd", default=DEFAULT_CLAUDE_CMD)
    parser.add_argument(
        "--claude-models",
        default=",".join(DEFAULT_CLAUDE_MODELS),
        help="Comma-separated Claude model fallback chain",
    )
    parser.add_argument("--codex-cmd", default=DEFAULT_CODEX_CMD)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--out", default="", help="Path to save final code")
    args = parser.parse_args()

    try:
        require_command(args.gemini_cmd)
        # require_command(args.claude_cmd)
        require_command(args.codex_cmd)
        cli_env = build_cli_env()
        if cli_env.get("NOTION_TOKEN"):
            print("[NOTION] token loaded for provider subprocesses")

        final_code = autonomous_collaboration(
            user_goal=args.goal,
            starter=args.starter,
            gemini_cmd=args.gemini_cmd,
            gemini_models=parse_csv_models(args.gemini_models),
            claude_cmd=args.claude_cmd,
            claude_models=parse_csv_models(args.claude_models),
            codex_cmd=args.codex_cmd,
            rounds=max(1, args.rounds),
            provider_timeout=max(10, args.timeout),
            cli_env=cli_env,
        )
    except CliCallError as exc:
        print("\n[ERROR]")
        print(str(exc))
        print(
            "\nHint: Make sure all CLIs are logged in first.\n"
            "  - gemini.cmd\n"
            "  - claude auth\n"
            "  - codex login status"
        )
        return 1

    print("\n[RESULT]\n")
    print(final_code)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(final_code)
        print(f"\n[SAVED] {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
