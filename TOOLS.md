# TOOLS.md - Local Notes

## Obsidian

Primary vault:

- `/Users/tttksj/Library/Mobile Documents/iCloud~md~obsidian/Documents/brain of podo`

Secondary vault:

- `/Users/tttksj/Library/Mobile Documents/iCloud~md~obsidian/Documents/note`

Operational notes:

- Vault paths contain spaces. Quote paths correctly in shell commands.
- If you need to work outside the current workspace root, host-side elevated execution is allowed for Telegram user `6768216338`.
- Prefer the primary vault unless the user explicitly names the secondary one.

## Telegram

- Bot handle: `@tttksj_bot`
- Allowed DM sender for elevated actions: `6768216338`
- DM commands from that sender should be treated as authorized work requests.
- Broad Telegram requests about the user's established work domains are authorized by default.
- Established work domains include Obsidian, LEET/study materials, local writing workflows, and local repo/file tasks.
- Do not treat login/linking, external uploads, internet publication, secret sharing, or destructive operations as auto-authorized. Ask again first.

## Local Project Root

- Default code/project root: `/Users/tttksj/first_repo`
- If the user refers to a relative project path like `scripts/quant_run_live_orders.sh`, resolve it as `/Users/tttksj/first_repo/scripts/quant_run_live_orders.sh` unless they specify another root.
- For repo tasks, use `/Users/tttksj/first_repo` as the default working directory.
- If a referenced path is missing, search under `/Users/tttksj/first_repo` before asking the user.
- For common repo folders such as `scripts`, `src`, `tests`, and `docs`, assume they belong to `/Users/tttksj/first_repo` unless evidence says otherwise.

## Local IDE + CLI Access

Available IDE apps:

- `/Applications/Cursor.app`
- `/Applications/PyCharm.app`
- `/Applications/Codex.app`

Available CLI tools:

- `codex` at `/Users/tttksj/.npm-global/bin/codex`
- `gemini` at `/usr/local/bin/gemini`

Preferred wrappers in this repo:

- Open Cursor for a path: `/Users/tttksj/first_repo/scripts/open_cursor_here.sh`
- Open PyCharm for a path: `/Users/tttksj/first_repo/scripts/open_pycharm_here.sh`
- Open Codex app: `/Users/tttksj/first_repo/scripts/open_codex_app.sh`
- Run Gemini non-interactively: `/Users/tttksj/first_repo/scripts/run_gemini_prompt.sh`
- Run Codex non-interactively: `/Users/tttksj/first_repo/scripts/run_codex_exec.sh`
- Delegate arbitrary work to Gemini: `/Users/tttksj/first_repo/scripts/delegate_to_gemini.sh`
- Delegate arbitrary work to Codex: `/Users/tttksj/first_repo/scripts/delegate_to_codex.sh`

Rules:

- For GUI apps, use host-side elevated exec.
- For `gemini` and `codex`, prefer the wrapper scripts above over ad hoc commands.
- You may call `gemini` or `codex`, capture their outputs, and use those outputs in your final response or next steps.
- If the user asks to compare or cross-check results between OpenClaw, Gemini, and Codex, do that automatically when useful.
- If the user explicitly asks to have Codex CLI or Gemini CLI do the task, use the delegate scripts.
- For broad tasks, you may delegate all or part of the work to those CLIs, then integrate or summarize the result.
- If any wrapper, CLI, IDE launch, or delegated tool fails, report the exact failing command and the concrete error cause.

## Editing Preferences

- For note edits, preserve existing markdown conventions.
- For generated study notes, keep structure clean and reusable.
- For LEET-related outputs, optimize for clarity, consistency, and easy revision later.
- For broad cleanup or continuation tasks, prefer producing a completed batch of useful edits instead of tiny incremental changes.
