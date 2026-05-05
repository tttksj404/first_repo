---
name: skill-autoresearch
description: Auto-improve any Claude Code skill using Karpathy's autoresearch loop — test, score, tweak, repeat until 95%+ pass rate. Run with "run autoresearch on [skill-name]".
---

# Skill Autoresearch

Auto-improve any Claude Code skill by iteratively testing, scoring, tweaking, and repeating until the skill consistently produces high-quality output. Based on Karpathy's autoresearch methodology applied to prompt engineering.

---

## Phase 1: Setup (Interactive)

### Step 1 — Identify Target Skill

The user specifies which skill in `.agents/skills/` to optimize. Read the target skill's `SKILL.md` to understand what it does, its current prompt, and its intended behavior.

- Confirm the skill exists at `.agents/skills/{skill-name}/SKILL.md`
- Read the full skill file and summarize it back to the user
- If the skill doesn't exist, list available skills and ask the user to pick one

### Step 2 — Collect Test Inputs

Ask the user for **2-4 test inputs** — these are example prompts they would actually use with the skill in real work. Good test inputs should:

- Cover the range of typical usage (easy case, hard case, edge case)
- Be representative of real work, not synthetic toy examples
- Be specific enough to produce deterministic-ish outputs

Prompt: "Give me 2-4 example prompts you'd actually use with this skill. Include at least one easy case and one tricky case."

### Step 3 — Build Scoring Checklist

Ask the user for **3-6 scoring checklist questions**. Each question must be answerable with a binary YES or NO when evaluating the skill's output.

Help the user convert vague quality complaints into specific yes/no checks:

| User says...                        | Convert to checklist question                              |
|-------------------------------------|------------------------------------------------------------|
| "The output is too generic"         | "Does the output reference specifics from the input?"      |
| "It's too long"                     | "Is the output under N lines/words?"                       |
| "It doesn't sound like me"          | "Does it avoid corporate buzzwords like synergy/leverage?"  |
| "The headline is weak"              | "Does the headline include a specific number or data point?"|
| "It misses the point"               | "Does the first sentence address the core request?"        |
| "Not actionable"                    | "Does every paragraph contain at least one concrete step?" |

Prompt: "What makes this skill's output good vs bad? Give me 3-6 yes/no questions I can use to score each output. I'll help you sharpen vague complaints into specific checks."

---

## Phase 2: Baseline

### Step 1 — Run Baseline Tests

Run the target skill (using the current, unmodified SKILL.md prompt) on each test input. Capture the full output for each.

### Step 2 — Score Baseline

For each test input's output, answer every checklist question with PASS or FAIL. Be strict and consistent — if there is any ambiguity, default to FAIL.

### Step 3 — Calculate Baseline Score

```
baseline_score = (total PASSes) / (total checklist questions * total test inputs) * 100
```

### Step 4 — Create Workspace

Create the workspace directory structure:

```
.agents/skills/skill-autoresearch/workspace/{skill-name}/
  baseline.json       — baseline scores per input per question
  config.json          — test inputs + checklist questions
  skill-snapshot.md    — copy of the original SKILL.md (working copy for modifications)
```

**baseline.json** format:
```json
{
  "score_percent": 66.7,
  "total_pass": 8,
  "total_checks": 12,
  "results": [
    {
      "input_id": 1,
      "input": "the test prompt",
      "checks": [
        {"question": "Q1 text", "result": "PASS"},
        {"question": "Q2 text", "result": "FAIL"}
      ]
    }
  ]
}
```

**config.json** format:
```json
{
  "target_skill": "skill-name",
  "original_skill_path": ".agents/skills/skill-name/SKILL.md",
  "test_inputs": ["input1", "input2", "input3"],
  "checklist": ["Q1", "Q2", "Q3", "Q4"],
  "created_at": "ISO timestamp"
}
```

---

## Phase 3: Improvement Loop

Repeat until **95%+ score achieved 3 consecutive times**, or **max 10 iterations**:

### 1. Analyze

Look at the scoring results from the previous iteration (or baseline). Identify:

- Which checklist questions fail most frequently?
- Are failures concentrated on specific test inputs or spread across all?
- What patterns in the skill prompt (or lack thereof) cause these failures?

### 2. Hypothesize

Propose **ONE small, targeted change** to the skill prompt that would fix the most common failure mode. Types of changes (pick exactly one):

- **Add a rule**: "Always include X" or "Never do Y"
- **Add an example**: Show the skill what good output looks like for a specific pattern
- **Add a constraint**: Length limit, format requirement, required section
- **Add a banned list**: Words, phrases, or patterns to avoid
- **Reword existing instruction**: Clarify an ambiguous instruction that causes misinterpretation
- **Reorder instructions**: Move a critical instruction higher in the prompt for emphasis

### 3. Apply

Make exactly ONE change to the working copy (`skill-snapshot.md`). The change must be:

- Small enough to isolate its effect
- Clearly describable in one sentence
- Reversible if it doesn't help

### 4. Test

Run the modified skill on ALL test inputs. Capture full outputs.

### 5. Score

Score all outputs against the full checklist. Calculate the new percentage score.

### 6. Decide

Compare the new score to the previous score:

