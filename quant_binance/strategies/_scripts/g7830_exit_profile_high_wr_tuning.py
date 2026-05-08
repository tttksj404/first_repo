"""Tune exits on high-cadence signals to see if WR can be lifted materially."""
from __future__ import annotations

import json
import sys
import time
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

OUT = SCRIPTS / "g7830_exit_profile_high_wr_tuning_results.json"
TOTAL_DAYS = sum(p.days for p in PERIODS)


def simulate(events: list[dict[str, Any]], dfs: dict[str, Any], spec: dict[str, Any], period_name: str, days: int) -> dict[str, Any]:
    open_pos: list[tuple[int, str]] = []
    pnl = 0.0
    wins = 0
    liq = 0
    n = 0
    curve = [0.0]
    keys = []
    for ev in resolve_conflicts(events):
        ts = int(ev["ts"])
        sym = str(ev["sym"])
        open_pos = [p for p in open_pos if p[0] > ts]
        if any(p[1] == sym for p in open_pos):
            continue
        if len(open_pos) >= spec["max_conc"]:
            continue
        df = dfs.get(sym)
        if df is None or ev["idx"] + spec["hold"] >= len(df):
            continue
        net_pct, liquidated, _ = event_return(df, ev["idx"], ev["side"], spec["hold"], spec["lev"], spec["tp_pct"], spec["sl_pct"])
        trade_pnl = EQUITY * spec["size"] * net_pct
        pnl += trade_pnl
        curve.append(pnl)
        wins += int(trade_pnl > 0)
        liq += int(liquidated)
        n += 1
        open_pos.append((ts + spec["hold"] * 3600 * 1000, sym))
        keys.append((period_name, ts, sym, ev["side"]))
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
        "keys": keys,
    }


def summarize(periods: dict[str, Any], keys: set[tuple[str, int, str, str]]) -> dict[str, Any]:
    n = sum(r["n"] for r in periods.values())
    pnl = sum(r["pnl_usd"] for r in periods.values())
    wins = sum(r["wr"] * r["n"] for r in periods.values())
    return {
        "n": n,
        "unique_n": len(keys),
        "trades_per_month": round(len(keys) / TOTAL_DAYS * 30.4, 2),
        "wr": round(wins / max(n, 1), 4),
        "pnl_usd": round(pnl, 2),
        "annual_pnl_usd": round(pnl / TOTAL_DAYS * 365, 2),
        "liquidations": sum(r["liquidations"] for r in periods.values()),
        "max_period_dd_usd": max(r["max_dd_usd"] for r in periods.values()),
        "min_period_pnl_usd": min(r["pnl_usd"] for r in periods.values()),
        "all_periods_positive": all(r["pnl_usd"] > 0 for r in periods.values()),
    }


def main() -> None:
    print("G7830 exit-profile high-WR tuning starting...", flush=True)
    t0 = time.time()
    caches = {}
    for period in PERIODS:
        dfs = build_period_cache(period, "no_dead")
        add_btc_regime(dfs)
        caches[period.name] = dfs

    rows_1309 = json.loads((SCRIPTS / "g1309_watch_confirm_breakout_results.json").read_text(encoding="utf-8"))["all_results"]
    base_ids = ["G4452", "G4456", "G4662", "G4677"]
    bases: dict[str, tuple[str, dict[str, Any]]] = {}
    for spec in g1307_specs():
        if spec["id"] in base_ids:
            bases[spec["id"]] = ("g1307", spec)
    for row in rows_1309:
        if row["id"] in base_ids:
            bases[row["id"]] = ("g1309", row["spec"])

    exits = []
    idx = 783000
    for hold in [3, 6, 9, 12]:
        for tp in [0.0125, 0.015, 0.020, 0.025]:
            for sl in [0.020, 0.025, 0.030, 0.040]:
                if sl < tp * 0.9:
                    continue
                exits.append({"exit_id": f"E{idx}", "hold": hold, "tp_pct": tp, "sl_pct": sl, "lev": 5.0, "size": 0.10, "max_conc": 5})
                idx += 1
    results = []
    for bid, (kind, base_spec) in bases.items():
        event_cache = {}
        for period in PERIODS:
            dfs = caches[period.name]
            event_cache[period.name] = adaptive_breakout_events(dfs, base_spec) if kind == "g1307" else watch_confirm_events(dfs, base_spec)
        for ex in exits:
            periods = {}
            keys = set()
            for period in PERIODS:
                res = simulate(event_cache[period.name], caches[period.name], ex, period.name, period.days)
                keys.update(map(tuple, res.pop("keys")))
                periods[period.name] = res
            w = summarize(periods, keys)
            row = {
                "id": f"{bid}_{ex['exit_id']}",
                "base_id": bid,
                "exit": ex,
                "periods": periods,
                "weighted": w,
                "pass_wr65_tpm8": w["wr"] >= 0.65 and w["trades_per_month"] >= 8 and w["pnl_usd"] > 0 and w["all_periods_positive"] and w["liquidations"] == 0,
                "pass_wr69_tpm8": w["wr"] >= 0.69 and w["trades_per_month"] >= 8 and w["pnl_usd"] > 0 and w["all_periods_positive"] and w["liquidations"] == 0,
            }
            results.append(row)
        print(f"  {bid} done", flush=True)

    ranked = sorted(
        results,
        key=lambda r: (
            r["pass_wr69_tpm8"],
            r["pass_wr65_tpm8"],
            r["weighted"]["wr"],
            r["weighted"]["trades_per_month"],
            r["weighted"]["annual_pnl_usd"],
        ),
        reverse=True,
    )
    top_positive = sorted(
        [
            r
            for r in results
            if r["weighted"]["pnl_usd"] > 0
            and r["weighted"]["all_periods_positive"]
            and r["weighted"]["trades_per_month"] >= 8
            and r["weighted"]["liquidations"] == 0
        ],
        key=lambda r: (
            r["weighted"]["wr"],
            r["weighted"]["trades_per_month"],
            r["weighted"]["annual_pnl_usd"],
        ),
        reverse=True,
    )
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": "Can exit tuning lift high-cadence sleeves to WR 65-69% while preserving positive full-window PnL?",
        "n_specs": len(results),
        "n_pass_wr65_tpm8": sum(r["pass_wr65_tpm8"] for r in results),
        "n_pass_wr69_tpm8": sum(r["pass_wr69_tpm8"] for r in results),
        "top": ranked[:100],
        "top_positive_tpm8": top_positive[:100],
        "elapsed_sec": round(time.time() - t0, 2),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)
    print(json.dumps(ranked[0]["weighted"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
