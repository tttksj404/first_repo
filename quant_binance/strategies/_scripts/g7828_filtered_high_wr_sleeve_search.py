"""Search symbol/hour filters that lift high-cadence sleeves toward high WR.

G7827 did not discover a fresh high-WR family. This pass tries to filter the
best high-cadence full-window sleeves by symbol/hour cells. It is still
research-only and likely overfit, but it answers whether the current data
contains enough high-WR pockets to build a better sleeve.
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "quant_binance" / "strategies" / "_scripts"
sys.path.insert(0, str(SCRIPTS))

from g1300_two_slot_search import resolve_conflicts  # type: ignore
from g1306_loose_breakout_adaptive_search import adaptive_breakout_events  # type: ignore
from g1307_controlled_loose_breakout_search import candidate_specs as g1307_specs  # type: ignore
from g1309_watch_confirm_breakout_search import watch_confirm_events  # type: ignore
from g900_ensemble_discovery import EQUITY, PERIODS, add_btc_regime, build_period_cache, event_return  # type: ignore

OUT = SCRIPTS / "g7828_filtered_high_wr_sleeve_search_results.json"
TOTAL_DAYS = sum(p.days for p in PERIODS)


def hour_of(ts: int) -> int:
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).hour


def simulate_records(events: list[dict[str, Any]], dfs: dict[str, Any], max_conc: int, period_name: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    open_pos: list[tuple[int, str]] = []
    for ev in resolve_conflicts(events):
        ts = int(ev["ts"])
        sym = str(ev["sym"])
        open_pos = [p for p in open_pos if p[0] > ts]
        if any(p[1] == sym for p in open_pos):
            continue
        if len(open_pos) >= max_conc:
            continue
        df = dfs.get(sym)
        if df is None:
            continue
        net_pct, liquidated, _ = event_return(df, ev["idx"], ev["side"], ev["hold"], ev["lev"], ev.get("tp_pct"), ev.get("sl_pct"))
        pnl = EQUITY * float(ev["size"]) * net_pct
        records.append(
            {
                "period": period_name,
                "ts": ts,
                "sym": sym,
                "side": ev["side"],
                "hour": hour_of(ts),
                "pnl_usd": pnl,
                "win": pnl > 0,
                "liquidated": liquidated,
                "key": (period_name, ts, sym, ev["side"]),
            }
        )
        open_pos.append((ts + int(ev["hold"]) * 3600 * 1000, sym))
    return records


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records)
    wins = sum(1 for r in records if r["win"])
    pnl = sum(float(r["pnl_usd"]) for r in records)
    liq = sum(1 for r in records if r["liquidated"])
    by_period: dict[str, dict[str, Any]] = {}
    maxdd = 0.0
    for period in PERIODS:
        rows = [r for r in records if r["period"] == period.name]
        curve = np.array([0.0] + list(np.cumsum([float(r["pnl_usd"]) for r in rows])), dtype=float)
        peak = np.maximum.accumulate(curve) if len(curve) else curve
        dd = float((peak - curve).max()) if len(curve) else 0.0
        maxdd = max(maxdd, dd)
        pn = len(rows)
        by_period[period.name] = {
            "n": pn,
            "wr": round(sum(1 for r in rows if r["win"]) / max(pn, 1), 4),
            "pnl_usd": round(sum(float(r["pnl_usd"]) for r in rows), 2),
            "trades_per_month": round(pn / period.days * 30.4, 2),
            "max_dd_usd": round(dd, 2),
        }
    return {
        "n": n,
        "trades_per_month": round(n / TOTAL_DAYS * 30.4, 2),
        "wr": round(wins / max(n, 1), 4),
        "pnl_usd": round(pnl, 2),
        "annual_pnl_usd": round(pnl / TOTAL_DAYS * 365, 2),
        "liquidations": liq,
        "max_period_dd_usd": round(maxdd, 2),
        "min_period_pnl_usd": round(min(row["pnl_usd"] for row in by_period.values()), 2),
        "all_periods_positive": all(row["pnl_usd"] > 0 for row in by_period.values()),
        "periods": by_period,
    }


def stat(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    return {
        "n": n,
        "wr": sum(1 for r in rows if r["win"]) / max(n, 1),
        "pnl": sum(float(r["pnl_usd"]) for r in rows),
    }


def eval_filter(records: list[dict[str, Any]], cells: set[tuple[str, int]]) -> dict[str, Any]:
    rows = [r for r in records if (r["sym"], r["hour"]) in cells]
    return summarize(rows)


def search_filters(candidate_id: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cell_rows: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        cell_rows[(r["sym"], r["hour"])].append(r)
    cells = []
    for cell, rows in cell_rows.items():
        s = stat(rows)
        if s["n"] >= 6 and s["pnl"] > 0:
            cells.append((cell, s))
    cells = sorted(cells, key=lambda x: (x[1]["wr"], x[1]["pnl"], x[1]["n"]), reverse=True)

    results: list[dict[str, Any]] = []
    selected: set[tuple[str, int]] = set()
    for idx, (cell, _s) in enumerate(cells[:120], 1):
        selected.add(cell)
        if idx < 3:
            continue
        res = eval_filter(records, selected)
        res["candidate_id"] = candidate_id
        res["filter_type"] = "top_symbol_hour_cells"
        res["n_cells"] = len(selected)
        res["cells"] = sorted([[sym, hour] for sym, hour in selected])
        results.append(res)

    # Also try pure symbol and pure hour cuts.
    for mode in ["symbol", "hour"]:
        groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        for r in records:
            groups[r["sym"] if mode == "symbol" else r["hour"]].append(r)
        ranked = []
        for key, rows in groups.items():
            s = stat(rows)
            if s["n"] >= 10 and s["pnl"] > 0:
                ranked.append((key, s))
        ranked = sorted(ranked, key=lambda x: (x[1]["wr"], x[1]["pnl"], x[1]["n"]), reverse=True)
        chosen = set()
        for idx, (key, _s) in enumerate(ranked, 1):
            chosen.add(key)
            if mode == "symbol":
                rows = [r for r in records if r["sym"] in chosen]
            else:
                rows = [r for r in records if r["hour"] in chosen]
            res = summarize(rows)
            res["candidate_id"] = candidate_id
            res["filter_type"] = f"top_{mode}s"
            res["n_filters"] = len(chosen)
            res["filters"] = sorted(chosen)
            results.append(res)
    return results


def main() -> None:
    print("G7828 filtered high-WR sleeve search starting...", flush=True)
    t0 = time.time()
    caches: dict[str, dict[str, Any]] = {}
    for period in PERIODS:
        dfs = build_period_cache(period, "no_dead")
        add_btc_regime(dfs)
        caches[period.name] = dfs

    rows_1309 = json.loads((SCRIPTS / "g1309_watch_confirm_breakout_results.json").read_text(encoding="utf-8"))["all_results"]
    ids = ["G4452", "G4456", "G4464", "G4472", "G4475", "G4677", "G4662", "G4692"]
    specs: dict[str, tuple[str, dict[str, Any]]] = {}
    for spec in g1307_specs():
        if spec["id"] in ids:
            specs[spec["id"]] = ("g1307", spec)
    for row in rows_1309:
        if row["id"] in ids:
            specs[row["id"]] = ("g1309", row["spec"])

    all_results: list[dict[str, Any]] = []
    raw_stats: list[dict[str, Any]] = []
    for cid in ids:
        kind, spec = specs[cid]
        records: list[dict[str, Any]] = []
        for period in PERIODS:
            dfs = caches[period.name]
            events = adaptive_breakout_events(dfs, spec) if kind == "g1307" else watch_confirm_events(dfs, spec)
            records.extend(simulate_records(events, dfs, spec.get("max_conc", 5), period.name))
        raw = summarize(records)
        raw["candidate_id"] = cid
        raw_stats.append(raw)
        results = search_filters(cid, records)
        all_results.extend(results)
        print(f"  {cid}: raw_wr={raw['wr']} raw_tpm={raw['trades_per_month']} filters={len(results)}", flush=True)

    def ok(row: dict[str, Any], tpm: float, wr: float) -> bool:
        return (
            row["trades_per_month"] >= tpm
            and row["wr"] >= wr
            and row["pnl_usd"] > 0
            and row["liquidations"] == 0
            and row["all_periods_positive"]
        )

    top = sorted(
        all_results,
        key=lambda r: (
            ok(r, 8, 0.65),
            ok(r, 12, 0.65),
            ok(r, 8, 0.69),
            r["wr"],
            r["trades_per_month"],
            r["annual_pnl_usd"],
        ),
        reverse=True,
    )
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": "Can symbol/hour filters turn high-cadence sleeves into high-WR sleeves?",
        "raw_stats": raw_stats,
        "n_filters_tested": len(all_results),
        "n_pass_tpm8_wr65": sum(1 for r in all_results if ok(r, 8, 0.65)),
        "n_pass_tpm12_wr65": sum(1 for r in all_results if ok(r, 12, 0.65)),
        "n_pass_tpm8_wr69": sum(1 for r in all_results if ok(r, 8, 0.69)),
        "top": top[:120],
        "elapsed_sec": round(time.time() - t0, 2),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)
    if top:
        print(json.dumps(top[0], ensure_ascii=False)[:2000], flush=True)


if __name__ == "__main__":
    main()
