"""Fetch ~365 days of 1h klines for BTC + 15-coin alt universe via Binance public API.
Saves to verify_btc_timing/data/{symbol}.json (list of [open_time, o, h, l, c, v]).
"""
import json
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).parent / "data"
OUT.mkdir(parents=True, exist_ok=True)

UNIVERSE = ['BTCUSDT', 'DOGEUSDT', 'PEPEUSDT', 'ARBUSDT', 'OPUSDT',
            'AVAXUSDT', 'SUIUSDT', 'ADAUSDT', 'APTUSDT', 'BNBUSDT',
            'DOTUSDT', 'LINKUSDT', 'NEARUSDT', 'SOLUSDT', 'UNIUSDT', 'XRPUSDT']

DAYS = 365
BARS_NEEDED = DAYS * 24
BASE = "https://api.binance.com/api/v3/klines"

def fetch_all(symbol):
    all_bars = []
    end_time = int(time.time() * 1000)
    while len(all_bars) < BARS_NEEDED:
        url = f"{BASE}?symbol={symbol}&interval=1h&endTime={end_time}&limit=1000"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                chunk = json.loads(r.read())
        except Exception as e:
            print(f"  {symbol} fetch err: {e}")
            time.sleep(2)
            continue
        if not chunk:
            break
        # chunk is sorted oldest -> newest
        all_bars = chunk + all_bars
        # next end = first bar's open_time - 1
        end_time = chunk[0][0] - 1
        if len(chunk) < 1000:
            break  # reached start
        time.sleep(0.15)  # rate limit gentle
    # dedupe by open_time
    seen = set()
    out = []
    for b in all_bars:
        if b[0] in seen:
            continue
        seen.add(b[0])
        # keep only [open_time, o, h, l, c, v]
        out.append([b[0], float(b[1]), float(b[2]), float(b[3]), float(b[4]), float(b[5])])
    out.sort(key=lambda x: x[0])
    return out[-BARS_NEEDED:]

for sym in UNIVERSE:
    target = OUT / f"{sym}.json"
    if target.exists():
        existing = json.loads(target.read_text())
        if len(existing) >= BARS_NEEDED * 0.95:
            print(f"{sym}: cached {len(existing)} bars - skip")
            continue
    print(f"{sym}: fetching...")
    bars = fetch_all(sym)
    target.write_text(json.dumps(bars))
    print(f"  saved {len(bars)} bars  range {bars[0][0]} -> {bars[-1][0]}")

print("DONE")
