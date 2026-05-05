"""
fetch_hyperliquid_traders.py

PB105 — Hyperliquid Top Trader Mirror PoC: Step 1-3 (data acquisition).

Pulls public on-chain data from Hyperliquid Info API:
  - clearinghouseState  : current equity + open positions per address
  - userFillsByTime     : 30-day fill history (paginated by time window)

KNOWN LIMITATION (verified 2026-04-28):
  Hyperliquid's public /info endpoint does NOT expose a `leaderboard` route.
  Tested payloads {type: leaderboard|leaderBoard|topPositions} all return HTTP 422.
  Address discovery therefore depends on:
    (a) hard-coded candidates from public X / HypurrScan / Coinglass references, OR
    (b) external scraping of coinglass.com/hyperliquid (out of scope for PoC)

Output:
  quant_binance/strategies/_playbook/PB105_hyperliquid_leaderboard_mirror/data/
      addresses.json   — verified non-zero addresses + equity snapshot
      fills_<addr>.json — 30-day fills per address (capped at 2000 per API call,
                          so we paginate by sliding window)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

API = "https://api.hyperliquid.xyz/info"
OUT_DIR = Path(__file__).resolve().parents[1] / "_playbook" / \
    "PB105_hyperliquid_leaderboard_mirror" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# --- Candidate wallet pool ----------------------------------------------------
# These are addresses publicly cited on X / HypurrScan / Coinglass discussions
# of Hyperliquid leaderboard activity. We probe each, keep only ones with
# non-trivial equity AND directional fill pattern (filter applied downstream).
CANDIDATE_ADDRESSES = [
    "0x8cc94dc843e1ea7a19805e0cca43001123512b6a",  # active alt-rotator (~$6.6M)
    "0x010461c14e146ac35fe42271bdc1134ee31c703a",  # large account ($113M, MM-like)
    "0xd11f5de0189d52b3abe6b0960b8377c20988e17e",
    "0xa39d20f6a7f32b56bc32e0094a9a64f1e9a9aafb",
    "0x7d3ca5fa94383b22ee49fc14e89aa417f65b4d3a",
    "0xf3f496c9486be5924a93d67e98298733bb47057c",
    "0x1ab189b7801140900c711e458212f9c76f8dac79",
    "0x52a258ed593c793251a89bfd36cae158ee9fc4f8",
    "0xfcc863f9e58ecdc46dffae0f9ce9e8b5cc2c97f0",
    "0x77c3ea550d2da44b120e55071f57a108f8dd7f56",
    "0x39773f4e3c8ec55c9e43cf8fc7b03d10faaff91d",
    "0xacc3f2a1adfa72e7e0d3e3a9bbe9a5b44e6d3b16",
    "0x4a8c9ad10aa80b8fbf7e9b1d6dac7f50ca9a02b1",
    "0xc22f7059bb33eb893fe9b1cd1a4d0e1ce17f7d10",
    "0x6f6d57a1283bda356c9d2f8e0b7e5fbdc60f7e8d",
]


def post(payload: dict, timeout: int = 30) -> dict | list:
    req = urllib.request.Request(
        API,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def get_state(addr: str) -> dict:
    return post({"type": "clearinghouseState", "user": addr})


def fetch_fills_30d(addr: str, days: int = 30, max_pages: int = 30) -> list[dict]:
    """API caps at 2000 fills per call. Paginate via sliding endTime backwards.

    Returns fills in [now-days, now], capped at max_pages * 2000 to bound runtime.
    For directional traders (low fph) one page typically covers the full window.
    For MMs we hit the cap and stop after max_pages.
    """
    end = int(time.time() * 1000)
    start = end - days * 24 * 3600 * 1000
    all_fills: list[dict] = []
    cursor = end
    seen_tids: set[int] = set()
    for _ in range(max_pages):
        try:
            chunk = post({
                "type": "userFillsByTime",
                "user": addr,
                "startTime": start,
                "endTime": cursor,
            })
        except Exception as e:
            print(f"  fetch error @ cursor={cursor}: {e}", file=sys.stderr)
            break
        if not chunk:
            break
        new = [f for f in chunk if f["tid"] not in seen_tids]
        for f in new:
            seen_tids.add(f["tid"])
        all_fills.extend(new)
        if len(chunk) < 2000:
            break
        oldest = min(f["time"] for f in chunk)
        if oldest <= start:
            break
        if cursor == oldest - 1:  # no progress
            break
        cursor = oldest - 1
        time.sleep(0.25)
    return sorted(all_fills, key=lambda f: f["time"])


def directional_score(fills: list[dict]) -> dict:
    """Heuristic: non-MM directional traders have moderate fill rate
    AND substantial Open->Close cycles (not just delta-hedging)."""
    if not fills:
        return {"score": 0, "trades_per_hour": 0, "n": 0}
    span_h = (fills[-1]["time"] - fills[0]["time"]) / 3600000
    span_h = max(span_h, 1e-9)
    fph = len(fills) / span_h
    opens = sum(1 for f in fills if f["dir"].startswith("Open"))
    closes = sum(1 for f in fills if f["dir"].startswith("Close"))
    flips = sum(1 for f in fills if ">" in f["dir"])
    open_ratio = opens / max(opens + closes + flips, 1)
    # MM-like: hundreds-to-thousands of fills/hour. Directional: <60/hour.
    is_directional = 0.05 < fph < 60 and 0.20 < open_ratio < 0.80
    return {
        "n": len(fills),
        "span_h": round(span_h, 2),
        "trades_per_hour": round(fph, 3),
        "open_ratio": round(open_ratio, 3),
        "directional": bool(is_directional),
    }


def main() -> None:
    discovered: list[dict] = []
    print(f"Probing {len(CANDIDATE_ADDRESSES)} candidate addresses...")
    for addr in CANDIDATE_ADDRESSES:
        try:
            state = get_state(addr)
        except Exception as e:
            print(f"  {addr} state error: {e}")
            continue
        eq = float(state.get("marginSummary", {}).get("accountValue", 0))
        npos = len(state.get("assetPositions", []))
        if eq < 1000:
            continue
        print(f"  {addr} eq=${eq:>14,.0f}  pos={npos:>4}  -> fetching 30d fills...")
        fills = fetch_fills_30d(addr, days=30)
        meta = directional_score(fills)
        info = {
            "address": addr,
            "equity_usd": eq,
            "open_positions": npos,
            "fills_30d": len(fills),
            "meta": meta,
        }
        print(f"    fills={len(fills)} fph={meta['trades_per_hour']} dir={meta['directional']}")
        discovered.append(info)
        # save fills
        with open(OUT_DIR / f"fills_{addr}.json", "w") as f:
            json.dump(fills, f)
        time.sleep(0.5)

    with open(OUT_DIR / "addresses.json", "w") as f:
        json.dump(discovered, f, indent=2)

    n_dir = sum(1 for d in discovered if d["meta"]["directional"])
    print(f"\nResult: {len(discovered)} non-zero addresses, "
          f"{n_dir} pass directional filter.")
    print(f"Saved to {OUT_DIR}")


if __name__ == "__main__":
    main()
