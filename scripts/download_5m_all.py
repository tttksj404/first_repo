#!/usr/bin/env python3
"""Download 5m klines for all universe symbols from Bitget.

Usage:
    python scripts/download_5m_all.py [--days 365] [--market futures]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env", override=False)

from quant_binance.exchange import ExchangeCredentials
from quant_binance.execution.bitget_rest import BitgetRestClient
from quant_binance.data.historical_download import (
    download_klines_range,
    save_historical_klines,
    load_historical_klines,
)


DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT",
    "BNBUSDT", "DOGEUSDT", "ADAUSDT", "APTUSDT",
    "ARBUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
    "LTCUSDT", "MATICUSDT", "NEARUSDT", "OPUSDT",
    "PEPEUSDT", "SUIUSDT", "UNIUSDT", "WIFUSDT",
]

OUTPUT_DIR = PROJECT_ROOT / "quant_runtime" / "historical"


def build_client() -> BitgetRestClient:
    api_key = os.environ.get("BITGET_API_KEY", "")
    api_secret = os.environ.get("BITGET_API_SECRET", "")
    api_passphrase = os.environ.get("BITGET_API_PASSPHRASE", "")
    if not api_key or not api_secret:
        print("ERROR: BITGET_API_KEY / BITGET_API_SECRET not found in env", file=sys.stderr)
        sys.exit(1)
    creds = ExchangeCredentials(
        exchange_id="bitget",
        api_key=api_key,
        api_secret=api_secret,
        api_passphrase=api_passphrase,
    )
    return BitgetRestClient(credentials=creds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download 5m klines from Bitget")
    parser.add_argument("--days", type=int, default=365, help="How many days back (default: 365)")
    parser.add_argument("--market", default="futures", choices=["futures", "spot"])
    parser.add_argument("--symbols", nargs="*", default=None, help="Override symbols list")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()

    symbols = args.symbols or DEFAULT_SYMBOLS
    interval = "5m"
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - args.days * 86_400_000

    client = build_client()

    print(f"=== Bitget 5m kline download ===")
    print(f"  Market: {args.market}")
    print(f"  Interval: {interval}")
    print(f"  Period: {args.days} days")
    print(f"  Symbols: {len(symbols)}")
    print(f"  Output: {OUTPUT_DIR}")
    print()

    total_klines = 0
    for i, symbol in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] {symbol}")

        if not args.force:
            cached = load_historical_klines(data_dir=OUTPUT_DIR, symbol=symbol, interval=interval)
            if cached:
                cached_start = int(cached[0]["open_time"])
                cached_end = int(cached[-1]["open_time"])
                cached_days = (cached_end - cached_start) / 86_400_000
                if cached_days >= args.days * 0.9:
                    print(f"  cached ({len(cached)} klines, {cached_days:.0f}d), skipping")
                    total_klines += len(cached)
                    continue

        try:
            klines = download_klines_range(
                client,
                market=args.market,
                symbol=symbol,
                interval=interval,
                start_ms=start_ms,
                end_ms=now_ms,
                page_limit=200,
                sleep_between=1.2,
            )
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        if klines:
            path = save_historical_klines(klines, output_dir=OUTPUT_DIR, symbol=symbol, interval=interval)
            range_days = (int(klines[-1]["open_time"]) - int(klines[0]["open_time"])) / 86_400_000
            print(f"  saved {len(klines)} klines ({range_days:.0f}d) -> {path}")
            total_klines += len(klines)
        else:
            print(f"  no data returned")

    print(f"\n=== Done: {total_klines} total 5m klines across {len(symbols)} symbols ===")


if __name__ == "__main__":
    main()
