"""ETH/SOL/DOGE/PEPE 5m klines fetch (사용자 실제 운용 universe)."""
import json, time, urllib.request
from pathlib import Path
from datetime import datetime, timezone

OUT = Path.home() / "Desktop" / "first_repo" / "quant_runtime" / "historical_5m"

# 사용자 실제 winners universe + 1000PEPE for perp accuracy
SYMBOLS = ["ETHUSDT", "SOLUSDT", "DOGEUSDT", "PEPEUSDT"]

START_MS = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
END_MS = int(datetime(2026, 4, 28, tzinfo=timezone.utc).timestamp() * 1000)
MIN5_MS = 5 * 60 * 1000
BASE = "https://api.binance.com/api/v3/klines"


def fetch(symbol):
    out_dir = OUT / symbol; out_dir.mkdir(parents=True, exist_ok=True)
    out_p = out_dir / "5m.json"
    if out_p.exists(): return len(json.loads(out_p.read_text()))
    bars = []; cur = START_MS
    while cur < END_MS:
        url = f"{BASE}?symbol={symbol}&interval=5m&startTime={cur}&limit=1000"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                chunk = json.loads(r.read())
        except Exception:
            time.sleep(1); continue
        if not chunk: break
        for b in chunk:
            ts = b[0]
            if ts >= END_MS: break
            bars.append({
                "open_time": ts,
                "open_price": float(b[1]),
                "high_price": float(b[2]),
                "low_price": float(b[3]),
                "close_price": float(b[4]),
                "base_volume": float(b[5]),
                "quote_volume": float(b[7]),
            })
        last = chunk[-1][0]
        if last >= END_MS - MIN5_MS: break
        cur = last + MIN5_MS
        time.sleep(0.05)
    if bars:
        bars.sort(key=lambda x: x["open_time"])
        out_p.write_text(json.dumps(bars))
    return len(bars)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for i, sym in enumerate(SYMBOLS, 1):
        try:
            n = fetch(sym)
            print(f"[{i}/{len(SYMBOLS)}] {sym}: {n} bars (~{n/12/24:.0f} days)")
        except Exception as e:
            print(f"[{i}/{len(SYMBOLS)}] {sym}: FAIL {e}")
