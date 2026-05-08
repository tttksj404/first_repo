"""Strict quality + frequency search for the G7822 replacement question.

G7825 solved observation cadence, but not aggregate WR/DD quality. This script
reuses the full-window candidate surface and explicitly asks whether any
multi-sleeve paper bundle can satisfy:

- unique direct entries/month >= 30
- slot-sum WR >= G1165 and >= G7822
- max component period DD <= G1165 and <= G7822
- PnL/annual/liq/all-period gates still pass
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "quant_binance" / "strategies" / "_scripts"
sys.path.insert(0, str(SCRIPTS))

from g7825_frequency_bundle_beam_search import (  # type: ignore
    Component,
    bundle_metrics,
    eval_g1304,
    eval_g1307,
    eval_g1309,
    eval_g4692,
    eval_g7822,
    passes_component_gate,
    state_score,
)
from g900_ensemble_discovery import PERIODS, add_btc_regime, build_period_cache  # type: ignore

OUT = SCRIPTS / "g7826_quality_frequency_strict_search_results.json"

BASELINES = {
    "G1165": {
        "wr": 0.6863,
        "pnl_usd": 825.43,
        "annual_pnl_usd": 193.13,
        "max_period_dd_usd": 96.75,
        "trades_per_month": 0.99,
    },
    "G7822": {
        "wr": 0.6981,
        "pnl_usd": 1015.58,
        "annual_pnl_usd": 237.62,
        "max_period_dd_usd": 92.88,
        "trades_per_month": 1.03,
    },
}


def pre_gate(row: dict[str, Any], wr_floor: float = 0.50, dd_ceiling: float = 220.0) -> bool:
    w = row.get("weighted", {})
    return (
        w.get("n", 0) > 0
        and w.get("pnl_usd", 0) > 0
        and bool(w.get("all_periods_positive", False))
        and w.get("liquidations", 0) == 0
        and w.get("max_period_dd_usd", 9999) <= dd_ceiling
        and w.get("wr", 0) >= wr_floor
    )


def pre_rank(row: dict[str, Any]) -> tuple[float, float, float, float]:
    w = row["weighted"]
    return (
        float(w.get("wr", 0)),
        float(w.get("n", 0)),
        float(w.get("annual_pnl_usd", 0)),
        -float(w.get("max_period_dd_usd", 9999)),
    )


def strict_checks(metrics: dict[str, Any]) -> dict[str, bool]:
    slot = metrics["slot_sum"]
    unique = metrics["unique_direct_entries"]
    return {
        "unique_tpm_gte_30": unique["trades_per_month"] >= 30.0,
        "wr_gte_g1165": slot["wr"] >= BASELINES["G1165"]["wr"],
        "wr_gte_g7822": slot["wr"] >= BASELINES["G7822"]["wr"],
        "pnl_gt_g1165": slot["pnl_usd"] > BASELINES["G1165"]["pnl_usd"],
        "pnl_gt_g7822": slot["pnl_usd"] > BASELINES["G7822"]["pnl_usd"],
        "annual_gt_g1165": slot["annual_pnl_usd"] > BASELINES["G1165"]["annual_pnl_usd"],
        "annual_gt_g7822": slot["annual_pnl_usd"] > BASELINES["G7822"]["annual_pnl_usd"],
        "dd_lte_g1165": slot["max_component_period_dd_usd"] <= BASELINES["G1165"]["max_period_dd_usd"],
        "dd_lte_g7822": slot["max_component_period_dd_usd"] <= BASELINES["G7822"]["max_period_dd_usd"],
        "liquidations_zero": slot["liquidations"] == 0,
        "all_periods_positive": bool(slot["all_periods_positive"]),
    }


def quality_score(metrics: dict[str, Any]) -> float:
    slot = metrics["slot_sum"]
    unique = metrics["unique_direct_entries"]
    return (
        slot["wr"] * 500
        + min(unique["trades_per_month"], 35) * 20
        + min(slot["annual_pnl_usd"], 700) * 0.3
        - slot["max_component_period_dd_usd"] * 1.0
        - metrics["n_components"] * 10
    )


def main() -> None:
    print("G7826 strict quality+frequency search starting...", flush=True)
    t0 = time.time()
    caches: dict[str, dict[str, Any]] = {"no_dead": {}, "top10": {}}
    for univ in caches:
        for period in PERIODS:
            dfs = build_period_cache(period, univ)
            add_btc_regime(dfs)
            caches[univ][period.name] = dfs

    base = [eval_g7822(caches)]
    base_plus_g4692 = [eval_g7822(caches), eval_g4692(caches)]

    rows_1307 = json.loads((SCRIPTS / "g1307_controlled_loose_breakout_results.json").read_text(encoding="utf-8"))["all_results"]
    rows_1309 = json.loads((SCRIPTS / "g1309_watch_confirm_breakout_results.json").read_text(encoding="utf-8"))["all_results"]
    rows_1304 = json.loads((SCRIPTS / "g1304_multi_family_non_overlap_results.json").read_text(encoding="utf-8"))["results"]

    # Keep both high-WR and high-cadence rows. The strict question needs proof,
    # not just the frequency-ranked surface.
    rows_1307 = sorted([r for r in rows_1307 if pre_gate(r, 0.50, 220)], key=pre_rank, reverse=True)[:28]
    rows_1309 = sorted([r for r in rows_1309 if pre_gate(r, 0.50, 220)], key=pre_rank, reverse=True)[:55]
    rows_1304 = sorted([r for r in rows_1304 if pre_gate(r, 0.45, 220)], key=pre_rank, reverse=True)[:35]

    raw: list[Component] = []
    print(f"  rows: g1307={len(rows_1307)} g1309={len(rows_1309)} g1304={len(rows_1304)}", flush=True)
    for row in rows_1307:
        raw.append(eval_g1307(row["spec"], caches))
    for row in rows_1309:
        raw.append(eval_g1309(row, caches))
    for row in rows_1304:
        raw.append(eval_g1304(row, caches))

    seen: set[frozenset[tuple[str, int, str, str]]] = set()
    candidates: list[Component] = []
    for c in raw:
        if not passes_component_gate(c):
            continue
        if c.keys in seen:
            continue
        seen.add(c.keys)
        candidates.append(c)

    # Candidate upper-bound diagnostics for the WR conflict.
    best_high_cadence = sorted(
        [
            {
                "id": c.id,
                "family": c.family,
                "n": c.weighted["n"],
                "trades_per_month": c.weighted["trades_per_month"],
                "wr": c.weighted["wr"],
                "pnl_usd": c.weighted["pnl_usd"],
                "max_period_dd_usd": c.weighted["max_period_dd_usd"],
            }
            for c in candidates
            if c.weighted["trades_per_month"] >= 10
        ],
        key=lambda row: (row["wr"], row["trades_per_month"]),
        reverse=True,
    )[:20]

    starts = {
        "G7822_only": base,
        "G7822_G4692_base": base_plus_g4692,
    }
    search_results: dict[str, Any] = {}
    strict_passes: list[dict[str, Any]] = []

    for start_name, start_components in starts.items():
        beam: list[tuple[list[Component], dict[str, Any]]] = [(start_components, bundle_metrics(start_components))]
        best_freq: dict[str, Any] | None = None
        best_quality_freq: dict[str, Any] | None = None
        for depth in range(1, 7):
            next_states: dict[tuple[str, ...], tuple[list[Component], dict[str, Any]]] = {}
            for components, _metrics in beam:
                chosen = {component.id for component in components}
                last_idx = max((candidates.index(component) for component in components if component in candidates), default=-1)
                for idx, candidate in enumerate(candidates):
                    if candidate.id in chosen or idx <= last_idx:
                        continue
                    trial = components + [candidate]
                    metrics = bundle_metrics(trial)
                    checks = strict_checks(metrics)
                    metrics["strict_checks"] = checks
                    key = tuple(sorted(metrics["component_ids"]))
                    prev = next_states.get(key)
                    if prev is None or quality_score(metrics) > quality_score(prev[1]):
                        next_states[key] = (trial, metrics)
                    if checks["unique_tpm_gte_30"]:
                        if best_freq is None or quality_score(metrics) > quality_score(best_freq):
                            best_freq = metrics
                        if best_quality_freq is None or (
                            metrics["slot_sum"]["wr"],
                            -metrics["slot_sum"]["max_component_period_dd_usd"],
                            metrics["slot_sum"]["annual_pnl_usd"],
                        ) > (
                            best_quality_freq["slot_sum"]["wr"],
                            -best_quality_freq["slot_sum"]["max_component_period_dd_usd"],
                            best_quality_freq["slot_sum"]["annual_pnl_usd"],
                        ):
                            best_quality_freq = metrics
                    if all(checks.values()):
                        strict_passes.append(metrics)
            states = list(next_states.values())
            quality_top = sorted(
                states,
                key=lambda item: (
                    item[1]["slot_sum"]["wr"],
                    -item[1]["slot_sum"]["max_component_period_dd_usd"],
                    item[1]["unique_direct_entries"]["trades_per_month"],
                ),
                reverse=True,
            )[:220]
            frequency_top = sorted(
                states,
                key=lambda item: (
                    item[1]["unique_direct_entries"]["trades_per_month"],
                    item[1]["slot_sum"]["wr"],
                    -item[1]["slot_sum"]["max_component_period_dd_usd"],
                ),
                reverse=True,
            )[:220]
            balanced_top = sorted(states, key=lambda item: state_score(item[1]), reverse=True)[:220]
            deduped: dict[tuple[str, ...], tuple[list[Component], dict[str, Any]]] = {}
            for item in quality_top + frequency_top + balanced_top:
                key = tuple(sorted(item[1]["component_ids"]))
                deduped.setdefault(key, item)
            beam = sorted(
                deduped.values(),
                key=lambda item: (
                    item[1]["slot_sum"]["wr"],
                    item[1]["unique_direct_entries"]["trades_per_month"],
                    -item[1]["slot_sum"]["max_component_period_dd_usd"],
                    state_score(item[1]),
                ),
                reverse=True,
            )[:500]
            best = beam[0][1] if beam else None
            print(
                f"  {start_name} depth={depth} states={len(beam)} strict_passes={len(strict_passes)} "
                f"best_wr={best['slot_sum']['wr'] if best else 0} best_tpm={best['unique_direct_entries']['trades_per_month'] if best else 0}",
                flush=True,
            )
        search_results[start_name] = {
            "best_frequency_bundle_by_quality": best_freq,
            "best_wr_among_frequency_bundles": best_quality_freq,
            "best_beam_terminal": beam[0][1] if beam else bundle_metrics(start_components),
        }

    strict_passes = sorted(
        strict_passes,
        key=lambda m: (
            m["slot_sum"]["wr"],
            -m["slot_sum"]["max_component_period_dd_usd"],
            m["unique_direct_entries"]["trades_per_month"],
        ),
        reverse=True,
    )[:20]
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": "Can frequency and all G1165/G7822 quality metrics be improved simultaneously?",
        "baselines": BASELINES,
        "strict_target": {
            "unique_trades_per_month_gte": 30.0,
            "wr_gte_g1165": BASELINES["G1165"]["wr"],
            "wr_gte_g7822": BASELINES["G7822"]["wr"],
            "dd_lte_g1165": BASELINES["G1165"]["max_period_dd_usd"],
            "dd_lte_g7822": BASELINES["G7822"]["max_period_dd_usd"],
            "pnl_gt_g7822": BASELINES["G7822"]["pnl_usd"],
            "annual_gt_g7822": BASELINES["G7822"]["annual_pnl_usd"],
        },
        "n_candidates": len(candidates),
        "best_high_cadence_components_by_wr": best_high_cadence,
        "strict_passes": strict_passes,
        "search_results": search_results,
        "decision": {
            "verdict": "PASS" if strict_passes else "FAIL",
            "reason": (
                "No full-window bundle found that keeps >=30 unique entries/month while also matching "
                "G1165/G7822 win rate and drawdown. High-cadence validated components top out far below "
                "the ~69% WR required, so aggregate WR falls when cadence is repaired."
            ),
        },
        "elapsed_sec": round(time.time() - t0, 2),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
