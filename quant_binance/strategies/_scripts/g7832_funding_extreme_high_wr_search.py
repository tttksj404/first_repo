"""Funding-extreme alpha search for high-WR cadence repair.

Coverage is 2024-01-01 through 2026-04-27 because local funding history starts
in 2024. This is not directly comparable to OOS22-23, but it is a separate
data-source alpha search beyond 1h price breakout.
"""
from __future__ import annotations

import json
import argparse
import sys
import time
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "quant_binance" / "strategies" / "_scripts"
sys.path.insert(0, str(SCRIPTS))

from g1300_two_slot_search import resolve_conflicts  # type: ignore
from g900_ensemble_discovery import EQUITY, event_return, load_symbol_df  # type: ignore

OUT = SCRIPTS / "g7832_funding_extreme_high_wr_search_results.json"
DATA_24 = ROOT / "quant_runtime" / "historical_2024"
DATA_25 = ROOT / "quant_runtime" / "historical_is25"
TOTAL_DAYS = 456 + 374


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--chunk-index", type=int, default=0, help="0-based chunk index to run")
    p.add_argument("--chunk-count", type=int, default=1, help="total chunks in the full grid")
    p.add_argument("--top-limit", type=int, default=300, help="top rows to keep per output")
    p.add_argument("--max-seconds", type=float, default=None, help="optional soft time budget; writes partial output before exiting")
    p.add_argument("--merge", action="store_true", help="merge completed chunk outputs into the canonical result file")
    p.add_argument("--allow-partial", action="store_true", help="merge whatever chunk outputs exist so far")
    return p.parse_args()


def chunk_out_path(chunk_index: int, chunk_count: int) -> Path:
    if chunk_count <= 1:
        return OUT
    return OUT.with_name(f"{OUT.stem}_chunk_{chunk_index:03d}_of_{chunk_count:03d}{OUT.suffix}")


def rank_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["dream_pass"],
        row["strict_pass"],
        row["weighted"]["wr"],
        row["weighted"]["trades_per_month"],
        row["weighted"]["annual_pnl_usd"],
    )


def iter_chunked_specs(chunk_index: int, chunk_count: int):
    if chunk_count < 1:
        raise ValueError("--chunk-count must be >= 1")
    if chunk_index < 0 or chunk_index >= chunk_count:
        raise ValueError("--chunk-index must be in [0, chunk_count)")
    hour_sets = [None, list(range(0, 8)), list(range(8, 16)), list(range(16, 24))]
    grid = product(
        ["positive_fade_short", "negative_squeeze_long", "positive_follow_long", "negative_follow_short"],
        [0.0001, 0.0003, 0.0005, 0.0008, 0.0012],
        [0.00, 0.04, 0.08, 0.12],
        [None, 1.2, 1.8, 2.5],
        [6, 12, 24, 36],
        [0.015, 0.025, 0.04, 0.06],
        [0.025, 0.04, 0.08, 0.12],
        [5.0],
        hour_sets,
    )
    for raw_i, combo in enumerate(grid):
        if raw_i % chunk_count == chunk_index:
            yield raw_i, combo


def merge_chunks(chunk_count: int, top_limit: int, allow_partial: bool = False) -> None:
    chunks = [chunk_out_path(i, chunk_count) for i in range(chunk_count)]
    missing = [str(p) for p in chunks if not p.exists()]
    if missing and not allow_partial:
        raise FileNotFoundError(f"missing chunk outputs: {missing[:5]}{'...' if len(missing) > 5 else ''}")
    chunks = [p for p in chunks if p.exists()]
    rows: list[dict[str, Any]] = []
    n_specs = 0
    n_strict = 0
    n_dream = 0
    elapsed = 0.0
    for path in chunks:
        payload = json.loads(path.read_text(encoding="utf-8"))
        n_specs += int(payload.get("n_specs", 0))
        n_strict += int(payload.get("n_strict_pass", 0))
        n_dream += int(payload.get("n_dream_pass", 0))
        elapsed += float(payload.get("elapsed_sec", 0.0))
        rows.extend(payload.get("top", []))
    ranked = sorted(rows, key=rank_key, reverse=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": "Can funding extremes produce high-frequency high-WR alpha?",
        "coverage": "2024-01-01 through 2026-04-27 funding/1h price",
        "chunk_count": chunk_count,
        "chunks_merged": len(chunks),
        "partial_merge": len(chunks) < chunk_count,
        "n_specs": n_specs,
        "n_strict_pass": n_strict,
        "n_dream_pass": n_dream,
        "top": ranked[:top_limit],
        "elapsed_sec_sum": round(elapsed, 2),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"merged {len(chunks)}/{chunk_count} chunks into {OUT}", flush=True)

SYMBOLS_24 = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "SOLUSDT", "DOGEUSDT",
    "DOTUSDT", "LINKUSDT", "LTCUSDT", "AVAXUSDT", "NEARUSDT",
    "UNIUSDT", "XRPUSDT", "OPUSDT", "ARBUSDT", "APTUSDT", "PEPEUSDT",
    "SUIUSDT",
]
SYMBOLS_25 = [
    "DOGEUSDT", "PEPEUSDT", "WIFUSDT", "ARBUSDT", "OPUSDT", "AVAXUSDT",
    "SUIUSDT", "ADAUSDT", "APTUSDT", "BNBUSDT", "DOTUSDT", "LINKUSDT",
    "LTCUSDT", "NEARUSDT", "SOLUSDT", "UNIUSDT", "XRPUSDT", "BTCUSDT",
]


def load_periods() -> dict[str, dict[str, pd.DataFrame]]:
    out = {"OOS24-Q1": {}, "IS25-26": {}}
    for sym in SYMBOLS_24:
        df = load_symbol_df(DATA_24, sym)
        if df is not None:
            out["OOS24-Q1"][sym] = df
    for sym in SYMBOLS_25:
        df = load_symbol_df(DATA_25, sym)
        if df is not None:
            out["IS25-26"][sym] = df
    return out


def build_events(dfs: dict[str, pd.DataFrame], spec: dict[str, Any]) -> list[dict[str, Any]]:
    events = []
    for sym, df in dfs.items():
        common = df["funding_rate"].notna() & df["atr_pct"].between(spec["atr_min"], spec["atr_max"])
        if spec["mode"] == "positive_fade_short":
            mask = common & (df["funding_rate"] >= spec["fund_abs"]) & (df["ret_24h"] >= spec["move_24h"])
            side = "short"
        elif spec["mode"] == "negative_squeeze_long":
            mask = common & (df["funding_rate"] <= -spec["fund_abs"]) & (df["ret_24h"] <= -spec["move_24h"])
            side = "long"
        elif spec["mode"] == "positive_follow_long":
            mask = common & (df["funding_rate"] >= spec["fund_abs"]) & (df["ret_24h"] >= spec["move_24h"])
            side = "long"
        else:
            mask = common & (df["funding_rate"] <= -spec["fund_abs"]) & (df["ret_24h"] <= -spec["move_24h"])
            side = "short"
        if spec.get("vol_min") is not None:
            mask &= df["vol_ratio"] >= spec["vol_min"]
        if spec.get("hour_set") is not None:
            hours = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.hour
            mask &= hours.isin(spec["hour_set"])
        idxs = np.where(mask.fillna(False).to_numpy(dtype=bool))[0]
        for idx in idxs:
            if idx + spec["hold"] >= len(df):
                continue
            conf = 1.0 + abs(float(df.at[idx, "funding_rate"])) / max(spec["fund_abs"], 1e-9)
            events.append({"ts": int(df.at[idx, "open_time"]), "sym": sym, "idx": int(idx), "side": side, "confidence": conf})
    return sorted(events, key=lambda e: e["ts"])


def simulate(events: list[dict[str, Any]], dfs: dict[str, pd.DataFrame], spec: dict[str, Any], days: int) -> dict[str, Any]:
    events = resolve_conflicts(events)
    open_pos: list[tuple[int, str]] = []
    pnl = 0.0
    wins = 0
    liq = 0
    n = 0
    curve = [0.0]
    for ev in events:
        ts = ev["ts"]
        sym = ev["sym"]
        open_pos = [p for p in open_pos if p[0] > ts]
        if any(p[1] == sym for p in open_pos):
            continue
        if len(open_pos) >= spec["max_conc"]:
            continue
        df = dfs[sym]
        net, liquidated, _ = event_return(df, ev["idx"], ev["side"], spec["hold"], spec["lev"], spec["tp_pct"], spec["sl_pct"])
        trade_pnl = EQUITY * spec["size"] * net
        pnl += trade_pnl
        curve.append(pnl)
        wins += int(trade_pnl > 0)
        liq += int(liquidated)
        n += 1
        open_pos.append((ts + spec["hold"] * 3600 * 1000, sym))
    arr = np.array(curve, dtype=float)
    peak = np.maximum.accumulate(arr)
    dd = peak - arr
    return {
        "n": n,
        "wr": wins / max(n, 1),
        "pnl_usd": round(pnl, 2),
        "annual_pnl_usd": round(pnl / days * 365, 2),
        "liquidations": liq,
        "max_dd_usd": round(float(dd.max()) if len(dd) else 0.0, 2),
    }


def summarize(periods: dict[str, Any]) -> dict[str, Any]:
    n = sum(r["n"] for r in periods.values())
    pnl = sum(r["pnl_usd"] for r in periods.values())
    wins = sum(r["wr"] * r["n"] for r in periods.values())
    return {
        "n": n,
        "trades_per_month": round(n / TOTAL_DAYS * 30.4, 2),
        "wr": round(wins / max(n, 1), 4),
        "pnl_usd": round(pnl, 2),
        "annual_pnl_usd": round(pnl / TOTAL_DAYS * 365, 2),
        "liquidations": sum(r["liquidations"] for r in periods.values()),
        "max_period_dd_usd": max(r["max_dd_usd"] for r in periods.values()),
        "min_period_pnl_usd": min(r["pnl_usd"] for r in periods.values()),
        "all_periods_positive": all(r["pnl_usd"] > 0 for r in periods.values()),
    }


def main() -> None:
    args = parse_args()
    if args.merge:
        merge_chunks(args.chunk_count, args.top_limit, args.allow_partial)
        return
    print(
        f"G7832 funding-extreme high-WR search starting chunk={args.chunk_index}/{args.chunk_count}...",
        flush=True,
    )
    t0 = time.time()
    caches = load_periods()
    print(f"  loaded OOS24={len(caches['OOS24-Q1'])} IS25={len(caches['IS25-26'])}", flush=True)
    results = []
    for raw_i, (mode, fund_abs, move_24h, vol_min, hold, tp, sl, lev, hour_set) in iter_chunked_specs(
        args.chunk_index, args.chunk_count
    ):
        if args.max_seconds is not None and time.time() - t0 >= args.max_seconds:
            print(f"  soft stop at {round(time.time()-t0,1)}s after rows={len(results)}", flush=True)
            break
        if sl < tp:
            continue
        spec = {
            "id": f"G{783200 + raw_i}",
            "mode": mode,
            "fund_abs": fund_abs,
            "move_24h": move_24h,
            "vol_min": vol_min,
            "hold": hold,
            "tp_pct": tp,
            "sl_pct": sl,
            "lev": lev,
            "size": 0.10,
            "max_conc": 5,
            "atr_min": 0,
            "atr_max": 10,
            "hour_set": hour_set,
        }
        periods = {}
        for pname, dfs in caches.items():
            days = 456 if pname == "OOS24-Q1" else 374
            periods[pname] = simulate(build_events(dfs, spec), dfs, spec, days)
        w = summarize(periods)
        row = {
            "id": spec["id"],
            "family": "funding_extreme",
            "spec": spec,
            "periods": periods,
            "weighted": w,
            "strict_pass": w["trades_per_month"] >= 8 and w["wr"] >= 0.65 and w["pnl_usd"] > 0 and w["all_periods_positive"] and w["liquidations"] == 0,
            "dream_pass": w["trades_per_month"] >= 12 and w["wr"] >= 0.69 and w["pnl_usd"] > 0 and w["all_periods_positive"] and w["liquidations"] == 0,
        }
        results.append(row)
        if len(results) % 1000 == 0:
            print(f"  done={len(results)} strict={sum(r['strict_pass'] for r in results)} dream={sum(r['dream_pass'] for r in results)}", flush=True)
    ranked = sorted(results, key=rank_key, reverse=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": "Can funding extremes produce high-frequency high-WR alpha?",
        "coverage": "2024-01-01 through 2026-04-27 funding/1h price",
        "chunk_index": args.chunk_index,
        "chunk_count": args.chunk_count,
        "n_specs": len(results),
        "n_strict_pass": sum(r["strict_pass"] for r in results),
        "n_dream_pass": sum(r["dream_pass"] for r in results),
        "top": ranked[: args.top_limit],
        "elapsed_sec": round(time.time() - t0, 2),
        "complete": args.max_seconds is None or time.time() - t0 < args.max_seconds,
    }
    out_path = chunk_out_path(args.chunk_index, args.chunk_count)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {out_path}", flush=True)
    if ranked:
        print(json.dumps(ranked[0], ensure_ascii=False)[:1600], flush=True)


if __name__ == "__main__":
    main()
