# Natural-Language Routing Registry

This registry maps Telegram/OpenClaw-style requests to the local skills in `.agents/skills` and the reference repos in `04. Tools/agent-stack/repos`.

The router script reads the JSON blocks below and combines them with `repos.json`, so keep repo ids and skill ids aligned with the current local assets.

## Route Format

- `id`: stable intent id returned by the router
- `summary`: short description of the class
- `strong_phrases`: higher-weight phrase matches
- `keywords`: lower-weight fallback matches
- `recommended_skills`: local skill ids plus why to use them
- `recommended_repos`: agent-stack repo ids plus why they help
- `handle_via`: `direct` or `delegate`
- `execution_path`: short recommendation for the parent assistant
- `examples`: representative request shapes

## obsidian_note_work
```json
{
  "id": "obsidian_note_work",
  "summary": "Obsidian vault work, note cleanup, clipping, and second-brain workflows.",
  "strong_phrases": [
    "obsidian",
    "obsidian clipper",
    "second brain",
    "vault",
    "wikilink"
  ],
  "keywords": [
    "note",
    "notes",
    "markdown",
    "capture",
    "clip",
    "clipper",
    "meeting notes",
    "daily note",
    "knowledge base"
  ],
  "recommended_skills": [
    {
      "id": "agency-orchestrator-lite",
      "reason": "Use when the note request spans plan/edit/verify phases instead of a single rewrite."
    },
    {
      "id": "work-progress-tracker",
      "reason": "Useful when note curation is part of a longer-running capture or cleanup effort."
    }
  ],
  "recommended_repos": [
    {
      "id": "obsidian-code",
      "reason": "Best local reference for vault-centric note reading, writing, and command execution patterns."
    },
    {
      "id": "awesome-openclaw-usecases",
      "reason": "Good source for second-brain and phone-driven assistant workflow ideas."
    }
  ],
  "handle_via": "direct",
  "execution_path": "Handle directly with the parent assistant for note edits or vault workflow suggestions. Pull in the reference repo only if the request needs plugin-style Obsidian workflow design.",
  "examples": [
    "Organize these meeting notes into my Obsidian vault.",
    "Make this Telegram capture usable in Obsidian with wikilinks."
  ]
}
```

## openclaw_orchestration_ideas
```json
{
  "id": "openclaw_orchestration_ideas",
  "summary": "OpenClaw, Telegram, and multi-agent orchestration design or routing ideas.",
  "strong_phrases": [
    "openclaw",
    "multi-agent",
    "planner executor verifier",
    "agent routing",
    "workflow design",
    "orchestration"
  ],
  "keywords": [
    "telegram",
    "delegate",
    "handoff",
    "coordinator",
    "router",
    "agent",
    "planner",
    "executor",
    "verifier",
    "workflow",
    "team"
  ],
  "recommended_skills": [
    {
      "id": "agency-orchestrator-lite",
      "reason": "Best fit for splitting broad orchestration ideas into a compact phase-based execution plan."
    },
    {
      "id": "agency-project-ops",
      "reason": "Useful when the orchestration idea spans multiple queues, owners, or competing priorities."
    }
  ],
  "recommended_repos": [
    {
      "id": "agency-agents",
      "reason": "Strongest local reference for role separation, handoffs, and agent catalog structure."
    },
    {
      "id": "symphony",
      "reason": "Best local reference for long-running autonomous runs, proof-of-work, and observability."
    },
    {
      "id": "awesome-openclaw-usecases",
      "reason": "Useful source of concrete OpenClaw and Telegram usage patterns."
    }
  ],
  "handle_via": "delegate",
  "execution_path": "Delegate to Codex when the request needs repo-backed orchestration design, reference comparison, or a new execution workflow. Handle directly only for a quick triage or recommendation.",
  "examples": [
    "Route Telegram requests across planner, executor, and verifier agents.",
    "Design an OpenClaw workflow for multi-agent task handoff."
  ]
}
```

## quant_autoresearch
```json
{
  "id": "quant_autoresearch",
  "summary": "AutoResearch-style quant experiment loops, strategy tuning, and variant comparison.",
  "strong_phrases": [
    "autoresearch",
    "quant",
    "parameter sweep",
    "paper trading",
    "strategy optimization",
    "overnight experiment"
  ],
  "keywords": [
    "optimize",
    "tune",
    "variant",
    "compare",
    "backtest",
    "replay",
    "paper",
    "leverage",
    "pnl",
    "strategy"
  ],
  "recommended_skills": [
    {
      "id": "quant-autoresearch",
      "reason": "Primary local skill for evidence-based experiment loops and candidate ranking."
    },
    {
      "id": "agency-reality-check",
      "reason": "Use to verify whether a candidate actually improved before promoting it."
    }
  ],
  "recommended_repos": [
    {
      "id": "autoresearch",
      "reason": "Direct local reference for autonomous experiment loops and human-authored program instructions."
    },
    {
      "id": "symphony",
      "reason": "Useful if the quant loop needs stronger run isolation, observability, or queueing."
    }
  ],
  "handle_via": "delegate",
  "execution_path": "Delegate to Codex for replay, paper, or comparative experiment work. Keep the parent assistant at triage level unless the request is only asking for a compact experiment plan.",
  "examples": [
    "Run an overnight quant autoresearch loop and compare the top variants.",
    "Tune these strategy parameters with replay before any live change."
  ]
}
```

