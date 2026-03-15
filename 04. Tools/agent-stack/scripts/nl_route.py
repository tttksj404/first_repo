#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
AGENT_STACK_ROOT = SCRIPT_PATH.parents[1]
REPO_ROOT = SCRIPT_PATH.parents[3]
REGISTRY_PATH = AGENT_STACK_ROOT / "docs" / "nl-routing-registry.md"
MANIFEST_PATH = AGENT_STACK_ROOT / "repos.json"
SKILLS_ROOT = REPO_ROOT / ".agents" / "skills"


def load_registry(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^##\s+(?P<heading>[a-z0-9_]+)\s*$\n```json\n(?P<body>.*?)\n```",
        re.MULTILINE | re.DOTALL,
    )
    routes = []
    for match in pattern.finditer(text):
        route = json.loads(match.group("body"))
        heading = match.group("heading")
        if route.get("id") != heading:
            raise ValueError(f"Registry heading/id mismatch: {heading} != {route.get('id')}")
        routes.append(route)
    if not routes:
        raise ValueError(f"No routes found in {path}")
    return routes


def load_manifest(path: Path) -> dict[str, dict]:
    items = json.loads(path.read_text(encoding="utf-8"))
    return {item["id"]: item for item in items}


def normalize_text(value: str) -> str:
    lowered = value.lower()
    return re.sub(r"[^0-9a-zA-Z가-힣]+", " ", lowered).strip()


def term_hit(request_raw: str, request_normalized: str, term: str) -> bool:
    probe = term.lower().strip()
    if not probe:
        return False
    if " " in probe or re.search(r"[^0-9a-z]", probe):
        return probe in request_raw
    return re.search(rf"(?<!\w){re.escape(probe)}(?!\w)", request_normalized) is not None


def score_route(route: dict, request: str) -> tuple[int, list[dict]]:
    request_raw = request.lower()
    request_normalized = normalize_text(request)
    hits = []
    score = 0

    for phrase in route.get("strong_phrases", []):
        if term_hit(request_raw, request_normalized, phrase):
            score += 3
            hits.append({"term": phrase, "kind": "strong_phrase", "weight": 3})

    for keyword in route.get("keywords", []):
        if term_hit(request_raw, request_normalized, keyword):
            score += 1
            hits.append({"term": keyword, "kind": "keyword", "weight": 1})

    return score, hits


def skill_record(skill_entry: dict) -> dict:
    skill_id = skill_entry["id"]
    skill_path = SKILLS_ROOT / skill_id / "SKILL.md"
    return {
        "id": skill_id,
        "path": str(skill_path.relative_to(REPO_ROOT)),
        "exists": skill_path.exists(),
        "reason": skill_entry["reason"],
    }


def repo_record(repo_entry: dict, manifest: dict[str, dict]) -> dict:
    repo_id = repo_entry["id"]
    manifest_item = manifest.get(repo_id)
    if manifest_item is None:
        return {
            "id": repo_id,
            "exists": False,
            "reason": repo_entry["reason"],
        }

    local_path = manifest_item.get("local_path")
    return {
        "id": repo_id,
        "name": manifest_item.get("name"),
        "type": manifest_item.get("type"),
        "local_path": local_path,
        "exists": bool(local_path and (REPO_ROOT / local_path).exists()),
        "manifest_why": manifest_item.get("why"),
        "reason": repo_entry["reason"],
    }


def build_result(route: dict, hits: list[dict], score: int, manifest: dict[str, dict], request: str) -> dict:
    return {
        "request": request,
        "intent_id": route["id"],
        "summary": route["summary"],
        "score": score,
        "why_it_matched": [
            f"{hit['kind']} '{hit['term']}' matched (+{hit['weight']})" for hit in hits
        ],
        "recommended_skills": [skill_record(item) for item in route["recommended_skills"]],
        "recommended_repos": [repo_record(item, manifest) for item in route["recommended_repos"]],
        "handle_via": route["handle_via"],
        "delegate_to_codex": route["handle_via"] == "delegate",
        "execution_path": route["execution_path"],
        "examples": route.get("examples", []),
    }


def format_text(result: dict) -> str:
    lines = [
        f"intent_id: {result['intent_id']}",
        f"summary: {result['summary']}",
        f"score: {result['score']}",
        "why_it_matched:",
    ]
    lines.extend(f"- {item}" for item in result["why_it_matched"])
    lines.append("recommended_skills:")
    for skill in result["recommended_skills"]:
        lines.append(
            f"- {skill['id']} ({skill['path']}, exists={str(skill['exists']).lower()}): {skill['reason']}"
        )
    lines.append("recommended_repos:")
    for repo in result["recommended_repos"]:
        lines.append(
            f"- {repo['id']} ({repo.get('local_path')}, exists={str(repo['exists']).lower()}): {repo['reason']}"
        )
    lines.append(f"handle_via: {result['handle_via']}")
    lines.append(f"delegate_to_codex: {str(result['delegate_to_codex']).lower()}")
    lines.append(f"execution_path: {result['execution_path']}")
    return "\n".join(lines)


def classify_request(request: str, routes: list[dict], manifest: dict[str, dict]) -> dict:
    scored = []
    for route in routes:
        score, hits = score_route(route, request)
        if score > 0:
            scored.append((score, len(hits), route["id"], route, hits))

    if not scored:
        return {
            "request": request,
            "intent_id": "unclassified",
            "summary": "No routing class met the minimum score.",
            "score": 0,
            "why_it_matched": [],
            "recommended_skills": [],
            "recommended_repos": [],
            "handle_via": "direct",
            "delegate_to_codex": False,
            "execution_path": "Handle directly with a quick manual triage, or expand the registry if this request pattern becomes common.",
            "examples": [],
        }

    best_score, _, _, best_route, best_hits = max(scored, key=lambda item: item[:3])
    return build_result(best_route, best_hits, best_score, manifest, request)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Route a Telegram/OpenClaw-style request to the best local skill and reference repo."
    )
    parser.add_argument("request", nargs="?", help="Natural-language request to classify.")
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="Output format.",
    )
    parser.add_argument(
        "--list-intents",
        action="store_true",
        help="Print the intent ids registered in the markdown registry and exit.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    routes = load_registry(REGISTRY_PATH)

    if args.list_intents:
        for route in routes:
            print(f"{route['id']}: {route['summary']}")
        return 0

    if not args.request:
        print("A request string is required unless --list-intents is used.", file=sys.stderr)
        return 2

    manifest = load_manifest(MANIFEST_PATH)
    result = classify_request(args.request, routes, manifest)

    if args.format == "text":
        print(format_text(result))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
