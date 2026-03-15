#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from typing import Any

from bridge_lib import SpecError, load_json_input, print_json, run_provider_task


TEMPLATE_PATTERN = re.compile(r"{{\s*([^{}]+?)\s*}}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an inspectable serial provider sequence with template substitution.",
    )
    parser.add_argument("--spec", help="Inline JSON sequence spec.")
    parser.add_argument("--spec-file", help="Path to a JSON sequence spec.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser.parse_args()


def resolve_path(context: dict[str, Any], expression: str) -> Any:
    parts = [part for part in expression.split(".") if part]
    if not parts:
        raise KeyError("Empty template expression.")

    value: Any = context
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
            continue
        raise KeyError(expression)
    return value


def stringify_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=True)


def render_template(template: str, context: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        value = resolve_path(context, expression)
        return stringify_value(value)

    return TEMPLATE_PATTERN.sub(replace, template)


def resolve_step_value(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str) and "{{" in value and "}}" in value:
        return render_template(value, context)
    return value


def normalize_sequence_spec(spec: Any) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise SpecError("Sequence spec must be a JSON object.")
    steps = spec.get("steps")
    if not isinstance(steps, list) or not steps:
        raise SpecError("Sequence spec must include a non-empty 'steps' array.")
    seen_ids: set[str] = set()
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise SpecError(f"Step {index} must be a JSON object.")
        step_id = step.get("id")
        if not isinstance(step_id, str) or not step_id.strip():
            raise SpecError(f"Step {index} must include a non-empty string 'id'.")
        if step_id in seen_ids:
            raise SpecError(f"Duplicate step id '{step_id}' is not allowed.")
        seen_ids.add(step_id)
    return spec


def run_sequence(spec: dict[str, Any]) -> dict[str, Any]:
    sequence = normalize_sequence_spec(spec)
    defaults = sequence.get("defaults") if isinstance(sequence.get("defaults"), dict) else {}
    sequence_input = sequence.get("input") if isinstance(sequence.get("input"), dict) else {}
    continue_on_error = bool(sequence.get("continue_on_error", False))

    step_results: list[dict[str, Any]] = []
    step_results_by_id: dict[str, dict[str, Any]] = {}
    last_result: dict[str, Any] | None = None
    stopped_at: str | None = None

    for raw_step in sequence["steps"]:
        context = {
            "defaults": defaults,
            "input": sequence_input,
            "steps": step_results_by_id,
            "last": last_result or {},
        }
        resolved_step = dict(defaults)
        resolved_step.update(raw_step)
        task_spec = dict(resolved_step)
        for key in ("provider", "cwd", "prompt", "model", "output_path"):
            if key in task_spec:
                try:
                    task_spec[key] = resolve_step_value(task_spec[key], context)
                except KeyError as exc:
                    raise SpecError(
                        f"Step '{raw_step['id']}' references missing template value '{exc.args[0]}'."
                    ) from exc

        result = run_provider_task(task_spec)
        result["step_id"] = raw_step["id"]
        if "node_type" in raw_step:
            result["node_type"] = raw_step["node_type"]
        if "label" in raw_step:
            result["label"] = raw_step["label"]

        step_results.append(result)
        step_results_by_id[raw_step["id"]] = result
        last_result = result

        if result["exit_code"] != 0 and not continue_on_error:
            stopped_at = raw_step["id"]
            break

    ok = all(item["exit_code"] == 0 for item in step_results)
    if stopped_at is None and len(step_results) != len(sequence["steps"]):
        stopped_at = sequence["steps"][len(step_results)]["id"]

    return {
        "ok": ok,
        "continue_on_error": continue_on_error,
        "requested_steps": len(sequence["steps"]),
        "completed_steps": len(step_results),
        "stopped_at": stopped_at,
        "steps": step_results,
        "steps_by_id": step_results_by_id,
    }


def main() -> int:
    args = parse_args()
    try:
        spec = load_json_input(args.spec, args.spec_file)
        result = run_sequence(spec)
    except SpecError as exc:
        print_json({"ok": False, "error": str(exc)}, pretty=args.pretty)
        return 2
    except Exception as exc:  # pragma: no cover - defensive shell bridge guard.
        print_json({"ok": False, "error": f"Unexpected bridge failure: {exc}"}, pretty=args.pretty)
        return 3

    print_json(result, pretty=args.pretty)
    if result["ok"]:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
