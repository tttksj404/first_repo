"""G1300 two-slot discovery for extra Oracle paper strategies.

Goal:
  Find two additional paper candidates beyond G1165. The extra slots should not
  be blind copies of G1165, so this search scores both standalone robustness and
  entry overlap against the deployed G1165 baseline.

Evidence gate:
  - three-period path simulation
  - TP/SL first-touch path exits
  - zero liquidations
  - all periods positive
  - drawdown <= 100 USD
"""
from __future__ import annotations

import json
import sys
import time
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(r"C:\Users\SSAFY\Desktop\first_repo")
SCRIPTS = ROOT / "quant_binance" / "strategies" / "_scripts"
sys.path.insert(0, str(SCRIPTS))

from g900_ensemble_discovery import (  # type: ignore
    COST_BPS,
    EQUITY,
    PERIODS,
    add_btc_regime,
    build_period_cache,
    ch1_events,
    event_return,
    resolve_conflicts,
)

OUT = SCRIPTS / "g1300_two_slot_results.json"

BASELINE = {
    "id": "G1165",
    "desc": "deployed_g1165_baseline",
    "univ": "no_dead",
    "max_conc": 5,
    "engines": {
        "ch1": {
            "thr": 80,
            "hold": 36,
            "atr_min": 3,
            "atr_max": 8,
            "lev": 10,
            "size": 0.25,
            "tp_pct": 0.14,
            "sl_pct": 0.075,
        }
    },
}


def simulate_with_keys(
    events: list[dict[str, Any]],
    dfs: dict[str, Any],
    max_conc: int,
    days: int,
    period_name: str,
) -> dict[str, Any]:
    events = resolve_conflicts(events)
    open_pos: list[tuple[int, str]] = []
    pnl = 0.0
    wins = 0
    liq = 0
    taken = 0
    by_side = {"long": {"n": 0, "pnl": 0.0}, "short": {"n": 0, "pnl": 0.0}}
    curve = [0.0]
    keys: list[tuple[str, int, str, str]] = []

    for ev in events:
        ts = ev["ts"]
        sym = ev["sym"]
        open_pos = [p for p in open_pos if p[0] > ts]
        if any(p[1] == sym for p in open_pos):
            continue
        if len(open_pos) >= max_conc:
            continue
        df = dfs.get(sym)
        if df is None:
            continue
        net_pct, liquidated, _ = event_return(
            df,
            ev["idx"],
            ev["side"],
            ev["hold"],
            ev["lev"],
            ev.get("tp_pct"),
            ev.get("sl_pct"),
        )
        trade_pnl = EQUITY * ev["size"] * net_pct
        pnl += trade_pnl
        curve.append(pnl)
        taken += 1
        wins += int(trade_pnl > 0)
        liq += int(liquidated)
        by_side[ev["side"]]["n"] += 1
        by_side[ev["side"]]["pnl"] += trade_pnl
        open_pos.append((ts + ev["hold"] * 3600 * 1000, sym))
        keys.append((period_name, int(ts), str(sym), ev["side"]))

    arr = np.array(curve, dtype=float)
    peak = np.maximum.accumulate(arr)
    max_dd = float((peak - arr).max()) if len(arr) else 0.0
    return {
        "n": taken,
        "wr": wins / taken if taken else 0.0,
        "pnl_usd": round(pnl, 2),
        "annual_pnl_usd": round(pnl / days * 365, 2) if days else 0.0,
        "monthly_pnl_usd": round(pnl / days * 30.4, 2) if days else 0.0,
        "liquidations": liq,
        "liq_rate": liq / taken if taken else 0.0,
        "max_dd_usd": round(max_dd, 2),
        "by_side": {k: {"n": v["n"], "pnl": round(v["pnl"], 2)} for k, v in by_side.items()},
        "keys": keys,
    }


def candidate_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    idx = 1300
    universes = ["no_dead", "top10"]
    thresholds = [80, 82]
    holds = [24, 36, 48]
    atr_mins = [0, 3]
    atr_maxs = [8, 10]
    profiles = [
        {"lev": 5, "size": 0.35},
        {"lev": 6, "size": 0.35},
        {"lev": 8, "size": 0.30},
        {"lev": 10, "size": 0.25},
    ]
    tps = [0.12, 0.14, 0.16]
    sls = [0.06, 0.075]
    max_concs = [5]

    for univ, thr, hold, atr_min, atr_max, profile, tp, sl, max_conc in product(
        universes, thresholds, holds, atr_mins, atr_maxs, profiles, tps, sls, max_concs
    ):
        if atr_min >= atr_max:
            continue
        desc = "slot_ch1_top10" if univ == "top10" else "slot_ch1_no_dead"
        specs.append(
            {
                "id": f"G{idx}",
                "desc": desc,
                "univ": univ,
                "max_conc": max_conc,
                "engines": {
                    "ch1": {
                        "thr": thr,
                        "hold": hold,
                        "atr_min": atr_min,
                        "atr_max": atr_max,
                        "lev": profile["lev"],
                        "size": profile["size"],
                        "tp_pct": tp,
                        "sl_pct": sl,
                    }
                },
            }
        )
        idx += 1
    return specs


