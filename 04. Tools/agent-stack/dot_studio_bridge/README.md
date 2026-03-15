# DOT Studio Bridge Prototype

This directory is a practical adapter layer for using `dot-studio` as a visual front-end while keeping execution in this repo's existing CLI wrappers:

- `scripts/delegate_to_codex.sh`
- `scripts/delegate_to_gemini.sh`

It does not replace DOT Studio's OpenCode runtime. It gives you a small bridge that can be called from a Studio-side server route or node executor.

## Layout

- `scripts/run_provider_task.py` - run one provider task from JSON
- `scripts/run_sequence.py` - run a small serial step graph with template substitution
- `examples/` - example task and sequence specs
- `docs/architecture.md` - how this can plug into DOT Studio without a runtime fork

## Provider Task Spec

```json
{
  "provider": "codex",
  "cwd": "/Users/tttksj/first_repo",
  "prompt": "Reply with BRIDGE_OK only.",
  "model": null,
  "json": false,
  "output_path": null
}
```

Run it:

```bash
python3 "04. Tools/agent-stack/dot_studio_bridge/scripts/run_provider_task.py" \
  --spec-file "04. Tools/agent-stack/dot_studio_bridge/examples/provider_task.codex.json" \
  --pretty
```

The output is normalized JSON with:

- `provider`
- `command` and `command_text`
- `exit_code`
- `stdout` and `stderr`
- `parsed_output` when `json=true` and stdout parses cleanly

## Sequence Spec

The sequence runner executes ordered steps and supports `{{ ... }}` substitution in step fields.

Supported references:

- `{{input.some_key}}`
- `{{defaults.cwd}}`
- `{{steps.plan.stdout}}`
- `{{steps.plan.parsed_output}}`
- `{{last.stdout}}`

Example:

```bash
python3 "04. Tools/agent-stack/dot_studio_bridge/scripts/run_sequence.py" \
  --spec-file "04. Tools/agent-stack/dot_studio_bridge/examples/sequence.serial.json" \
  --pretty
```

## Notes

- Extra metadata on steps, such as `node_type`, is ignored by execution but preserved in result output where useful.
- This is intentionally prototype-grade: serial execution only, no streaming tokens, no session reuse, no DOT Studio graph semantics beyond "ordered nodes".
