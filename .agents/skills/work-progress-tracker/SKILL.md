---
name: work-progress-tracker
description: Track long-running work by turning scattered updates into a clear status snapshot. Use when a task spans many steps, sub-agents, logs, or retries and you need exact progress, blockers, next actions, and completion criteria.
---

# Work Progress Tracker

## Workflow

1. Identify the active goal.
2. Separate work into:
   - completed
   - in progress
   - blocked
   - not started
3. Name the current blocking issue, not just the latest activity.
4. Record the next concrete action that would move the task forward.
5. If percentages are used, tie them to objective remaining work.

## Output format

- Goal:
- Done:
- In progress:
- Blocked by:
- Next action:
- Completion signal:

## Rules

- Do not confuse motion with progress.
- Prefer evidence from commits, tests, logs, or running processes.
- If the task is stuck on one unresolved blocker, say so directly.
- Keep status concise and decision-useful.