def evaluate_spec(
    spec: dict[str, Any],
    caches: dict[str, dict[str, dict[str, Any]]],
    baseline_keys: set[tuple[str, int, str, str]],
) -> dict[str, Any]:
    period_results: dict[str, Any] = {}
    all_keys: set[tuple[str, int, str, str]] = set()
    ch1_cache: dict[str, list[dict[str, Any]]] = {}
    for period in PERIODS:
        dfs = caches[spec["univ"]][period.name]
        events = ch1_cache.setdefault(period.name, ch1_events(dfs, spec["engines"]["ch1"]))
        res = simulate_with_keys(events, dfs, spec["max_conc"], period.days, period.name)
        all_keys.update(res.pop("keys"))
        period_results[period.name] = res

    valid = [period_results[p.name] for p in PERIODS if period_results[p.name]["n"] > 0]
    total_n = sum(r["n"] for r in valid)
    total_pnl = sum(r["pnl_usd"] for r in valid)
    total_days = sum(p.days for p in PERIODS if period_results[p.name]["n"] > 0)
    wr = sum(r["wr"] * r["n"] for r in valid) / max(total_n, 1)
    annual = total_pnl / total_days * 365 if total_days else 0.0
    liq = sum(r["liquidations"] for r in valid)
    max_dd = max((r["max_dd_usd"] for r in valid), default=0.0)
    min_period_pnl = min((period_results[p.name]["pnl_usd"] for p in PERIODS), default=0.0)
    all_pos = all(period_results[p.name]["pnl_usd"] > 0 for p in PERIODS)
    overlap_n = len(all_keys & baseline_keys)
    overlap_vs_candidate = overlap_n / max(len(all_keys), 1)
    overlap_vs_baseline = overlap_n / max(len(baseline_keys), 1)
    jaccard = overlap_n / max(len(all_keys | baseline_keys), 1)

    weighted = {
        "n": total_n,
        "wr": round(wr, 4),
        "pnl_usd": round(total_pnl, 2),
        "annual_pnl_usd": round(annual, 2),
        "monthly_pnl_usd": round(annual / 12, 2),
        "all_periods_positive": all_pos,
        "min_period_pnl_usd": round(min_period_pnl, 2),
        "liquidations": liq,
        "liq_rate": round(liq / total_n, 4) if total_n else 0.0,
        "max_period_dd_usd": round(max_dd, 2),
        "baseline_overlap_n": overlap_n,
        "baseline_overlap_vs_candidate": round(overlap_vs_candidate, 4),
        "baseline_overlap_vs_baseline": round(overlap_vs_baseline, 4),
        "baseline_overlap_jaccard": round(jaccard, 4),
    }
    checks = {
        "n_>=_30": total_n >= 30,
        "wr_>=_60": wr >= 0.60,
        "annual_pnl_>=_120": annual >= 120,
        "all_periods_positive": all_pos,
        "liq_==_0": liq == 0,
        "max_period_dd_<=_100": max_dd <= 100,
    }
    slot_score = annual + wr * 60 + min_period_pnl * 0.2 - max_dd * 0.25 - jaccard * 55
    return {
        "id": spec["id"],
        "desc": spec["desc"],
        "spec": spec,
        "periods": period_results,
        "weighted": weighted,
        "slot_score": round(slot_score, 4),
        "decision": {"checks": checks, "verdict": "PASS" if all(checks.values()) else "FAIL"},
    }


