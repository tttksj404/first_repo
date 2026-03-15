# Architecture Note

## What This Prototype Does Now

The bridge keeps DOT Studio in its current role as the visual workspace and lets this repo remain the execution owner for Codex and Gemini.

Today the bridge can:

1. Accept a simple task spec for `provider=codex|gemini`.
2. Shell out to this repo's existing wrapper scripts.
3. Return normalized JSON that a DOT Studio route or node inspector could render directly.
4. Execute a small ordered sequence and substitute prior step output into later prompts.

The important constraint is that this is an adapter around existing wrappers, not a replacement for Studio's OpenCode runtime.

## Practical Integration Path

DOT Studio already has a server boundary between the React client and its runtime layer:

- client API surface: `04. Tools/agent-stack/repos/dot-studio/src/api.ts`
- server entry: `04. Tools/agent-stack/repos/dot-studio/server/index.ts`
- current act execution authority: `04. Tools/agent-stack/repos/dot-studio/server/lib/act-runtime.ts`

The smallest credible integration is:

1. Add a Studio-side server route such as `/api/bridge/provider-task` and `/api/bridge/sequence`.
2. In that route, `spawn` one of these Python scripts with `--spec-file` or `--spec`.
3. Return the normalized JSON result to the existing thread panel or a lightweight "bridge result" inspector.
4. Gate usage behind a performer or node convention, for example:
   - performer model/provider tagged as `codex`
   - performer model/provider tagged as `gemini`
   - node metadata like `runtime: "external-bridge"`

That lets Studio keep:

- stage editing
- performer/node composition
- existing act canvas UX

while delegating only selected node execution to this repo's wrappers.

## What This Avoids

This avoids a full replacement of the OpenCode path. You do not need to fork:

- Studio state management
- prompt composition UX
- the full act editor
- the full Studio server

Instead, you add one narrow execution escape hatch for selected providers.

## What Would Need Deeper DOT Studio Integration

This bridge does not currently provide:

- streaming token events
- abort/resume semantics
- long-lived session reuse across nodes
- parallel joins or true orchestrator graph routing
- full Tal/Dance prompt compilation parity
- MCP/tool wiring parity with Studio's OpenCode integration
- provider auth or model catalog management inside Studio

Those would require explicit changes in DOT Studio's server/runtime layer, especially around the current `act-runtime.ts` session and event model.

## Suggested First Bridge Shape

Treat the scripts here as a prototype contract:

- single-step execution for worker-like nodes
- ordered sequence execution for simple graph demos
- normalized JSON results for easy inspection and logging

If that proves useful, the next step is not "rewrite OpenCode in Studio". The next step is "teach Studio to call this bridge for a small class of external-provider nodes".
