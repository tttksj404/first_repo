#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
python3 scripts/quant_telegram_bridge.py
