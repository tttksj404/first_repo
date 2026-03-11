---
name: debug-log-summarizer
description: Summarize long logs, command output, stack traces, daemon heartbeats, and test failures into root cause, evidence, current state, and next actions. Use when logs are noisy, repetitive, or too long to reason about quickly.
---

# Debug Log Summarizer

## Workflow

1. Read the smallest useful log window first.
2. Identify the latest meaningful failure, warning, or state transition.
3. Separate signal from repetition:
   - root cause candidate
   - confirmed evidence
   - side effects
   - unresolved unknowns
4. Report in this order:
   - current state
   - likely root cause
   - exact evidence
   - next debug step
5. Quote only the minimum lines needed to support the conclusion.

## Output format

Use compact bullets:
- State:
- Root cause:
- Evidence:
- Next step:

## Rules

- Prefer the most recent failure over older noise.
- Distinguish confirmed facts from hypotheses.
- If heartbeats continue, say the process is alive even if work is stalled.
- If multiple failures exist, rank them by what blocks progress first.
- Do not dump entire logs when a short evidence slice is enough.
