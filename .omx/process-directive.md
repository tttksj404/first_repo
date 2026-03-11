# Persistent Execution Directive

Recorded on: 2026-03-09

For subsequent user requests in this workspace, default execution policy is:

1. Analyze the request and local/project context first.
2. Validate assumptions with tests, inspection, or external verification when needed.
3. Execute the required work end-to-end whenever feasible.
4. Apply changes directly rather than stopping at proposals.
5. Report outcomes, evidence, blockers, and operational implications clearly.

Additional instruction:

- Treat this as the default workflow for all future user commands unless the user explicitly overrides it.
- Prefer doing the full cycle in one turn: analysis, validation, execution, application, and reporting.
- If disk space becomes constrained or file growth threatens runtime stability, prioritize log/file housekeeping work above other optimizations.
- When storage pressure blocks edits or tests, first reclaim space by pruning generated artifacts, oversized logs, and stale runtime outputs, then continue the requested work.
- Treat automatic file cleanup and retention control for runtime outputs as a standing high-priority maintenance concern in this workspace.
