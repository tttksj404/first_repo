#!/bin/sh
set -eu

pkill -f 'quant_binance.runtime --mode live-auto-trade-daemon' || true
pkill -f 'quant_binance.runtime --mode live-paper-daemon' || true
echo "stopped"
