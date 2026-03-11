---
name: commit-hygiene-guard
description: Detect dirty working tree problems before commit or push. Use when the user mentions commit, push, git, sync, clean up changes, mixed diff, accidental deletion, runtime artifacts, unrelated files, or asks whether a repo is safe to commit.
---

# Commit Hygiene Guard

1. Inspect only changed and untracked files first.
2. Separate intended code changes from suspicious noise.
3. Treat these as suspicious by default:
   - runtime outputs
   - caches
   - logs
   - generated artifacts
   - broad deletions
   - editor history files
4. Report:
   - safe files to commit
   - suspicious files to exclude
   - missing validation before commit
5. Prefer narrow commits over mixed commits.

## Output
- Safe to commit:
- Intended files:
- Suspicious files:
- Missing checks:
- Recommended next action:
