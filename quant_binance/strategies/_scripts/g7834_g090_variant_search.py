"""Search G090/CH1-funding long variants for high WR and higher cadence."""
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

from g002_mingogogo_ch1_backtest import compute_ch1_score, atr_pct  # type: ignore
from g098_funding_validation import COMMON, KLINES_DIR, FUND_DIR, merge_funding  # type: ignore
from g900_ensemble_discovery import event_return  # type: ignore

OUT = SCRIPTS / "g7834_g090_variant_search_results.json"
TOTAL_DAYS = 365 + 365 + 117
EQUITY = 100.0


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


def rank_key(row: dict[str, Any]) -> tuple[Any, ...]:
    w = row["weighted"]
    return (
        row["freq_pass"],
        row["strict_pass"],
        w["all_years_positive"],
        w["all_years_wr_gte_65"],
        w["wr"],
        min(w["trades_per_month"], 30),
        w["annual_pnl_usd"],
        -w["max_period_dd_usd"],
    )


def iter_chunked_specs(chunk_index: int, chunk_count: int):
    if chunk_count < 1:
        raise ValueError("--chunk-count must be >= 1")
    if chunk_index < 0 or chunk_index >= chunk_count:
        raise ValueError("--chunk-index must be in [0, chunk_count)")
    hour_sets = [
        [1, 3, 0, 2, 21, 20, 4, 23, 6, 19],
        [1, 3, 0, 2, 21, 20, 4, 23, 6, 19, 22, 17, 11, 8, 5, 18, 10, 9, 15],
        list(range(0, 8)),
        list(range(8, 16)),
        list(range(16, 24)),
        None,
    ]
    grid = product(
        [70, 72, 74, 76, 78, 80, 82],
        [4, 6, 8, 10, 12],
        [12, 18, 24, 36, 48],
        [0.06, 0.08, 0.10, 0.12, 0.16],
        [0.035, 0.055, 0.07, 0.085],
        [None, 0.0004, 0.0008, 0.0012],
        [None, 0.20, 0.40, 0.80],
        [None, 1.2, 1.8],
        hour_sets,
    )
    for raw_i, combo in enumerate(grid):
        if raw_i % chunk_count == chunk_index:
            yield raw_i, combo


def merge_chunks(chunk_count: int, top_limit: int) -> None:
    chunks = [chunk_out_path(i, chunk_count) for i in range(chunk_count)]
    missing = [str(p) for p in chunks if not p.exists()]
    if missing:
        raise FileNotFoundError(f"missing chunk outputs: {missing[:5]}{'...' if len(missing) > 5 else ''}")
    rows: list[dict[str, Any]] = []
    n_specs = 0
    n_strict = 0
    n_freq = 0
    elapsed = 0.0
    for path in chunks:
        payload = json.loads(path.read_text(encoding="utf-8"))
        n_specs += int(payload.get("n_specs", 0))
        n_strict += int(payload.get("n_strict_pass", 0))
        n_freq += int(payload.get("n_freq_pass", 0))
        elapsed += float(payload.get("elapsed_sec", 0.0))
        rows.extend(payload.get("top", []))
    ranked = sorted(rows, key=rank_key, reverse=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": "Can G090 variants raise cadence while preserving high WR?",
        "coverage": "2024-01-01 through 2026-04-27",
        "chunk_count": chunk_count,
        "n_specs": n_specs,
        "n_strict_pass": n_strict,
        "n_freq_pass": n_freq,
        "top": ranked[:top_limit],
        "elapsed_sec_sum": round(elapsed, 2),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"merged {chunk_count} chunks into {OUT}", flush=True)


