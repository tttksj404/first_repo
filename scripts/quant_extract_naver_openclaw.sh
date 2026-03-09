#!/bin/sh
set -eu

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <naver-url> [output-md]" >&2
  exit 1
fi

URL="$1"
OUTPUT="${2:-quant_runtime/artifacts/openclaw_naver_strategy.md}"

cd "$(dirname "$0")/.."
node scripts/openclaw_naver_crawl.mjs "$URL" "$OUTPUT"