## security_secrets
```json
{
  "id": "security_secrets",
  "summary": "Secret exposure, credential traces, unsafe defaults, and security sanity checks.",
  "strong_phrases": [
    "api key",
    "secret leak",
    "credential leak",
    "password trace",
    "unsafe to run",
    "secret cleanup"
  ],
  "keywords": [
    "secret",
    "token",
    "credential",
    "password",
    "env",
    "leak",
    "privacy",
    "risk",
    "permission",
    "security"
  ],
  "recommended_skills": [
    {
      "id": "agency-security-sanity",
      "reason": "Best fit for defensive risk review and concrete remediation guidance."
    },
    {
      "id": "secret-trace-scan",
      "reason": "Use when the request is specifically about finding and cleaning up local secret traces."
    }
  ],
  "recommended_repos": [
    {
      "id": "onecli",
      "reason": "Strongest local reference for credential isolation and gateway-based secret handling."
    },
    {
      "id": "agency-agents",
      "reason": "Useful source for compliance, trust, and review-oriented agent patterns."
    }
  ],
  "handle_via": "direct",
  "execution_path": "Handle directly with local defensive skills first. Delegate only if the request expands into a broader system redesign for secret routing or permissions.",
  "examples": [
    "Check whether any API keys were leaked into local files or shell history.",
    "Is this automation safe enough to run with current permissions?"
  ]
}
```

## code_review_commit_hygiene
```json
{
  "id": "code_review_commit_hygiene",
  "summary": "Changed-file review, commit readiness, dirty-tree triage, and suspicious diff cleanup.",
  "strong_phrases": [
    "code review",
    "review code",
    "safe to commit",
    "commit hygiene",
    "pre-push review"
  ],
  "keywords": [
    "review",
    "commit",
    "push",
    "diff",
    "dirty",
    "staged",
    "unstaged",
    "git",
    "checkpoint",
    "artifact"
  ],
  "recommended_skills": [
    {
      "id": "code-review-checkpoint",
      "reason": "Primary local skill for changed-file review and missing-validation triage."
    },
    {
      "id": "commit-hygiene-guard",
      "reason": "Best fit when the main question is whether the working tree is safe to commit."
    }
  ],
  "recommended_repos": [
    {
      "id": "agency-agents",
      "reason": "Useful reference for reviewer, evidence, and reality-checker role separation."
    },
    {
      "id": "symphony",
      "reason": "Good reference when commit review should feed into a proof-of-work or verify-before-land flow."
    }
  ],
  "handle_via": "direct",
  "execution_path": "Handle directly with the local review skills. Delegate only if the user wants a new automated review workflow or a repo-backed process redesign.",
  "examples": [
    "Do a code review of the changed files and tell me if this is safe to commit.",
    "Clean up this mixed diff before I push."
  ]
}
```

## logs_debugging
```json
{
  "id": "logs_debugging",
  "summary": "Log digestion, stack traces, daemon failures, and compact debugging triage.",
  "strong_phrases": [
    "stack trace",
    "test failure",
    "daemon heartbeat",
    "why did this crash",
    "summarize logs"
  ],
  "keywords": [
    "log",
    "logs",
    "debug",
    "debugging",
    "trace",
    "error",
    "failure",
    "heartbeat",
    "exception",
    "crash"
  ],
  "recommended_skills": [
    {
      "id": "debug-log-summarizer",
      "reason": "Primary local skill for reducing noisy logs to current state, root cause, evidence, and next step."
    },
    {
      "id": "config-runtime-drift-check",
      "reason": "Use when the failure looks like a config/runtime mismatch instead of pure code logic."
    }
  ],
  "recommended_repos": [
    {
      "id": "symphony",
      "reason": "Best local reference for observability, worker state, and long-running agent runtime behavior."
    },
    {
      "id": "agency-agents",
      "reason": "Useful reference for evidence collection and failure-routing patterns."
    }
  ],
  "handle_via": "direct",
  "execution_path": "Handle directly for log summarization and immediate triage. Delegate if the request turns into a larger runtime architecture or observability redesign.",
  "examples": [
    "Summarize these daemon logs and tell me the latest real failure.",
    "This test output is noisy. Find the blocking error."
  ]
}
```

## long_running_work_tracking
```json
{
  "id": "long_running_work_tracking",
  "summary": "Status snapshots for multi-step work, blockers, retries, and completion signals.",
  "strong_phrases": [
    "long-running",
    "progress report",
    "what is left",
    "blocked by",
    "completion signal"
  ],
  "keywords": [
    "status",
    "progress",
    "tracking",
    "tracker",
    "blocked",
    "retry",
    "next action",
    "in progress",
    "not started",
    "snapshot"
  ],
  "recommended_skills": [
    {
      "id": "work-progress-tracker",
      "reason": "Primary local skill for turning scattered progress into a decision-useful snapshot."
    },
    {
      "id": "agency-project-ops",
      "reason": "Useful when status tracking also needs prioritization or blocker management."
    }
  ],
  "recommended_repos": [
    {
      "id": "symphony",
      "reason": "Strongest local reference for run-level state, retries, and proof-of-work tracking."
    },
    {
      "id": "awesome-openclaw-usecases",
      "reason": "Useful source for project-state and multi-channel assistant patterns."
    }
  ],
  "handle_via": "direct",
  "execution_path": "Handle directly for concise status snapshots. Delegate only when the user wants a new tracking system, state model, or automation workflow.",
  "examples": [
    "Give me an exact progress snapshot for this long-running task.",
    "What is blocked, what is done, and what is the next action?"
  ]
}
```