def load_all() -> dict[str, pd.DataFrame]:
    out = {}
    for sym in COMMON:
        kp = KLINES_DIR / sym / "1h.json"
        fp = FUND_DIR / sym / "funding.json"
        if not kp.exists() or not fp.exists():
            continue
        df = pd.DataFrame(json.loads(kp.read_text(encoding="utf-8"))).sort_values("open_time").reset_index(drop=True)
        fund = pd.DataFrame(json.loads(fp.read_text(encoding="utf-8")))
        if len(df) < 200 or len(fund) == 0:
            continue
        for col in ["open_price", "high_price", "low_price", "close_price", "base_volume", "quote_volume"]:
            df[col] = df[col].astype(float)
        df["open_time"] = df["open_time"].astype("int64")
        score, _ = compute_ch1_score(df)
        df["score"] = score.astype(float)
        df["atr_pct"] = atr_pct(df["high_price"], df["low_price"], df["close_price"], 14).astype(float)
        df["ret_24h"] = df["close_price"].pct_change(24)
        df["vol_ratio"] = df["quote_volume"] / df["quote_volume"].rolling(48).median().shift(1)
        df = merge_funding(df, fund).rename(columns={"funding": "funding_rate"})
        df["hour"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.hour
        df["year"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.year
        out[sym] = df.reset_index(drop=True)
    return out


def events(dfs: dict[str, pd.DataFrame], spec: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    hours = set(spec["hours"]) if spec["hours"] is not None else None
    for sym, df in dfs.items():
        mask = (df["score"] >= spec["score"]) & (df["atr_pct"] <= spec["atr_max"])
        if spec["funding_abs_lte"] is not None:
            mask &= df["funding_rate"].abs() <= spec["funding_abs_lte"]
        if spec["ret24_max"] is not None:
            mask &= df["ret_24h"] <= spec["ret24_max"]
        if spec["vol_min"] is not None:
            mask &= df["vol_ratio"] >= spec["vol_min"]
        if hours is not None:
            mask &= df["hour"].isin(hours)
        idxs = np.where(mask.fillna(False).to_numpy(dtype=bool))[0]
        for idx in idxs:
            if idx + spec["hold"] < len(df):
                out.append({"ts": int(df.at[idx, "open_time"]), "sym": sym, "idx": int(idx), "confidence": float(df.at[idx, "score"])})
    return sorted(out, key=lambda e: (e["ts"], -e["confidence"]))


def simulate(evs: list[dict[str, Any]], dfs: dict[str, pd.DataFrame], spec: dict[str, Any]) -> dict[str, Any]:
    open_pos: list[tuple[int, str]] = []
    rows = []
    for ev in evs:
        ts = ev["ts"]
        sym = ev["sym"]
        open_pos = [p for p in open_pos if p[0] > ts]
        if any(p[1] == sym for p in open_pos):
            continue
        if len(open_pos) >= spec["max_conc"]:
            continue
        net, liq, _ = event_return(dfs[sym], ev["idx"], "long", spec["hold"], spec["lev"], spec["tp_pct"], spec["sl_pct"])
        pnl = EQUITY * spec["size"] * net
        year = int(dfs[sym].at[ev["idx"], "year"])
        rows.append({"pnl": pnl, "win": pnl > 0, "liq": liq, "year": year})
        open_pos.append((ts + spec["hold"] * 3600 * 1000, sym))
    return summarize(rows)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by = {}
    maxdd = 0.0
    for year in [2024, 2025, 2026]:
        yr = [r for r in rows if r["year"] == year]
        curve = np.array([0.0] + list(np.cumsum([r["pnl"] for r in yr])), dtype=float)
        peak = np.maximum.accumulate(curve) if len(curve) else curve
        dd = float((peak - curve).max()) if len(curve) else 0.0
        maxdd = max(maxdd, dd)
        by[str(year)] = {
            "n": len(yr),
            "wr": round(sum(1 for r in yr if r["win"]) / max(len(yr), 1), 4),
            "pnl_usd": round(sum(r["pnl"] for r in yr), 2),
            "max_dd_usd": round(dd, 2),
        }
    n = len(rows)
    pnl = sum(r["pnl"] for r in rows)
    return {
        "n": n,
        "trades_per_month": round(n / TOTAL_DAYS * 30.4, 2),
        "wr": round(sum(1 for r in rows if r["win"]) / max(n, 1), 4),
        "pnl_usd": round(pnl, 2),
        "annual_pnl_usd": round(pnl / TOTAL_DAYS * 365, 2),
        "liquidations": sum(1 for r in rows if r["liq"]),
        "max_period_dd_usd": round(maxdd, 2),
        "min_year_pnl_usd": round(min(v["pnl_usd"] for v in by.values()), 2),
        "all_years_positive": all(v["pnl_usd"] > 0 for v in by.values()),
        "all_years_wr_gte_65": all(v["wr"] >= 0.65 for v in by.values() if v["n"] > 0),
        "years": by,
    }


def main() -> None:
    args = parse_args()
    if args.merge:
        merge_chunks(args.chunk_count, args.top_limit)
        return
    print(f"G7834 G090 variant search starting chunk={args.chunk_index}/{args.chunk_count}...", flush=True)
    t0 = time.time()
    dfs = load_all()
    results = []
    for raw_i, (score, atr_max, hold, tp, sl, funding_abs, ret24_max, vol_min, hours) in iter_chunked_specs(
        args.chunk_index, args.chunk_count
    ):
        if args.max_seconds is not None and time.time() - t0 >= args.max_seconds:
            print(f"  soft stop at {round(time.time()-t0,1)}s after rows={len(results)}", flush=True)
            break
        if sl > tp:
            continue
        spec = {
            "id": f"G{783400 + raw_i}",
            "score": score,
            "atr_max": atr_max,
            "hold": hold,
            "tp_pct": tp,
            "sl_pct": sl,
            "funding_abs_lte": funding_abs,
            "ret24_max": ret24_max,
            "vol_min": vol_min,
            "hours": hours,
            "lev": 5.0,
            "size": 0.10,
            "max_conc": 5,
        }
        w = simulate(events(dfs, spec), dfs, spec)
        row = {
            "id": spec["id"],
            "family": "g090_ch1_funding_long_variant",
            "spec": spec,
            "weighted": w,
            "strict_pass": w["trades_per_month"] >= 12 and w["wr"] >= 0.69 and w["all_years_positive"] and w["all_years_wr_gte_65"] and w["liquidations"] == 0,
            "freq_pass": w["trades_per_month"] >= 20 and w["wr"] >= 0.69 and w["all_years_positive"] and w["liquidations"] == 0,
        }
        results.append(row)
        if len(results) % 1000 == 0:
            print(f"  done={len(results)} strict={sum(r['strict_pass'] for r in results)} freq={sum(r['freq_pass'] for r in results)}", flush=True)
    ranked = sorted(results, key=rank_key, reverse=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": "Can G090 variants raise cadence while preserving high WR?",
        "coverage": "2024-01-01 through 2026-04-27",
        "chunk_index": args.chunk_index,
        "chunk_count": args.chunk_count,
        "n_specs": len(results),
        "n_strict_pass": sum(r["strict_pass"] for r in results),
        "n_freq_pass": sum(r["freq_pass"] for r in results),
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
