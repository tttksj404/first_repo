---
name: agency-security-sanity
description: Practical defensive security review for local code, config, secrets handling, and operational risk. Use when the user asks about leaks, exposed keys, risky automation, credential traces, unsafe defaults, or whether something is safe enough to run.
---

# Agency Security Sanity

1. Focus on defensive risk, not exploitation.
2. Check for:
   - secret traces
   - unsafe defaults
   - over-broad permissions
   - accidental exposure paths
   - destructive or externally visible side effects
3. Rank findings:
   - critical
   - high
   - medium
   - low
4. Pair every risk with a concrete fix.

## Output
- Risk:
- Severity:
- Evidence:
- Fix:
- Safe to proceed: yes/no