- **Score improved (strictly higher)** — KEEP the change. The working copy stays modified.
- **Score stayed the same** — REVERT the change. No improvement means unnecessary complexity.
- **Score decreased** — REVERT the change immediately.
- **Mixed result** (helps one question but hurts another) — REVERT. A change must be net-positive with no regressions.

### 7. Record

Save iteration results to `workspace/{skill-name}/iteration-{N}/`:

**scores.json** — full scoring grid:
```json
{
  "iteration": 1,
  "score_percent": 75.0,
  "previous_score_percent": 66.7,
  "decision": "KEEP",
  "total_pass": 9,
  "total_checks": 12,
  "results": [ ... same format as baseline ... ]
}
```

**change.md** — what was changed:
```markdown
## Change
Added rule: "Always start the first sentence with a concrete action verb."

## Rationale
Checklist question "Does the first sentence address the core request?" failed on 3/4 inputs.
The skill prompt had no instruction about opening sentences.

## Diff
Added to line 15 of the skill prompt:
> Rule: The first sentence of your output MUST begin with a concrete action verb (e.g., Create, Remove, Add, Configure). Never open with "This" or "The".
```

**decision.md** — keep or revert:
```markdown
## Decision: KEEP

## Score: 66.7% -> 75.0% (+8.3%)

## Impact
- Q3 "Does the first sentence address the core request?" went from 1/4 PASS to 4/4 PASS
- No regressions on other questions

## Reasoning
Clear improvement on the targeted failure mode with no negative side effects.
```

---

## Phase 4: Results

### Step 1 — Save Improved Skill

Copy the final working copy to a new skill directory:

```
.agents/skills/{skill-name}-improved/SKILL.md
```

The original skill at `.agents/skills/{skill-name}/SKILL.md` is **never modified**.

### Step 2 — Generate Changelog

Save `workspace/{skill-name}/changelog.md`:

```markdown
# Autoresearch Changelog: {skill-name}

## Iteration 1 — KEEP
- **Change**: Added rule about opening with action verbs
- **Score**: 66.7% -> 75.0%
- **Reason**: Q3 failed on 3/4 inputs; no instruction existed for opening sentences

## Iteration 2 — REVERT
- **Change**: Added banned list of buzzwords
- **Score**: 75.0% -> 75.0% (no change)
- **Reason**: No improvement; added unnecessary complexity

## Iteration 3 — KEEP
- **Change**: Added example of good vs bad output for conciseness
- **Score**: 75.0% -> 91.7%
- **Reason**: Q2 "Is the output under 200 words?" went from 1/4 to 4/4 PASS

...
```

### Step 3 — Generate Summary

Save `workspace/{skill-name}/summary.md`:

```markdown
# Autoresearch Summary: {skill-name}

## Results
- **Starting score**: 66.7%
- **Final score**: 95.8%
- **Iterations**: 5 (3 kept, 2 reverted)
- **Consecutive passes at 95%+**: 3

## Changes Kept
1. Added rule: open with action verb (Q3: 25% -> 100%)
2. Added example: good vs bad concise output (Q2: 25% -> 100%)
3. Added constraint: max 3 bullet points per section (Q5: 50% -> 100%)

## Changes Reverted
1. Banned buzzword list (no improvement)
2. Reordered instructions (hurt Q1)

## Key Insights
- The biggest win was adding a concrete example of good output — rules alone weren't enough
- The skill needed explicit length constraints; "be concise" is too vague
- Instruction ordering matters less than instruction specificity

## Output Location
- Improved skill: `.agents/skills/{skill-name}-improved/SKILL.md`
- Changelog: `.agents/skills/skill-autoresearch/workspace/{skill-name}/changelog.md`
```

---

## Reporting Format

After each iteration, print:

```
Iteration N: XX.X% (arrow from previous)
  Changed: [one-sentence description]
  Decision: KEEP/REVERT
  Failures: Q1(PASS/FAIL), Q2(PASS/FAIL), ...
```

After completion, print:

```
Autoresearch Complete
  Skill: {name}
  Baseline: XX.X% -> Final: YY.Y%
  Iterations: N (K kept, R reverted)
  Improved skill saved to: .agents/skills/{name}-improved/SKILL.md
```

---

## Rules

1. **NEVER modify the original skill file** — always work on the snapshot copy in the workspace.
2. **ONE change per iteration** — isolate variables so you know what helped.
3. **Changes must be SMALL and TARGETED** — one rule, one example, one constraint. Not a rewrite.
4. **If a change helps one question but hurts another, REVERT it** — no tradeoffs, only net-positive changes.
5. **Scoring is binary** — PASS or FAIL per question. No partial credit, no subjective ratings.
6. **Log everything** — the changelog is as valuable as the improved skill itself.
7. **Target 95% but accept diminishing returns** — if stuck at 90%+ after 3 iterations of no progress, stop and report.
8. **Be strict when scoring** — when in doubt, FAIL. This prevents score inflation and ensures real improvement.
9. **Preserve the spirit of the original skill** — improvements should make it better at its stated purpose, not change what it does.
10. **The user's checklist is the ground truth** — never override or reinterpret their quality criteria.
