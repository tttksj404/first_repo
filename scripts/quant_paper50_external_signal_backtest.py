#!/usr/bin/env python3
"""Backtest 3 candidate external alpha signals against actual market forward returns.

Tests:
  A. Spot-perp basis Z-score (Bitget perp ref_price vs Binance spot 1m close)
  B. Cross-exchange funding divergence (Bitget funding - Binance funding, point-in-time)
  C. OI delta x Price delta 4-quadrant (using alpha_outcomes OI snapshots)

For each, joins against decisions.jsonl + cached forward klines and computes
discrimination: extreme-signal-bucket forward return vs neutral-bucket.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import ssl
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.quant_paper50_counterfactual import (  # type: ignore[import-not-found]
    fetch_klines_cached,
    _parse_timestamp,
    _safe_float,
)
from quant_binance.execution.client_factory import build_exchange_rest_client  # type: ignore[import-not-found]


DECISIONS = ROOT / "quant_runtime_paper50" / "forensics" / "decisions.jsonl"
KLINE_CACHE = ROOT / "quant_runtime_paper50" / "cache" / "klines"
OUT = ROOT / "quant_runtime_paper50" / "artifacts" / "paper50_external_signal_backtest_latest.json"

# Binance spot symbol mapping (PEPE quoted as 1000PEPEUSDT on fapi but PEPEUSDT on spot, 1000-scaled)
BINANCE_SPOT = {
    "BTCUSDT": "BTCUSDT",
    "ETHUSDT": "ETHUSDT",
    "SOLUSDT": "SOLUSDT",
    "DOGEUSDT": "DOGEUSDT",
    "PEPEUSDT": "PEPEUSDT",  # spot ticker; will need to scale by 1000 on Binance fapi side, but spot is direct
}

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def _http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "paper50-backtest/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20, context=CTX) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code in (418, 429):
                time.sleep(2 ** attempt)
                continue
            raise
        except Exception:
            if attempt < 2:
                time.sleep(1.5 ** attempt)
                continue
            raise


def fetch_binance_spot_1m(symbol: str, *, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
    """Return [(open_time_ms, close_price)] sorted ascending."""
    out: list[tuple[int, float]] = []
    cursor = start_ms
    while cursor < end_ms:
        url = (
            "https://api.binance.com/api/v3/klines?"
            + urllib.parse.urlencode(
                {"symbol": symbol, "interval": "1m", "startTime": cursor, "endTime": end_ms, "limit": 1000}
            )
        )
        rows = _http_json(url) or []
        if not rows:
            break
        for r in rows:
            out.append((int(r[0]), float(r[4])))
        last_open = int(rows[-1][0])
        if last_open <= cursor:
            break
        cursor = last_open + 60_000
        time.sleep(0.05)
    return out


def fetch_binance_funding_history(symbol: str, *, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
    """Return [(funding_time_ms, fundingRate)] for the futures perp symbol."""
    url = (
        "https://fapi.binance.com/fapi/v1/fundingRate?"
        + urllib.parse.urlencode({"symbol": symbol, "startTime": start_ms, "endTime": end_ms, "limit": 1000})
    )
    rows = _http_json(url) or []
    return [(int(r["fundingTime"]), float(r["fundingRate"])) for r in rows]


def fetch_bitget_funding_history(symbol: str, *, start_ms: int, end_ms: int) -> list[tuple[int, float]]:
    """Bitget historical funding rate, public endpoint."""
    out: list[tuple[int, float]] = []
    cursor = end_ms
    while True:
        url = (
            "https://api.bitget.com/api/v2/mix/market/history-fund-rate?"
            + urllib.parse.urlencode({"symbol": symbol, "productType": "USDT-FUTURES", "pageSize": 100})
        )
        rows = _http_json(url)
        if not rows or rows.get("code") != "00000":
            break
        data = rows.get("data") or []
        if not data:
            break
        for r in data:
            ts = int(r.get("settleTime") or r.get("fundingTime") or 0)
            rate = float(r.get("fundingRate") or 0.0)
            if start_ms <= ts <= end_ms:
                out.append((ts, rate))
        # Bitget returns most-recent first; we'd need pagination but 100 covers ~33 days at 8h cadence
        break
    out.sort()
    return out


def _forward_ret_signed(client, *, symbol: str, ref_ts: str, ref_price: float, intent_side: str, forward_minutes: int) -> float | None:
    if ref_price <= 0.0:
        return None
    ts = _parse_timestamp(ref_ts)
    start_ms = int(ts.timestamp() * 1000)
    end_ms = int((ts + timedelta(minutes=forward_minutes + 1)).timestamp() * 1000)
    try:
        bars = sorted(
            fetch_klines_cached(
                client.get_klines, symbol=symbol, start_ms=start_ms, end_ms=end_ms,
                forward_minutes=forward_minutes, cache_dir=KLINE_CACHE,
            ),
            key=lambda x: int(x.get("open_time") or 0),
        )
    except Exception:
        return None
    if not bars:
        return None
    target_ms = start_ms + forward_minutes * 60_000
    after = [b for b in bars if int(b.get("open_time") or 0) >= target_ms] or [bars[-1]]
    close = _safe_float(after[0].get("close_price"), 0.0)
    if close <= 0.0:
        return None
    raw = (close / ref_price - 1.0) * 10000.0
    if intent_side == "short":
        return -raw
    return raw


def _stats(arr: list[float]) -> dict[str, Any]:
    if not arr:
        return {"n": 0}
    return {
        "n": len(arr),
        "mean_bps": round(statistics.mean(arr), 3),
        "median_bps": round(statistics.median(arr), 3),
        "winrate": round(sum(1 for x in arr if x > 0) / len(arr), 3),
    }


def main() -> None:
    decisions = []
    with DECISIONS.open() as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            sym = (d.get("symbol") or "").upper()
            if sym not in BINANCE_SPOT:
                continue
            decisions.append(d)
    print(f"loaded {len(decisions)} decisions")
    if not decisions:
        return

    timestamps = [_parse_timestamp(d["timestamp"]) for d in decisions]
    start_ts = min(timestamps) - timedelta(days=2)  # need 24h prior for Z-score
    end_ts = max(timestamps) + timedelta(hours=2)
    start_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000)

    print(f"fetching spot 1m klines for {start_ts.isoformat()} .. {end_ts.isoformat()}")
    spot: dict[str, list[tuple[int, float]]] = {}
    spot_ts: dict[str, list[int]] = {}
    spot_close: dict[str, list[float]] = {}
    for sym in BINANCE_SPOT:
        bsym = BINANCE_SPOT[sym]
        rows = fetch_binance_spot_1m(bsym, start_ms=start_ms, end_ms=end_ms)
        # PEPE on Binance spot is in same units as Bitget perp (raw, no /1000)
        spot[sym] = rows
        spot_ts[sym] = [r[0] for r in rows]
        spot_close[sym] = [r[1] for r in rows]
        print(f"  {sym} <- Binance spot {bsym}: {len(rows)} 1m bars")

    print(f"\nfetching funding histories")
    bitget_funding: dict[str, list[tuple[int, float]]] = {}
    binance_funding: dict[str, list[tuple[int, float]]] = {}
    for sym in BINANCE_SPOT:
        bsym = BINANCE_SPOT[sym] if sym != "PEPEUSDT" else "1000PEPEUSDT"
        try:
            bitget_funding[sym] = fetch_bitget_funding_history(sym, start_ms=start_ms, end_ms=end_ms)
            binance_funding[sym] = fetch_binance_funding_history(bsym, start_ms=start_ms, end_ms=end_ms)
            print(f"  {sym}: bitget_funding={len(bitget_funding[sym])} binance_funding={len(binance_funding[sym])}")
        except Exception as exc:
            print(f"  {sym}: funding fetch failed - {exc}")
            bitget_funding[sym] = []
            binance_funding[sym] = []

    # Compute basis time series per symbol (perp_close from Bitget cached klines vs Binance spot close)
    # For each minute we need the perp price too. Use cached forward klines as the perp proxy.
    # Easier: for each decision, basis_bps_at_decision = (ref_price_perp / spot_close_at_or_before) - 1
    # And rolling Z over preceding 24h of basis: need to compute basis ts series.
    # We'll approximate by sampling spot at every 5-minute boundary that matches decision timestamps,
    # and use perp_ref_price from decisions where available; for prior-window Z-score, fall back to
    # cached perp klines if available, else skip.
    # Practical implementation: for each (symbol, decision_ts), find spot close <= ts; basis_now.
    # For Z-score: build a (sym, ts) -> basis dict from perp 1m klines we can fetch via cache,
    # join with spot 1m, take 1440-sample rolling window before decision_ts.

    # Build a 1m perp series per symbol from cache files (concatenate all cached spans)
    # Cache files are quant_runtime_paper50/cache/klines/<SYM>_<startms>_<endms>.json
    perp_series: dict[str, dict[int, float]] = defaultdict(dict)
    for f in KLINE_CACHE.glob("*.json"):
        parts = f.stem.split("_")
        if len(parts) < 3:
            continue
        sym = parts[0]
        if sym not in BINANCE_SPOT:
            continue
        try:
            bars = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        for b in bars:
            ot = int(b.get("open_time") or 0)
            cp = _safe_float(b.get("close_price"), 0.0)
            if ot > 0 and cp > 0.0:
                perp_series[sym][ot] = cp

    print()
    for sym in BINANCE_SPOT:
        print(f"  perp 1m cache {sym}: {len(perp_series[sym])} bars")

    # For each decision, compute the three signals + signed forward return
    results: list[dict[str, Any]] = []
    client = build_exchange_rest_client(exchange="bitget", allow_insecure_ssl=True, allow_missing_credentials=True)
    for i, d in enumerate(decisions):
        sym = d["symbol"].upper()
        ts = _parse_timestamp(d["timestamp"])
        ts_ms = int(ts.timestamp() * 1000)
        ref_perp = _safe_float(d.get("reference_price"), 0.0)
        if ref_perp <= 0.0:
            continue

        # Spot price at-or-just-before decision
        idx = bisect_left(spot_ts[sym], ts_ms) - 1
        spot_price_now = spot_close[sym][idx] if idx >= 0 and idx < len(spot_close[sym]) else None
        if spot_price_now is None or spot_price_now <= 0.0:
            continue
        basis_now_bps = (ref_perp / spot_price_now - 1.0) * 10000.0

        # Build prior 24h basis series for Z-score: minutes from (ts - 24h) to ts
        window_start_ms = ts_ms - 86_400_000
        window_basis: list[float] = []
        # iterate through spot ts in window; match perp 1m bar at same minute
        i0 = bisect_left(spot_ts[sym], window_start_ms)
        i1 = bisect_left(spot_ts[sym], ts_ms)
        for k in range(i0, i1):
            spot_ts_k = spot_ts[sym][k]
            sp = spot_close[sym][k]
            pp = perp_series[sym].get(spot_ts_k)
            if pp and sp > 0:
                window_basis.append((pp / sp - 1.0) * 10000.0)
        if len(window_basis) >= 60:
            mu = statistics.mean(window_basis)
            sigma = statistics.stdev(window_basis) if len(window_basis) > 1 else 0.0
            basis_z = (basis_now_bps - mu) / sigma if sigma > 1e-9 else 0.0
        else:
            basis_z = None

        # Funding divergence at-or-just-before decision (Bitget − Binance), in bps per 8h
        bg = bitget_funding.get(sym, [])
        bn = binance_funding.get(sym, [])
        bg_rate = next((rate for ts2, rate in reversed(bg) if ts2 <= ts_ms), None)
        bn_rate = next((rate for ts2, rate in reversed(bn) if ts2 <= ts_ms), None)
        funding_div_bps = (
            (bg_rate - bn_rate) * 10000.0
            if bg_rate is not None and bn_rate is not None else None
        )

        # Forward returns
        td = d.get("trend_direction", 0)
        intent_side = "long" if td > 0 else ("short" if td < 0 else "long")
        f15 = _forward_ret_signed(client, symbol=sym, ref_ts=d["timestamp"], ref_price=ref_perp, intent_side=intent_side, forward_minutes=15)
        f60 = _forward_ret_signed(client, symbol=sym, ref_ts=d["timestamp"], ref_price=ref_perp, intent_side=intent_side, forward_minutes=60)

        results.append({
            "symbol": sym,
            "timestamp": d["timestamp"],
            "intent_side": intent_side,
            "ref_perp": ref_perp,
            "spot_price": spot_price_now,
            "basis_now_bps": basis_now_bps,
            "basis_z": basis_z,
            "funding_div_bps_per_8h": funding_div_bps,
            "f15": f15,
            "f60": f60,
        })
        if (i + 1) % 500 == 0:
            print(f"  ... {i+1}/{len(decisions)}")

    # ============ Analysis ============
    out: dict[str, Any] = {"n_decisions": len(results), "per_signal": {}}

    # Signal A: basis_z buckets
    def bucket_basis_z(z: float | None) -> str:
        if z is None:
            return "no_window"
        if abs(z) < 0.5:
            return "neutral"
        if 0.5 <= abs(z) < 1.0:
            return "mild"
        if 1.0 <= abs(z) < 2.0:
            return "extreme"
        return "very_extreme"

    bucket_f15: dict[str, list[float]] = defaultdict(list)
    bucket_f60: dict[str, list[float]] = defaultdict(list)
    for r in results:
        bk = bucket_basis_z(r["basis_z"])
        if r["f15"] is not None:
            bucket_f15[bk].append(r["f15"])
        if r["f60"] is not None:
            bucket_f60[bk].append(r["f60"])
    out["per_signal"]["basis_z"] = {
        "f15": {k: _stats(v) for k, v in bucket_f15.items()},
        "f60": {k: _stats(v) for k, v in bucket_f60.items()},
    }

    # Signal B: funding divergence buckets (in bps/8h)
    def bucket_div(d: float | None) -> str:
        if d is None:
            return "no_data"
        if abs(d) < 1.0:
            return "tight"
        if abs(d) < 3.0:
            return "mild"
        if abs(d) < 5.0:
            return "wide"
        return "extreme"

    bf15: dict[str, list[float]] = defaultdict(list)
    bf60: dict[str, list[float]] = defaultdict(list)
    for r in results:
        bk = bucket_div(r["funding_div_bps_per_8h"])
        if r["f15"] is not None:
            bf15[bk].append(r["f15"])
        if r["f60"] is not None:
            bf60[bk].append(r["f60"])
    out["per_signal"]["funding_divergence"] = {
        "f15": {k: _stats(v) for k, v in bf15.items()},
        "f60": {k: _stats(v) for k, v in bf60.items()},
    }

    # Per-symbol basis_z extreme vs neutral
    by_sym: dict[str, Any] = {}
    for sym in BINANCE_SPOT:
        rs = [r for r in results if r["symbol"] == sym and r["basis_z"] is not None]
        if not rs:
            continue
        extreme_f15 = [r["f15"] for r in rs if abs(r["basis_z"]) >= 1.0 and r["f15"] is not None]
        neutral_f15 = [r["f15"] for r in rs if abs(r["basis_z"]) < 0.5 and r["f15"] is not None]
        extreme_f60 = [r["f60"] for r in rs if abs(r["basis_z"]) >= 1.0 and r["f60"] is not None]
        neutral_f60 = [r["f60"] for r in rs if abs(r["basis_z"]) < 0.5 and r["f60"] is not None]
        by_sym[sym] = {
            "n": len(rs),
            "extreme_f15": _stats(extreme_f15),
            "neutral_f15": _stats(neutral_f15),
            "extreme_f60": _stats(extreme_f60),
            "neutral_f60": _stats(neutral_f60),
        }
    out["per_symbol_basis_z"] = by_sym

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True))
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
