---
name: agency-orchestrator-lite
description: Lightweight orchestration for multi-step work with role separation between planning, implementation, verification, and summary. Use when a task is long, complex, or benefits from staged execution instead of one-shot handling.
---

# Agency Orchestrator Lite

1. Split work into phases:
   - plan
   - implement
   - verify
   - summarize
2. Do not mix verification into implementation by default.
3. Track current phase and the single blocking issue.
4. If a phase fails, loop only that phase instead of restarting everything.
5. Prefer specialist tools or agents for the current phase.

## Output
- Goal:
- Current phase:
- Done:
- Blocked by:
- Next phase:
