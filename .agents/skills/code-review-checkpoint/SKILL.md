---
name: code-review-checkpoint
description: Run a compact pre-commit or pre-push review on changed files. Use when changes are ready to finalize and you need a quick checkpoint for risky diffs, unrelated file noise, missing tests, migration mistakes, or commit readiness.
---

# Code Review Checkpoint

## Workflow

1. Inspect changed files only.
2. Group findings into:
   - intended changes
   - suspicious unrelated changes
   - missing validation
   - likely breakage points
3. Check for:
   - accidental file deletions
   - runtime artifacts in git changes
   - config drift
   - signature mismatch between callers and callees
   - tests that should exist but do not
4. Decide one of three outcomes:
   - safe to commit
   - commit after small fixes
   - do not commit yet

## Output format

- Safe to commit: yes/no
- Intended files:
- Suspicious files:
- Missing checks:
- Recommended action:

## Rules

- Prioritize correctness over style.
- Call out dirty working tree issues explicitly.
- Treat generated output, caches, and runtime artifacts as suspicious by default.
- Prefer narrow commits over mixed commits.
