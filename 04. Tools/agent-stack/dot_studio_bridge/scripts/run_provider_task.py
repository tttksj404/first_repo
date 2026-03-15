#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from bridge_lib import SpecError, load_json_input, print_json, run_provider_task


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one Codex or Gemini provider task through the existing repo wrappers.",
    )
    parser.add_argument("--spec", help="Inline JSON task spec.")
    parser.add_argument("--spec-file", help="Path to a JSON task spec.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        spec = load_json_input(args.spec, args.spec_file)
        result = run_provider_task(spec)
    except SpecError as exc:
        print_json({"ok": False, "error": str(exc)}, pretty=args.pretty)
        return 2
    except Exception as exc:  # pragma: no cover - defensive shell bridge guard.
        print_json({"ok": False, "error": f"Unexpected bridge failure: {exc}"}, pretty=args.pretty)
        return 3

    print_json(result, pretty=args.pretty)
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
