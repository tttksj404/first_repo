#!/bin/sh
set -eu

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <naver-url> [output-md]" >&2
  exit 1
fi

URL="$1"
OUTPUT="${2:-quant_runtime/artifacts/naver_article.md}"

cd "$(dirname "$0")/.."

if ! node -e "import('playwright').then(() => process.exit(0)).catch(() => process.exit(1))"; then
  npm install --no-save playwright
fi

node scripts/extract_naver_article.mjs "$URL" "$OUTPUT"
