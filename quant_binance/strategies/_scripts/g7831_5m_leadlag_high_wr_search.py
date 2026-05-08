"""Chunk-safe 5m lead/lag high-WR search.

Uses only locally available 5m data:
- DOGEUSDT, ETHUSDT, PEPEUSDT, SOLUSDT
- 2024-01-01 through 2026-04-27

The purpose is to try a genuinely different alpha source from 1h breakout:
cross-asset lead/lag on short timeframes.
"""
from __future__ import annotations

import heapq
import argparse
import json
import math
import time
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "quant_runtime" / "historical_5m"
SCRIPTS = ROOT / "quant_binance" / "strategies" / "_scripts"
OUT = SCRIPTS / "g7831_5m_leadlag_high_wr_search_results.json"

SYMBOLS = ["ETHUSDT", "SOLUSDT", "DOGEUSDT", "PEPEUSDT"]
EQUITY = 100.0
COST = 0.0010  # 10 bps round-trip
TOTAL_DAYS = 365 + 365 + 117


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--chunk-index", type=int, default=0, help="0-based chunk index to run")
    p.add_argument("--chunk-count", type=int, default=1, help="total chunks in the full grid")
    p.add_argument("--top-limit", type=int, default=300, help="top rows to keep per output")
    p.add_argument("--max-seconds", type=float, default=None, help="optional soft time budget; writes partial output before exiting")
    p.add_argument("--merge", action="store_true", help="merge completed chunk outputs into the canonical result file")
    return p.parse_args()


def chunk_out_path(chunk_index: int, chunk_count: int) -> Path:
    if chunk_count <= 1:
        return OUT
    return OUT.with_name(f"{OUT.stem}_chunk_{chunk_index:03d}_of_{chunk_count:03d}{OUT.suffix}")


def iter_chunked_product(chunk_index: int, chunk_count: int):
    if chunk_count < 1:
        raise ValueError("--chunk-count must be >= 1")
    if chunk_index < 0 or chunk_index >= chunk_count:
        raise ValueError("--chunk-index must be in [0, chunk_count)")
    grid = product(
        SYMBOLS,
        SYMBOLS,
        ["follow", "revert", "same_confirm"],
        [3, 6, 12],
        [1, 3],
        [0.004, 0.006, 0.008, 0.012, 0.018],
        [0.002, 0.004, 0.006, 0.010],
        [3, 6, 9, 12],
        [0.004, 0.006, 0.008, 0.012],
        [0.006, 0.010, 0.015, 0.020],
    )
    for raw_i, combo in enumerate(grid):
        if raw_i % chunk_count == chunk_index:
            yield raw_i, combo


def merge_chunks(chunk_count: int, top_limit: int) -> None:
    chunks = [chunk_out_path(i, chunk_count) for i in range(chunk_count)]
    missing = [str(p) for p in chunks if not p.exists()]
    if missing:
        raise FileNotFoundError(f"missing chunk outputs: {missing[:5]}{'...' if len(missing) > 5 else ''}")
    top_heap: list[tuple[float, int, dict[str, Any]]] = []
    counter = 0
    n_specs = 0
    n_pass = 0
    elapsed = 0.0
    for path in chunks:
        payload = json.loads(path.read_text(encoding="utf-8"))
        n_specs += int(payload.get("n_specs_evaluated", 0))
        n_pass += int(payload.get("n_strict_pass", 0))
        elapsed += float(payload.get("elapsed_sec", 0.0))
        for row in payload.get("top", []):
            counter += 1
            push_top(top_heap, row, counter, top_limit)
    top = [item[2] for item in sorted(top_heap, key=lambda x: x[0], reverse=True)]
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": "Can 5m cross-asset lead/lag produce high-frequency high-WR alpha?",
        "coverage": "2024-01-01 through 2026-04-27, ETH/SOL/DOGE/PEPE 5m only",
        "chunk_count": chunk_count,
        "n_specs_evaluated": n_specs,
        "n_strict_pass": n_pass,
        "criteria": "tpm>=8, wr>=65%, pnl>0, all years positive, liq=0",
        "top": top,
        "elapsed_sec_sum": round(elapsed, 2),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"merged {chunk_count} chunks into {OUT}", flush=True)


def load_aligned() -> dict[str, pd.DataFrame]:
    raw = {}
    common: set[int] | None = None
    for sym in SYMBOLS:
        p = DATA / sym / "5m.json"
        df = pd.DataFrame(json.loads(p.read_text(encoding="utf-8"))).sort_values("open_time")
        for col in ["open_price", "high_price", "low_price", "close_price", "quote_volume"]:
            df[col] = df[col].astype(float)
        df["open_time"] = df["open_time"].astype("int64")
        raw[sym] = df
        ts = set(df["open_time"].tolist())
        common = ts if common is None else common & ts
    common_idx = sorted(common or [])
    out = {}
    for sym, df in raw.items():
        out[sym] = df[df["open_time"].isin(common_idx)].reset_index(drop=True)
    return out


