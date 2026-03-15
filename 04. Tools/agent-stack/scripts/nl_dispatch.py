#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from nl_route import REGISTRY_PATH, MANIFEST_PATH, classify_request, load_manifest, load_registry


SCRIPT_PATH = Path(__file__).resolve()
AGENT_STACK_ROOT = SCRIPT_PATH.parents[1]
WRAPPER_PATH = AGENT_STACK_ROOT / "scripts" / "codex_agent_stack.sh"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify a natural-language request and either print a compact local plan or dispatch it to Codex."
    )
    parser.add_argument("request", help="Natural-language request to classify.")
    parser.add_argument(
        "--run",
        action="store_true",
        help="Execute the wrapper for delegate routes. Default is dry-run.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="text",
        help="Output format.",
    )
    return parser.parse_args(argv)


def pick_repo(recommended_repos: list[dict]) -> dict | None:
    for repo in recommended_repos:
        if repo.get("exists") and repo.get("local_path"):
            return repo
    for repo in recommended_repos:
        if repo.get("local_path"):
            return repo
    return recommended_repos[0] if recommended_repos else None


def build_wrapper_command(repo_id: str, request: str) -> list[str]:
    return [str(WRAPPER_PATH), repo_id, request]


def direct_action_plan(route_result: dict) -> list[str]:
    plan = []

    available_skills = [skill["id"] for skill in route_result["recommended_skills"] if skill["exists"]]
    if available_skills:
        plan.append(f"Use skill {available_skills[0]}.")

    available_repos = [repo["id"] for repo in route_result["recommended_repos"] if repo.get("exists")]
    if available_repos:
        plan.append(f"Use repo {available_repos[0]} only if deeper reference is needed.")

    plan.append(f"Next action: {route_result['execution_path']}")

    if route_result["intent_id"] == "unclassified":
        plan.append("If this pattern repeats, add a dedicated route to the registry.")

    return plan


def build_dispatch_result(route_result: dict, run_requested: bool) -> dict:
    selected_repo = None
    command = None
    can_delegate = False
    status = "direct-plan"
    note = None
    action_plan = None
    wrapper_ready = WRAPPER_PATH.is_file() and os.access(WRAPPER_PATH, os.X_OK)

    if route_result["delegate_to_codex"]:
        selected_repo = pick_repo(route_result["recommended_repos"])
        if selected_repo and selected_repo.get("local_path"):
            command = build_wrapper_command(selected_repo["id"], route_result["request"])
            if not selected_repo.get("exists", False):
                status = "repo-missing"
                note = f"Selected repo '{selected_repo['id']}' is not available locally."
            elif not wrapper_ready:
                status = "wrapper-missing"
                note = f"Wrapper is not executable: {WRAPPER_PATH}"
            else:
                can_delegate = True
                status = "ready-to-run"
        else:
            status = "no-repo"
            note = "No recommended repo could be mapped to a local checkout."
    else:
        action_plan = direct_action_plan(route_result)

    will_execute = bool(run_requested and can_delegate and command)
    if route_result["delegate_to_codex"] and run_requested and not will_execute and note is None:
        note = "Run mode requested, but delegation could not proceed."

    return {
        "mode": "run" if run_requested else "dry-run",
        "decision": "delegate" if route_result["delegate_to_codex"] else "direct",
        "status": status,
        "route": route_result,
        "selected_repo": selected_repo,
        "selected_repo_path": selected_repo.get("local_path") if selected_repo else None,
        "command": command,
        "command_text": shlex.join(command) if command else None,
        "will_run": will_execute,
        "action_plan": action_plan,
        "note": note,
    }


def format_text(dispatch_result: dict) -> str:
    route_result = dispatch_result["route"]
    lines = [
        f"intent_id: {route_result['intent_id']}",
        f"summary: {route_result['summary']}",
        f"dispatch_mode: {dispatch_result['decision']}",
        f"mode: {dispatch_result['mode']}",
        f"status: {dispatch_result['status']}",
    ]

    if dispatch_result["selected_repo"]:
        repo = dispatch_result["selected_repo"]
        lines.append(f"selected_repo: {repo['id']} ({repo.get('local_path')}, exists={str(repo.get('exists', False)).lower()})")

    if dispatch_result["command_text"]:
        command_label = "running_command" if dispatch_result["will_run"] else "would_run"
        lines.append(f"{command_label}: {dispatch_result['command_text']}")

    if dispatch_result["action_plan"]:
        lines.append("action_plan:")
        lines.extend(f"- {step}" for step in dispatch_result["action_plan"])

    if route_result["why_it_matched"]:
        lines.append("why_it_matched:")
        lines.extend(f"- {item}" for item in route_result["why_it_matched"])

    if dispatch_result["note"]:
        lines.append(f"note: {dispatch_result['note']}")

    return "\n".join(lines)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    routes = load_registry(REGISTRY_PATH)
    manifest = load_manifest(MANIFEST_PATH)
    route_result = classify_request(args.request, routes, manifest)
    dispatch_result = build_dispatch_result(route_result, args.run)

    if dispatch_result["will_run"]:
        if args.format == "json":
            completed = subprocess.run(
                dispatch_result["command"],
                capture_output=True,
                text=True,
            )
            dispatch_result["exit_code"] = completed.returncode
            dispatch_result["stdout"] = completed.stdout
            dispatch_result["stderr"] = completed.stderr
            print(json.dumps(dispatch_result, indent=2, ensure_ascii=False))
            return completed.returncode

        print(format_text(dispatch_result))
        completed = subprocess.run(dispatch_result["command"])
        return completed.returncode

    if args.format == "json":
        print(json.dumps(dispatch_result, indent=2, ensure_ascii=False))
    else:
        print(format_text(dispatch_result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
