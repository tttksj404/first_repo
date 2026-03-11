---
name: secret-trace-scan
description: Scan local traces of sensitive data exposure such as API keys, passwords, tokens, login traces, editor history, shell history, env files, and browser-stored remnants. Use when the user mentions security, leak, exposed key, password trace, credential cleanup, privacy, or asks whether secrets remain on the machine.
---

# Secret Trace Scan

1. Check environment variable presence without printing secrets.
2. Search likely local trace locations:
   - editor history
   - env files
   - shell history
   - browser login storage
   - project files
3. Report existence and path only, never echo secret values.
4. Recommend cleanup order:
   - revoke/rotate if exposed
   - delete local traces
   - verify removal
5. Prefer minimal disclosure in outputs.

## Output
- Secret type:
- Trace found:
- Location:
- Risk level:
- Recommended cleanup:
