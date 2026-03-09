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
