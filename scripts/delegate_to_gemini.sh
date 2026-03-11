#!/bin/zsh
set -euo pipefail

WORKDIR="/Users/tttksj/first_repo"
MODEL=""
JSON_MODE=0
PROMPT_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cwd)
      WORKDIR="$2"
      shift 2
      ;;
    --model)
      MODEL="$2"
      shift 2
      ;;
    --json)
      JSON_MODE=1
      shift
      ;;
    --)
      shift
      PROMPT_ARGS+=("$@")
      break
      ;;
    *)
      PROMPT_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ ${#PROMPT_ARGS[@]} -eq 0 ]]; then
  echo "Usage: $0 [--cwd DIR] [--model MODEL] [--json] -- <prompt>" >&2
  exit 1
fi

cd "$WORKDIR"

CMD=(gemini)

if [[ -n "$MODEL" ]]; then
  CMD+=(--model "$MODEL")
fi

if [[ "$JSON_MODE" -eq 1 ]]; then
  CMD+=(--output-format json)
else
  CMD+=(--output-format text)
fi

CMD+=(--prompt "${PROMPT_ARGS[*]}")

"${CMD[@]}"