def exit_return(df: pd.DataFrame, idx: int, side: str, hold: int, tp: float, sl: float, lev: float) -> tuple[float, bool]:
    if idx + hold >= len(df):
        return 0.0, False
    entry = float(df.at[idx, "close_price"])
    path = df.iloc[idx + 1 : idx + hold + 1]
    if entry <= 0 or len(path) == 0:
        return 0.0, False
    liq_move = 0.90 / lev
    raw = None
    for _, bar in path.iterrows():
        hi = float(bar["high_price"])
        lo = float(bar["low_price"])
        if side == "long":
            if lo <= entry * (1 - sl):
                raw = -sl
                break
            if lo / entry - 1 <= -liq_move:
                return -0.90, True
            if hi >= entry * (1 + tp):
                raw = tp
                break
        else:
            if hi >= entry * (1 + sl):
                raw = -sl
                break
            if hi / entry - 1 >= liq_move:
                return -0.90, True
            if lo <= entry * (1 - tp):
                raw = tp
                break
    if raw is None:
        exit_price = float(df.at[idx + hold, "close_price"])
        raw = exit_price / entry - 1 if side == "long" else entry / exit_price - 1
    return (raw - COST) * lev, False


def simulate(events: list[tuple[int, str, str, int]], dfs: dict[str, pd.DataFrame], spec: dict[str, Any]) -> dict[str, Any]:
    events = sorted(events)
    open_pos: list[tuple[int, str]] = []
    records = []
    for ts, follower, side, idx in events:
        open_pos = [p for p in open_pos if p[0] > ts]
        if any(p[1] == follower for p in open_pos):
            continue
        if len(open_pos) >= spec["max_conc"]:
            continue
        net, liq = exit_return(dfs[follower], idx, side, spec["hold"], spec["tp"], spec["sl"], spec["lev"])
        pnl = EQUITY * spec["size"] * net
        records.append({"ts": ts, "sym": follower, "side": side, "pnl": pnl, "win": pnl > 0, "liq": liq})
        open_pos.append((ts + spec["hold"] * 5 * 60 * 1000, follower))
    return summarize(records)


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_year = {}
    maxdd = 0.0
    for year in [2024, 2025, 2026]:
        rows = [r for r in records if pd.Timestamp(r["ts"], unit="ms", tz="UTC").year == year]
        curve = np.array([0.0] + list(np.cumsum([r["pnl"] for r in rows])), dtype=float)
        peak = np.maximum.accumulate(curve) if len(curve) else curve
        dd = float((peak - curve).max()) if len(curve) else 0.0
        maxdd = max(maxdd, dd)
        by_year[str(year)] = {
            "n": len(rows),
            "wr": round(sum(1 for r in rows if r["win"]) / max(len(rows), 1), 4),
            "pnl_usd": round(sum(r["pnl"] for r in rows), 2),
            "max_dd_usd": round(dd, 2),
        }
    n = len(records)
    pnl = sum(r["pnl"] for r in records)
    wins = sum(1 for r in records if r["win"])
    return {
        "n": n,
        "trades_per_month": round(n / TOTAL_DAYS * 30.4, 2),
        "wr": round(wins / max(n, 1), 4),
        "pnl_usd": round(pnl, 2),
        "annual_pnl_usd": round(pnl / TOTAL_DAYS * 365, 2),
        "liquidations": sum(1 for r in records if r["liq"]),
        "max_period_dd_usd": round(maxdd, 2),
        "min_year_pnl_usd": round(min(v["pnl_usd"] for v in by_year.values()), 2),
        "all_years_positive": all(v["pnl_usd"] > 0 for v in by_year.values()),
        "years": by_year,
    }


