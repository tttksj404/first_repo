"""Filter the promising G090-long sleeve for 2024-2026 high WR."""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "quant_binance" / "strategies" / "_scripts"
sys.path.insert(0, str(SCRIPTS))

from g098_funding_validation import COMMON, gather_g090_long  # type: ignore

OUT = SCRIPTS / "g7833_g090_filter_high_wr_search_results.json"
TOTAL_DAYS = 365 + 365 + 117


def prep() -> pd.DataFrame:
    e = gather_g090_long(COMMON).copy()
    e["dt"] = pd.to_datetime(e["open_time"], unit="ms", utc=True)
    e["year"] = e["dt"].dt.year
    e["hour"] = e["dt"].dt.hour
    e["win"] = e["net_bps"] > 0
    return e


def summarize(e: pd.DataFrame) -> dict[str, Any]:
    by = {}
    maxdd = 0.0
    for y in [2024, 2025, 2026]:
        rows = e[e["year"] == y]
        curve = np.array([0.0] + list(np.cumsum(rows["net_bps"].to_numpy() / 10000 * 5.0 * 10.0)), dtype=float)
        peak = np.maximum.accumulate(curve) if len(curve) else curve
        dd = float((peak - curve).max()) if len(curve) else 0.0
        maxdd = max(maxdd, dd)
        by[str(y)] = {
            "n": int(len(rows)),
            "wr": round(float(rows["win"].mean()) if len(rows) else 0.0, 4),
            "avg_net_bps": round(float(rows["net_bps"].mean()) if len(rows) else 0.0, 2),
            "pnl_units": round(float(rows["net_bps"].sum() / 10000 * 5.0 * 10.0), 2),
        }
    n = len(e)
    return {
        "n": int(n),
        "trades_per_month": round(n / TOTAL_DAYS * 30.4, 2),
        "wr": round(float(e["win"].mean()) if n else 0.0, 4),
        "avg_net_bps": round(float(e["net_bps"].mean()) if n else 0.0, 2),
        "pnl_units": round(float(e["net_bps"].sum() / 10000 * 5.0 * 10.0), 2),
        "max_dd_units": round(maxdd, 2),
        "min_year_pnl_units": round(min(v["pnl_units"] for v in by.values()), 2),
        "all_years_positive": all(v["pnl_units"] > 0 for v in by.values()),
        "all_years_wr_gte_65": all(v["wr"] >= 0.65 for v in by.values() if v["n"] > 0),
        "years": by,
    }


def main() -> None:
    print("G7833 G090 filter high-WR search starting...", flush=True)
    t0 = time.time()
    e = prep()
    print(f"  raw n={len(e)}", flush=True)
    results = []

    # Ranked additive filters by symbols, hours, and symbol-hour cells.
    for mode in ["symbol", "hour", "symbol_hour"]:
        groups: dict[Any, pd.DataFrame] = {}
        if mode == "symbol":
            for k, rows in e.groupby("sym"):
                groups[k] = rows
        elif mode == "hour":
            for k, rows in e.groupby("hour"):
                groups[int(k)] = rows
        else:
            for k, rows in e.groupby(["sym", "hour"]):
                groups[k] = rows
        scored = []
        for k, rows in groups.items():
            if len(rows) < 3:
                continue
            s = summarize(rows)
            if s["pnl_units"] > 0:
                scored.append((k, s))
        scored = sorted(scored, key=lambda x: (x[1]["wr"], x[1]["pnl_units"], x[1]["n"]), reverse=True)
        chosen = []
        for k, _s in scored:
            chosen.append(k)
            if mode == "symbol":
                rows = e[e["sym"].isin(chosen)]
            elif mode == "hour":
                rows = e[e["hour"].isin(chosen)]
            else:
                allowed = set(chosen)
                rows = e[e.apply(lambda r: (r["sym"], r["hour"]) in allowed, axis=1)]
            if len(rows) < 20:
                continue
            s = summarize(rows)
            s["filter_type"] = mode
            if mode == "symbol_hour":
                s["filters"] = [[sym, int(hour)] for sym, hour in chosen]
            else:
                s["filters"] = list(chosen)
            s["strict_pass"] = (
                s["trades_per_month"] >= 8
                and s["wr"] >= 0.69
                and s["all_years_wr_gte_65"]
                and s["all_years_positive"]
            )
            results.append(s)

    # Threshold filters.
    for fund_abs in [None, 0.0002, 0.0004, 0.0006, 0.0008]:
        for atr_max in [4, 6, 8]:
            rows = e[e["atr_pct"] <= atr_max]
            if fund_abs is not None:
                rows = rows[rows["funding"].abs() <= fund_abs]
            if len(rows) < 20:
                continue
            s = summarize(rows)
            s["filter_type"] = "threshold"
            s["filters"] = {"funding_abs_lte": fund_abs, "atr_max": atr_max}
            s["strict_pass"] = s["trades_per_month"] >= 8 and s["wr"] >= 0.69 and s["all_years_wr_gte_65"] and s["all_years_positive"]
            results.append(s)

    ranked = sorted(results, key=lambda r: (r["strict_pass"], r["wr"], r["trades_per_month"], r["pnl_units"]), reverse=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": "Can G090-long be filtered into a high-frequency high-WR sleeve?",
        "raw": summarize(e),
        "n_filters": len(results),
        "n_strict_pass": sum(1 for r in results if r["strict_pass"]),
        "top": ranked[:120],
        "elapsed_sec": round(time.time() - t0, 2),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)
    print(json.dumps(ranked[0], ensure_ascii=False)[:1600], flush=True)


if __name__ == "__main__":
    main()
