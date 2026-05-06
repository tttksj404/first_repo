---
name: auto-dream
description: Consolidate and optimize Claude Code memory files — merge duplicates, remove stale info, keep MEMORY.md under 200 lines. Run manually with "dream" or auto-triggered via SessionStart hook.
---

# Auto Dream — Memory Consolidation

## When to Run
- **Manual**: User says "dream" or "consolidate my memory files"
- **Auto**: SessionStart hook detects 24h elapsed AND 5+ sessions since last dream

## Memory Directory
`~/.claude/projects/-Users-tttksj-first-repo/memory/`

## Workflow

### Step 1: Read All Memory Files
Read every file in the memory directory:
- `MEMORY.md` (main index, must stay under 200 lines)
- `quant.md` (quant system architecture details)
- `workflow.md` (dev workflow, git, deployment patterns)
- Any other `.md` files that exist

### Step 2: Analyze
Identify across all files:
- **Duplicates**: Same information repeated in multiple files or sections
- **Outdated info**: References to old commits, removed features, stale paths
- **Contradictions**: Conflicting statements between files
- **Gaps**: Recent work or patterns not yet captured in memory
- **Overgrown topics**: Sections in MEMORY.md that should be extracted to their own topic file

### Step 3: Consolidate
- Merge duplicate entries, keeping the most current version
- Remove stale or outdated information
- Resolve contradictions (prefer most recent info)
- Move detailed topic content from MEMORY.md into appropriate topic files
- Create new topic files if a subject has accumulated enough detail (5+ related entries)

### Step 4: Enforce Constraints
- **MEMORY.md must stay under 200 lines** — this is the startup load threshold
- MEMORY.md should be a high-level index with links to topic files
- Topic files hold the detailed information
- Every topic file must be linked from MEMORY.md's "Topic Files" section

### Step 5: Update Tracking
Write `last_dream.json` in the memory directory:
```json
{
  "last_dream_timestamp": "<current ISO 8601 timestamp>",
  "sessions_since_dream": 0
}
```

### Step 6: Report
Output a brief summary of changes:
- Files modified
- Entries merged/removed/added
- Current MEMORY.md line count
- Any new topic files created
- Next auto-dream estimated trigger

## Rules
- NEVER delete memory files entirely — only consolidate content
- NEVER remove information that is still relevant, even if old
- Preserve the MEMORY.md structure: Overview, Key Directories, Architecture, Key Files, etc.
- Keep topic file links in MEMORY.md up to date
- Use the user's preferred language (Korean) for any commentary, but keep technical terms in English