def event_candidates(dfs: dict[str, pd.DataFrame], spec: dict[str, Any]) -> list[tuple[int, str, str, int]]:
    leader = spec["leader"]
    follower = spec["follower"]
    ldf = dfs[leader]
    fdf = dfs[follower]
    lret = ldf["close_price"].pct_change(spec["lookback"]).to_numpy()
    fret = fdf["close_price"].pct_change(spec["follower_lookback"]).to_numpy()
    events = []
    for idx in np.where(np.isfinite(lret))[0]:
        if idx + spec["hold"] >= len(fdf):
            continue
        lr = float(lret[idx])
        fr = float(fret[idx]) if math.isfinite(float(fret[idx])) else 0.0
        side = None
        if spec["mode"] == "follow":
            if lr >= spec["move"] and abs(fr) <= spec["max_follower_move"]:
                side = "long"
            elif lr <= -spec["move"] and abs(fr) <= spec["max_follower_move"]:
                side = "short"
        elif spec["mode"] == "revert":
            if lr >= spec["move"] and abs(fr) <= spec["max_follower_move"]:
                side = "short"
            elif lr <= -spec["move"] and abs(fr) <= spec["max_follower_move"]:
                side = "long"
        elif spec["mode"] == "same_confirm":
            if lr >= spec["move"] and 0 <= fr <= spec["max_follower_move"]:
                side = "long"
            elif lr <= -spec["move"] and -spec["max_follower_move"] <= fr <= 0:
                side = "short"
        if side is not None:
            events.append((int(fdf.at[idx, "open_time"]), follower, side, int(idx)))
    return events


def push_top(heap: list[tuple[float, int, dict[str, Any]]], row: dict[str, Any], counter: int, limit: int = 300) -> None:
    w = row["weighted"]
    score = (
        (1 if row["strict_pass"] else 0) * 10000
        + w["wr"] * 1000
        + min(w["trades_per_month"], 30) * 50
        + w["annual_pnl_usd"] * 0.2
        - w["max_period_dd_usd"] * 0.5
    )
    item = (score, counter, row)
    if len(heap) < limit:
        heapq.heappush(heap, item)
    elif score > heap[0][0]:
        heapq.heapreplace(heap, item)


def main() -> None:
    args = parse_args()
    if args.merge:
        merge_chunks(args.chunk_count, args.top_limit)
        return
    print(
        f"G7831 5m lead-lag high-WR search starting chunk={args.chunk_index}/{args.chunk_count}...",
        flush=True,
    )
    t0 = time.time()
    dfs = load_aligned()
    print(f"  aligned rows={len(next(iter(dfs.values())))}", flush=True)
    top_heap: list[tuple[float, int, dict[str, Any]]] = []
    counter = 0
    n_specs = 0
    n_pass = 0
    for raw_i, (leader, follower, mode, lookback, follower_lb, move, max_follower_move, hold, tp, sl) in iter_chunked_product(
        args.chunk_index, args.chunk_count
    ):
        if args.max_seconds is not None and time.time() - t0 >= args.max_seconds:
            print(f"  soft stop at {round(time.time()-t0,1)}s after evaluated={n_specs}", flush=True)
            break
        if leader == follower:
            continue
        if sl < tp:
            continue
        spec = {
            "leader": leader,
            "follower": follower,
            "mode": mode,
            "lookback": lookback,
            "follower_lookback": follower_lb,
            "move": move,
            "max_follower_move": max_follower_move,
            "hold": hold,
            "tp": tp,
            "sl": sl,
            "lev": 5.0,
            "size": 0.10,
            "max_conc": 3,
        }
        events = event_candidates(dfs, spec)
        if len(events) < 30:
            continue
        weighted = simulate(events, dfs, spec)
        n_specs += 1
        strict = (
            weighted["trades_per_month"] >= 8
            and weighted["wr"] >= 0.65
            and weighted["pnl_usd"] > 0
            and weighted["all_years_positive"]
            and weighted["liquidations"] == 0
        )
        n_pass += int(strict)
        row = {"id": f"G7831_{raw_i}", "family": "5m_leadlag", "spec": spec, "weighted": weighted, "strict_pass": strict}
        counter += 1
        push_top(top_heap, row, counter, args.top_limit)
        if n_specs % 1000 == 0:
            print(f"  evaluated={n_specs} pass={n_pass} elapsed={round(time.time()-t0,1)}", flush=True)
    top = [item[2] for item in sorted(top_heap, key=lambda x: x[0], reverse=True)]
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": "Can 5m cross-asset lead/lag produce high-frequency high-WR alpha?",
        "coverage": "2024-01-01 through 2026-04-27, ETH/SOL/DOGE/PEPE 5m only",
        "chunk_index": args.chunk_index,
        "chunk_count": args.chunk_count,
        "n_specs_evaluated": n_specs,
        "n_strict_pass": n_pass,
        "criteria": "tpm>=8, wr>=65%, pnl>0, all years positive, liq=0",
        "top": top,
        "elapsed_sec": round(time.time() - t0, 2),
        "complete": args.max_seconds is None or time.time() - t0 < args.max_seconds,
    }
    out_path = chunk_out_path(args.chunk_index, args.chunk_count)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {out_path}", flush=True)
    if top:
        print(json.dumps(top[0], ensure_ascii=False)[:1600], flush=True)


if __name__ == "__main__":
    main()
