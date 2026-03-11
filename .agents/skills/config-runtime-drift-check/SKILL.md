---
name: config-runtime-drift-check
description: Find mismatches between config, runtime, scripts, env vars, and code paths. Use when the user says something should work but runtime behavior disagrees, or mentions mismatch, drift, daemon, script args, env check, config issue, stale settings, or execution path problems.
---

# Config Runtime Drift Check

1. Compare config values, runtime args, env variables, and calling code.
2. Look for caller/callee signature mismatch, outdated script flags, stale env defaults, and code paths using different assumptions.
3. Prioritize the first mismatch that blocks execution.
4. Confirm whether the problem is:
   - config drift
   - script drift
   - runtime wiring mismatch
   - env loading mismatch
5. End with one concrete fix path.

## Output
- Observed behavior:
- Likely mismatch:
- Evidence:
- Fix path:
