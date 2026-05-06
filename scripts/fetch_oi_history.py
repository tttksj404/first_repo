"""Fetch 1-year hourly OI data from Bybit public API for backtest symbols."""
import json, subprocess, time, sys
from pathlib import Path
from datetime import datetime, timezone

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
OUT_DIR = Path("quant_runtime/historical")
INTERVAL = "1h"
LIMIT = 200  # max per request

# Match our 1h.json date range: 2025-03-25 to 2026-04-04
START_TS = 1742911200000  # 2025-03-25 14:00 UTC
END_TS   = 1775307600000  # 2026-04-04 13:00 UTC


def fetch_page(symbol, cursor=""):
    url = f"https://api.bybit.com/v5/market/open-interest?category=linear&symbol={symbol}&intervalTime={INTERVAL}&limit={LIMIT}"
    if cursor:
        url += f"&cursor={cursor}"
    cmd = ["curl", "-s", url]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return json.loads(result.stdout)


def fetch_all_oi(symbol):
    all_data = []
    cursor = ""
    pages = 0

    # Start from most recent, paginate backwards
    while True:
        data = fetch_page(symbol, cursor)
        if data.get("retCode") != 0:
            print(f"  ERROR: {data.get('retMsg')}")
            break

        records = data.get("result", {}).get("list", [])
        if not records:
            break

        for r in records:
            ts = int(r["timestamp"])
            if ts < START_TS:
                all_data.extend(records)
                print(f"  Reached start date, stopping")
                break
            all_data.append(r)
        else:
            cursor = data.get("result", {}).get("nextPageCursor", "")
            if not cursor:
                break
            pages += 1
            if pages % 10 == 0:
                oldest_ts = int(records[-1]["timestamp"])
                oldest_dt = datetime.fromtimestamp(oldest_ts / 1000, tz=timezone.utc)
                print(f"  {symbol}: {len(all_data)} records, oldest: {oldest_dt.strftime('%Y-%m-%d')}", flush=True)
            time.sleep(0.15)  # rate limit
            continue
        break

    # Filter to our date range and sort by timestamp ascending
    filtered = []
    seen = set()
    for r in all_data:
        ts = int(r["timestamp"])
        if START_TS <= ts <= END_TS and ts not in seen:
            seen.add(ts)
            filtered.append({
                "timestamp": ts,
                "open_interest": float(r["openInterest"]),
            })
    filtered.sort(key=lambda x: x["timestamp"])
    return filtered


def main():
    print(f"Fetching OI history: {', '.join(SYMBOLS)}")
    print(f"Range: {datetime.fromtimestamp(START_TS/1000, tz=timezone.utc)} to {datetime.fromtimestamp(END_TS/1000, tz=timezone.utc)}")

    for sym in SYMBOLS:
        print(f"\n{sym}:", flush=True)
        oi_data = fetch_all_oi(sym)

        out_path = OUT_DIR / sym / "oi_1h.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        json.dump(oi_data, open(out_path, "w"))

        if oi_data:
            first_dt = datetime.fromtimestamp(oi_data[0]["timestamp"] / 1000, tz=timezone.utc)
            last_dt = datetime.fromtimestamp(oi_data[-1]["timestamp"] / 1000, tz=timezone.utc)
            print(f"  Saved {len(oi_data)} records: {first_dt.strftime('%Y-%m-%d')} to {last_dt.strftime('%Y-%m-%d')}")
        else:
            print(f"  No data!")

    print("\nDone!")


if __name__ == "__main__":
    main()
