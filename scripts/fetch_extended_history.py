#!/usr/bin/env python3
"""
Extended Historical Data Fetcher
=================================
Bitget public API로 365일치 1h/4h OHLCV 데이터 수집.
API 키 불필요 (public endpoint).

Bitget API limit: 200 candles per request.
1h: 365일 = 8760 bars → ~44 requests
4h: 365일 = 2190 bars → ~11 requests

Rate limit: 20 req/sec (public), sleep 0.15s between requests.
"""
from __future__ import annotations

import json
import time
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone, timedelta

HIST_DIR = Path(__file__).resolve().parent.parent / "quant_runtime" / "historical"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
TIMEFRAMES = {
    "1h": {"granularity": "1h", "ms": 3600_000, "target_days": 365},
    "4h": {"granularity": "4h", "ms": 14400_000, "target_days": 365},
}
LIMIT = 1000  # Binance max per request


def fetch_klines_binance(symbol: str, interval: str, end_ms: int, limit: int = LIMIT) -> list[dict]:
    """Fetch klines from Binance public API (no key needed). Up to 1000 per request."""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&endTime={end_ms}&limit={limit}"

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "quant-history-fetch/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                rows = json.loads(resp.read().decode("utf-8"))
            candles = []
            for row in rows:
                candles.append({
                    "open_time": int(row[0]),
                    "open_price": float(row[1]),
                    "high_price": float(row[2]),
                    "low_price": float(row[3]),
                    "close_price": float(row[4]),
                    "base_volume": float(row[5]),
                    "quote_volume": float(row[7]),  # Binance: index 7 = quote asset volume
                })
            return candles
        except Exception as e:
            print(f"    Request failed (attempt {attempt+1}): {e}")
            time.sleep(2)
    return []


def fetch_full_history(symbol: str, tf: str, config: dict) -> list[dict]:
    """Fetch full history by paginating backwards."""
    granularity = config["granularity"]
    bar_ms = config["ms"]
    target_days = config["target_days"]
    target_bars = target_days * 24 * 3600_000 // bar_ms

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    end_ms = now_ms
    all_candles = []
    seen_times = set()

    print(f"  {symbol}/{tf}: fetching ~{target_bars} bars...", end="", flush=True)

    while len(all_candles) < target_bars:
        candles = fetch_klines_binance(symbol, granularity, end_ms)
        if not candles:
            print(f" [stopped at {len(all_candles)} bars, no more data]")
            break

        new_count = 0
        for c in candles:
            if c["open_time"] not in seen_times:
                seen_times.add(c["open_time"])
                all_candles.append(c)
                new_count += 1

        if new_count == 0:
            print(f" [stopped at {len(all_candles)} bars, no new data]")
            break

        # Move end_ms to oldest candle - 1ms
        oldest = min(c["open_time"] for c in candles)
        end_ms = oldest - 1

        print(".", end="", flush=True)
        time.sleep(0.2)  # rate limit

    # Sort by time ascending
    all_candles.sort(key=lambda c: c["open_time"])

    # Deduplicate
    final = []
    seen = set()
    for c in all_candles:
        if c["open_time"] not in seen:
            seen.add(c["open_time"])
            final.append(c)

    if final:
        t0 = datetime.fromtimestamp(final[0]["open_time"]/1000, tz=timezone.utc)
        t1 = datetime.fromtimestamp(final[-1]["open_time"]/1000, tz=timezone.utc)
        days = (t1 - t0).days
        print(f" {len(final)} bars, {t0.strftime('%Y-%m-%d')} ~ {t1.strftime('%Y-%m-%d')} ({days}d)")
    else:
        print(" 0 bars")

    return final


def main():
    print("=" * 80)
    print("Extended Historical Data Fetch — Bitget Public API")
    print(f"Target: {TIMEFRAMES['1h']['target_days']} days, Symbols: {', '.join(SYMBOLS)}")
    print("=" * 80)

    for sym in SYMBOLS:
        sym_dir = HIST_DIR / sym
        sym_dir.mkdir(parents=True, exist_ok=True)

        for tf, config in TIMEFRAMES.items():
            candles = fetch_full_history(sym, tf, config)
            if not candles:
                continue

            out_path = sym_dir / f"{tf}.json"

            # If existing data, merge
            if out_path.exists():
                with open(out_path) as f:
                    existing = json.load(f)
                existing_times = {c["open_time"] for c in existing}
                new_count = 0
                for c in candles:
                    if c["open_time"] not in existing_times:
                        existing.append(c)
                        new_count += 1
                existing.sort(key=lambda c: c["open_time"])
                candles = existing
                print(f"    Merged {new_count} new bars with {len(existing)-new_count} existing")

            with open(out_path, "w") as f:
                json.dump(candles, f)
            print(f"    Saved: {out_path} ({len(candles)} bars)")

    # Summary
    print(f"\n{'=' * 80}")
    print("SUMMARY")
    print(f"{'=' * 80}")
    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            path = HIST_DIR / sym / f"{tf}.json"
            if path.exists():
                with open(path) as f:
                    data = json.load(f)
                if data:
                    t0 = datetime.fromtimestamp(data[0]["open_time"]/1000, tz=timezone.utc)
                    t1 = datetime.fromtimestamp(data[-1]["open_time"]/1000, tz=timezone.utc)
                    print(f"  {sym}/{tf}: {len(data)} bars, {t0.strftime('%Y-%m-%d')} ~ {t1.strftime('%Y-%m-%d')} ({(t1-t0).days}d)")


if __name__ == "__main__":
    main()
