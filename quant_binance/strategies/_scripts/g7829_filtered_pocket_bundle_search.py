"""Bundle high-WR symbol/hour pockets to test strict all-metric repair."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "quant_binance" / "strategies" / "_scripts"
sys.path.insert(0, str(SCRIPTS))

from g7828_filtered_high_wr_sleeve_search import (  # type: ignore
    PERIODS,
    build_period_cache,
    add_btc_regime,
    adaptive_breakout_events,
    watch_confirm_events,
    g1307_specs,
    simulate_records,
    search_filters,
    summarize,
)

OUT = SCRIPTS / "g7829_filtered_pocket_bundle_search_results.json"
TOTAL_DAYS = sum(p.days for p in PERIODS)


G7822_STATS = {"n": 53, "wins": round(53 * 0.6981), "pnl_usd": 1015.58, "max_dd": 92.88}


def load_pocket_records() -> list[dict[str, Any]]:
    caches = {}
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

    pockets: list[dict[str, Any]] = []
    for cid in ids:
        kind, spec = specs[cid]
        records = []
        for period in PERIODS:
            dfs = caches[period.name]
            events = adaptive_breakout_events(dfs, spec) if kind == "g1307" else watch_confirm_events(dfs, spec)
            records.extend(simulate_records(events, dfs, spec.get("max_conc", 5), period.name))
        filters = search_filters(cid, records)
        for row in filters:
            if row["pnl_usd"] <= 0 or not row["all_periods_positive"] or row["liquidations"] != 0:
                continue
            if row["wr"] < 0.69:
                continue
            if row["trades_per_month"] < 0.3:
                continue
            if row["filter_type"] == "top_symbol_hour_cells":
                cells = {tuple(cell) for cell in row["cells"]}
                selected = [r for r in records if (r["sym"], r["hour"]) in cells]
            elif row["filter_type"] == "top_symbols":
                selected = [r for r in records if r["sym"] in set(row["filters"])]
            elif row["filter_type"] == "top_hours":
                selected = [r for r in records if r["hour"] in set(row["filters"])]
            else:
                continue
            keys = {tuple(r["key"]) for r in selected}
            pockets.append(
                {
                    "id": f"{cid}_{row['filter_type']}_{len(pockets)}",
                    "candidate_id": cid,
                    "filter_type": row["filter_type"],
                    "summary": row,
                    "records": selected,
                    "keys": keys,
                }
            )
    # Deduplicate identical keysets.
    seen = set()
    out = []
    for p in sorted(pockets, key=lambda x: (x["summary"]["wr"], x["summary"]["trades_per_month"]), reverse=True):
        frozen = frozenset(p["keys"])
        if frozen in seen:
            continue
        seen.add(frozen)
        out.append(p)
    return out


def bundle_summary(pockets: list[dict[str, Any]]) -> dict[str, Any]:
    by_key: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    # If duplicate entry appears across pockets, keep first. For WR/PnL, count de-duped records.
    for pocket in pockets:
        for r in pocket["records"]:
            by_key.setdefault(tuple(r["key"]), r)
    records = list(by_key.values())
    s = summarize(records)
    n = s["n"] + G7822_STATS["n"]
    wins = sum(1 for r in records if r["win"]) + G7822_STATS["wins"]
    pnl = s["pnl_usd"] + G7822_STATS["pnl_usd"]
    return {
        "pocket_ids": [p["id"] for p in pockets],
        "candidate_ids": [p["candidate_id"] for p in pockets],
        "n_pockets": len(pockets),
        "pocket_unique": s,
        "with_g7822": {
            "n": n,
            "unique_trades_per_month": round(n / TOTAL_DAYS * 30.4, 2),
            "wr": round(wins / max(n, 1), 4),
            "pnl_usd": round(pnl, 2),
            "annual_pnl_usd": round(pnl / TOTAL_DAYS * 365, 2),
            "max_period_dd_upper_bound": round(max(s["max_period_dd_usd"], G7822_STATS["max_dd"]), 2),
        },
    }


def main() -> None:
    print("G7829 filtered pocket bundle search starting...", flush=True)
    t0 = time.time()
    pockets = load_pocket_records()
    print(f"  pockets={len(pockets)}", flush=True)
    beam: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []
    for p in pockets:
        beam.append(([p], bundle_summary([p])))
    passes: list[dict[str, Any]] = []
    for depth in range(2, 21):
        states = {}
        for chosen, _summary in beam:
            chosen_ids = {id(p) for p in chosen}
            last_idx = max(pockets.index(p) for p in chosen)
            for idx, p in enumerate(pockets):
                if idx <= last_idx or id(p) in chosen_ids:
                    continue
                trial = chosen + [p]
                summary = bundle_summary(trial)
                wg = summary["with_g7822"]
                key = tuple(summary["pocket_ids"])
                states[key] = (trial, summary)
                if (
                    wg["unique_trades_per_month"] >= 30
                    and wg["wr"] >= 0.6863
                    and wg["max_period_dd_upper_bound"] <= 96.75
                    and wg["pnl_usd"] > 1015.58
                ):
                    passes.append(summary)
        beam = sorted(
            states.values(),
            key=lambda item: (
                item[1]["with_g7822"]["wr"],
                item[1]["with_g7822"]["unique_trades_per_month"],
                item[1]["with_g7822"]["annual_pnl_usd"],
            ),
            reverse=True,
        )[:300]
        best = beam[0][1] if beam else None
        print(
            f"  depth={depth} states={len(beam)} passes={len(passes)} "
            f"best_wr={best['with_g7822']['wr'] if best else 0} "
            f"best_tpm={best['with_g7822']['unique_trades_per_month'] if best else 0}",
            flush=True,
        )
        if passes:
            break
    best = sorted(passes, key=lambda s: (s["with_g7822"]["wr"], s["with_g7822"]["unique_trades_per_month"]), reverse=True)[:20]
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_pockets": len(pockets),
        "pocket_summaries": [
            {k: v for k, v in p.items() if k not in {"records", "keys"}} for p in pockets[:80]
        ],
        "passes": best,
        "best_terminal": beam[0][1] if beam else None,
        "decision": {
            "verdict": "PASS" if best else "FAIL",
            "reason": "Combines only filtered pockets with standalone WR>=69%.",
        },
        "elapsed_sec": round(time.time() - t0, 2),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
