"""Validate combinations of the current high-WR sleeve candidates.

This is a follow-up to:
- G7833: G090-long hour-filter high-WR sleeve
- G7832: funding-extreme chunked search candidates

It combines signal records chronologically with a simple same-symbol/open-slot
portfolio constraint so the reported cadence is closer to something a paper
runtime could actually attempt.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "quant_binance" / "strategies" / "_scripts"
sys.path.insert(0, str(SCRIPTS))

from g1300_two_slot_search import resolve_conflicts  # type: ignore
from g7832_funding_extreme_high_wr_search import build_events, load_periods  # type: ignore
from g7833_g090_filter_high_wr_search import prep as prep_g090  # type: ignore
from g900_ensemble_discovery import EQUITY, event_return  # type: ignore

OUT = SCRIPTS / "g7835_high_wr_sleeve_combo_validation_results.json"
TOTAL_DAYS = 365 + 365 + 117
G090_HOURS = [1, 3, 0, 2, 21, 20, 4, 23, 6, 19]

FUNDING_CANDIDATES = [
    {
        "id": "G805740_balanced_negative_squeeze",
        "mode": "negative_squeeze_long",
        "fund_abs": 0.0001,
        "move_24h": 0.08,
        "vol_min": None,
        "hold": 6,
        "tp_pct": 0.015,
        "sl_pct": 0.12,
        "lev": 5.0,
        "size": 0.10,
        "max_conc": 5,
        "atr_min": 0,
        "atr_max": 10,
        "hour_set": None,
    },
    {
        "id": "G827758_balanced_positive_follow_midday",
        "mode": "positive_follow_long",
        "fund_abs": 0.0001,
        "move_24h": 0.12,
        "vol_min": 1.8,
        "hold": 6,
        "tp_pct": 0.015,
        "sl_pct": 0.12,
        "lev": 5.0,
        "size": 0.10,
        "max_conc": 5,
        "atr_min": 0,
        "atr_max": 10,
        "hour_set": list(range(8, 16)),
    },
]


def g090_records() -> list[dict[str, Any]]:
    e = prep_g090()
    e = e[e["hour"].isin(G090_HOURS)].copy()
    rows = []
    for _, r in e.iterrows():
        pnl = float(r["net_bps"]) / 10000.0 * 5.0 * 10.0
        rows.append(
            {
                "ts": int(r["open_time"]),
                "sym": str(r["sym"]),
                "side": "long",
                "family": "g090_hour_filter",
                "pnl": pnl,
                "win": pnl > 0,
                "liq": False,
                "duration_ms": 24 * 3600 * 1000,
            }
        )
    return rows


def funding_records(spec: dict[str, Any], periods: dict[str, dict[str, pd.DataFrame]]) -> list[dict[str, Any]]:
    rows = []
    for dfs in periods.values():
        events = resolve_conflicts(build_events(dfs, spec))
        open_pos: list[tuple[int, str]] = []
        for ev in events:
            ts = int(ev["ts"])
            sym = str(ev["sym"])
            open_pos = [p for p in open_pos if p[0] > ts]
            if any(p[1] == sym for p in open_pos):
                continue
            if len(open_pos) >= spec["max_conc"]:
                continue
            net, liquidated, _ = event_return(dfs[sym], ev["idx"], ev["side"], spec["hold"], spec["lev"], spec["tp_pct"], spec["sl_pct"])
            pnl = EQUITY * spec["size"] * net
            rows.append(
                {
                    "ts": ts,
                    "sym": sym,
                    "side": ev["side"],
                    "family": spec["id"],
                    "pnl": pnl,
                    "win": pnl > 0,
                    "liq": liquidated,
                    "duration_ms": spec["hold"] * 3600 * 1000,
                }
            )
            open_pos.append((ts + spec["hold"] * 3600 * 1000, sym))
    return rows


def apply_portfolio_constraints(records: list[dict[str, Any]], max_conc: int = 5) -> list[dict[str, Any]]:
    taken = []
    open_pos: list[tuple[int, str]] = []
    seen: set[tuple[int, str, str]] = set()
    for r in sorted(records, key=lambda x: (x["ts"], x["family"])):
        key = (int(r["ts"]), str(r["sym"]), str(r["side"]))
        if key in seen:
            continue
        seen.add(key)
        open_pos = [p for p in open_pos if p[0] > r["ts"]]
        if any(p[1] == r["sym"] for p in open_pos):
            continue
        if len(open_pos) >= max_conc:
            continue
        taken.append(r)
        open_pos.append((int(r["ts"]) + int(r["duration_ms"]), str(r["sym"])))
    return taken


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
            "pnl_units": round(sum(r["pnl"] for r in rows), 2),
            "max_dd_units": round(dd, 2),
        }
    by_family = {}
    for fam in sorted({r["family"] for r in records}):
        rows = [r for r in records if r["family"] == fam]
        by_family[fam] = {
            "n": len(rows),
            "wr": round(sum(1 for r in rows if r["win"]) / max(len(rows), 1), 4),
            "pnl_units": round(sum(r["pnl"] for r in rows), 2),
        }
    n = len(records)
    pnl = sum(r["pnl"] for r in records)
    return {
        "n": n,
        "trades_per_month": round(n / TOTAL_DAYS * 30.4, 2),
        "wr": round(sum(1 for r in records if r["win"]) / max(n, 1), 4),
        "pnl_units": round(pnl, 2),
        "annual_pnl_units": round(pnl / TOTAL_DAYS * 365, 2),
        "liquidations": sum(1 for r in records if r["liq"]),
        "max_period_dd_units": round(maxdd, 2),
        "all_years_positive": all(v["pnl_units"] > 0 for v in by_year.values()),
        "years": by_year,
        "families": by_family,
    }


def main() -> None:
    print("G7835 high-WR sleeve combo validation starting...", flush=True)
    t0 = time.time()
    periods = load_periods()
    base = g090_records()
    funding = {spec["id"]: funding_records(spec, periods) for spec in FUNDING_CANDIDATES}
    combos = []
    specs = [
        ("G090_only", base),
        ("G090_plus_G805740", base + funding["G805740_balanced_negative_squeeze"]),
        ("G090_plus_G827758", base + funding["G827758_balanced_positive_follow_midday"]),
        ("G090_plus_G805740_plus_G827758", base + funding["G805740_balanced_negative_squeeze"] + funding["G827758_balanced_positive_follow_midday"]),
    ]
    for name, records in specs:
        taken = apply_portfolio_constraints(records)
        combos.append(
            {
                "id": name,
                "raw_records": len(records),
                "taken_records": len(taken),
                "weighted": summarize(taken),
            }
        )
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": "Do the new funding sleeves combine with the G090 hour-filter sleeve toward the 30/month high-WR target?",
        "coverage": "2024-01-01 through 2026-04-27 where local inputs are available",
        "portfolio_constraint": "dedupe same ts/sym/side, skip same-symbol overlapping holds, max_conc=5",
        "funding_candidates": FUNDING_CANDIDATES,
        "combos": combos,
        "elapsed_sec": round(time.time() - t0, 2),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)
    for row in combos:
        print(row["id"], json.dumps(row["weighted"], ensure_ascii=False)[:1000], flush=True)


if __name__ == "__main__":
    main()