def main() -> None:
    print("G1300 two-slot search starting...")
    t0 = time.time()
    caches: dict[str, dict[str, dict[str, Any]]] = {}
    for univ in ["no_dead", "top10"]:
        caches[univ] = {}
        for period in PERIODS:
            dfs = build_period_cache(period, univ)
            add_btc_regime(dfs)
            caches[univ][period.name] = dfs
            print(f"  loaded {period.name}/{univ}: {len(dfs)} symbols")

    baseline_eval = evaluate_spec(BASELINE, caches, set())
    baseline_keys: set[tuple[str, int, str, str]] = set()
    for period in PERIODS:
        dfs = caches[BASELINE["univ"]][period.name]
        events = ch1_events(dfs, BASELINE["engines"]["ch1"])
        res = simulate_with_keys(events, dfs, BASELINE["max_conc"], period.days, period.name)
        baseline_keys.update(res["keys"])
    print(f"  baseline G1165 keys: {len(baseline_keys)}")

    specs = candidate_specs()
    results = []
    for i, spec in enumerate(specs, 1):
        res = evaluate_spec(spec, caches, baseline_keys)
        results.append(res)
        if i % 250 == 0 or res["decision"]["verdict"] == "PASS":
            w = res["weighted"]
            print(
                f"{i:04d}/{len(specs)} {res['id']} {spec['univ']} "
                f"n={w['n']:>3} wr={w['wr']:.3f} ann={w['annual_pnl_usd']:>7.2f} "
                f"dd={w['max_period_dd_usd']:>6.2f} ov={w['baseline_overlap_jaccard']:.2f} "
                f"{res['decision']['verdict']}"
            )

    passers = [r for r in results if r["decision"]["verdict"] == "PASS"]
    ranked_by_slot = sorted(
        passers,
        key=lambda r: (
            r["slot_score"],
            -r["weighted"]["baseline_overlap_jaccard"],
            r["weighted"]["annual_pnl_usd"],
        ),
        reverse=True,
    )
    ranked_by_annual = sorted(passers, key=lambda r: r["weighted"]["annual_pnl_usd"], reverse=True)

    diversified = [
        r for r in ranked_by_slot
        if r["weighted"]["baseline_overlap_jaccard"] <= 0.80
    ]
    top10_pass = [r for r in ranked_by_slot if r["spec"]["univ"] == "top10"]
    no_dead_pass = [r for r in ranked_by_slot if r["spec"]["univ"] == "no_dead"]

    # Pick one top10 candidate and one no-dead expansion candidate. Without this
    # guard the top two are often near-identical ATR-max twins, which wastes an
    # Oracle paper slot.
    recommendations = []
    if top10_pass:
        recommendations.append(top10_pass[0])
    no_dead_low_overlap = [
        r for r in no_dead_pass
        if r["weighted"]["baseline_overlap_jaccard"] <= 0.80
    ]
    if no_dead_low_overlap:
        recommendations.append(no_dead_low_overlap[0])
    elif no_dead_pass:
        recommendations.append(no_dead_pass[0])
    for cand in ranked_by_slot:
        if len(recommendations) >= 2:
            break
        if cand["id"] not in {r["id"] for r in recommendations}:
            recommendations.append(cand)

    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cost_bps": COST_BPS,
        "equity": EQUITY,
        "baseline": baseline_eval,
        "n_specs": len(specs),
        "n_pass": len(passers),
        "decision_criteria": {
            "n_min": 30,
            "wr_min": 0.60,
            "annual_pnl_min_usd": 120,
            "all_periods_positive": True,
            "liquidations": 0,
            "max_period_dd_usd": 100,
            "slot_score_penalizes_overlap": True,
        },
        "recommended_two_slots": recommendations[:2],
        "top_by_slot_score": ranked_by_slot[:30],
        "top_by_annual": ranked_by_annual[:20],
        "results": results,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nPASS {len(passers)}/{len(specs)}")
    print("Recommended slots:")
    for r in recommendations[:2]:
        w = r["weighted"]
        ch = r["spec"]["engines"]["ch1"]
        print(
            f"  {r['id']} {r['desc']} score={r['slot_score']:.2f} "
            f"n={w['n']} wr={w['wr']:.3f} ann={w['annual_pnl_usd']:.2f} "
            f"mo={w['monthly_pnl_usd']:.2f} dd={w['max_period_dd_usd']:.2f} "
            f"ovJ={w['baseline_overlap_jaccard']:.3f} ovCand={w['baseline_overlap_vs_candidate']:.3f} "
            f"univ={r['spec']['univ']} maxc={r['spec']['max_conc']} "
            f"thr={ch['thr']} hold={ch['hold']} atr={ch['atr_min']}-{ch['atr_max']} "
            f"lev={ch['lev']} size={ch['size']} tp={ch['tp_pct']} sl={ch['sl_pct']}"
        )
    print(f"Wrote {OUT}")
    print(f"Elapsed {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
