"""Solve the G7822 paper-frequency problem with multi-sleeve bundle search.

G7824 proved that one extra full-window sleeve was not enough. This pass opens
the surface to multiple already-tested full-window sleeves and ranks bundles by
de-duplicated direct entries, not raw slot-sum counts.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "quant_binance" / "strategies" / "_scripts"
sys.path.insert(0, str(SCRIPTS))

from g1300_two_slot_search import simulate_with_keys  # type: ignore
from g1304_multi_family_non_overlap_search import events_for_spec  # type: ignore
from g1306_loose_breakout_adaptive_search import adaptive_breakout_events, simulate_adaptive  # type: ignore
from g1309_watch_confirm_breakout_search import simulate as simulate_breakout  # type: ignore
from g1309_watch_confirm_breakout_search import watch_confirm_events  # type: ignore
from g7822_g4692_frequency_solution import G4692_SPEC, G7822_EXCLUDED, G7822_SPEC, weighted  # type: ignore
from g900_ensemble_discovery import PERIODS, add_btc_regime, build_period_cache, ch1_events  # type: ignore

OUT = SCRIPTS / "g7825_frequency_bundle_beam_search_results.json"
TOTAL_DAYS = sum(period.days for period in PERIODS)


@dataclass(frozen=True)
class Component:
    id: str
    family: str
    desc: str
    spec: dict[str, Any]
    weighted: dict[str, Any]
    periods: dict[str, Any]
    keys: frozenset[tuple[str, int, str, str]]


def strip_keys(result: dict[str, Any]) -> tuple[dict[str, Any], set[tuple[str, int, str, str]]]:
    keys = set(map(tuple, result.pop("keys")))
    return result, keys


def trades_per_month(n: int) -> float:
    return round(n / TOTAL_DAYS * 30.4, 2)


def eval_g7822(caches: dict[str, dict[str, Any]]) -> Component:
    periods: dict[str, Any] = {}
    keys: set[tuple[str, int, str, str]] = set()
    for period in PERIODS:
        dfs = {sym: df for sym, df in caches["no_dead"][period.name].items() if sym not in G7822_EXCLUDED}
        result, period_keys = strip_keys(
            simulate_with_keys(ch1_events(dfs, G7822_SPEC["engine"]), dfs, G7822_SPEC["max_conc"], period.days, period.name)
        )
        periods[period.name] = result
        keys.update(period_keys)
    return Component("G7822", "ch1_quality", "quality CH1 replacement", G7822_SPEC, weighted(periods), periods, frozenset(keys))


def eval_g4692(caches: dict[str, dict[str, Any]]) -> Component:
    periods: dict[str, Any] = {}
    keys: set[tuple[str, int, str, str]] = set()
    for period in PERIODS:
        dfs = caches["no_dead"][period.name]
        result, period_keys = strip_keys(simulate_breakout(watch_confirm_events(dfs, G4692_SPEC), dfs, 5, period.days, period.name))
        periods[period.name] = result
        keys.update(period_keys)
    return Component("G4692", "watch_confirm", "watch-confirm breakout mid", G4692_SPEC, weighted(periods), periods, frozenset(keys))


def eval_g1307(spec: dict[str, Any], caches: dict[str, dict[str, Any]]) -> Component:
    periods: dict[str, Any] = {}
    keys: set[tuple[str, int, str, str]] = set()
    for period in PERIODS:
        dfs = caches[spec["univ"]][period.name]
        result, period_keys = strip_keys(simulate_adaptive(adaptive_breakout_events(dfs, spec), dfs, spec["max_conc"], period.days, period.name))
        periods[period.name] = result
        keys.update(period_keys)
    return Component(spec["id"], "controlled_loose_breakout", spec["desc"], spec, weighted(periods), periods, frozenset(keys))


def eval_g1309(row: dict[str, Any], caches: dict[str, dict[str, Any]]) -> Component:
    spec = row["spec"]
    periods: dict[str, Any] = {}
    keys: set[tuple[str, int, str, str]] = set()
    for period in PERIODS:
        dfs = caches["no_dead"][period.name]
        result, period_keys = strip_keys(simulate_breakout(watch_confirm_events(dfs, spec), dfs, 5, period.days, period.name))
        periods[period.name] = result
        keys.update(period_keys)
    return Component(row["id"], "watch_confirm", row["desc"], spec, weighted(periods), periods, frozenset(keys))


def eval_g1304(row: dict[str, Any], caches: dict[str, dict[str, Any]]) -> Component:
    spec = row["spec"]
    periods: dict[str, Any] = {}
    keys: set[tuple[str, int, str, str]] = set()
    for period in PERIODS:
        dfs = caches[spec["univ"]][period.name]
        result, period_keys = strip_keys(simulate_with_keys(events_for_spec(dfs, spec), dfs, spec["max_conc"], period.days, period.name))
        periods[period.name] = result
        keys.update(period_keys)
    return Component(row["id"], row["family"], row["family"], spec, weighted(periods), periods, frozenset(keys))


def passes_component_gate(component: Component) -> bool:
    w = component.weighted
    return (
        w["n"] > 0
        and w["pnl_usd"] > 0
        and w["all_periods_positive"]
        and w["liquidations"] == 0
        and w["max_period_dd_usd"] <= 190
        and w["wr"] >= 0.50
    )


def bundle_metrics(components: list[Component]) -> dict[str, Any]:
    union: set[tuple[str, int, str, str]] = set()
    for component in components:
        union.update(component.keys)
    n = sum(c.weighted["n"] for c in components)
    pnl = sum(c.weighted["pnl_usd"] for c in components)
    wins = sum(c.weighted["wr"] * c.weighted["n"] for c in components)
    liquidations = sum(c.weighted["liquidations"] for c in components)
    per_period = {}
    for period in PERIODS:
        pn = sum(c.periods[period.name]["n"] for c in components)
        ppnl = sum(c.periods[period.name]["pnl_usd"] for c in components)
        pwins = sum(c.periods[period.name]["wr"] * c.periods[period.name]["n"] for c in components)
        per_period[period.name] = {
            "slot_sum_n": pn,
            "slot_sum_trades_per_month": round(pn / period.days * 30.4, 2),
            "slot_sum_wr": round(pwins / max(pn, 1), 4),
            "slot_sum_pnl_usd": round(ppnl, 2),
        }
    return {
        "component_ids": [c.id for c in components],
        "component_families": [c.family for c in components],
        "n_components": len(components),
        "slot_sum": {
            "n": n,
            "trades_per_month": trades_per_month(n),
            "wr": round(wins / max(n, 1), 4),
            "pnl_usd": round(pnl, 2),
            "annual_pnl_usd": round(pnl / TOTAL_DAYS * 365, 2),
            "all_periods_positive": all(c.weighted["all_periods_positive"] for c in components),
            "liquidations": liquidations,
            "max_component_period_dd_usd": max(c.weighted["max_period_dd_usd"] for c in components),
        },
        "unique_direct_entries": {
            "n": len(union),
            "trades_per_month": trades_per_month(len(union)),
        },
        "per_period_slot_sum": per_period,
    }


def state_score(metrics: dict[str, Any]) -> float:
    unique_tpm = metrics["unique_direct_entries"]["trades_per_month"]
    slot = metrics["slot_sum"]
    return (
        unique_tpm * 100
        + slot["wr"] * 100
        + min(slot["annual_pnl_usd"], 600) * 0.20
        - max(0.0, slot["max_component_period_dd_usd"] - 130) * 0.40
        - metrics["n_components"] * 8
    )


def main() -> None:
    print("G7825 frequency bundle beam search starting...", flush=True)
    t0 = time.time()
    caches: dict[str, dict[str, Any]] = {"no_dead": {}, "top10": {}}
    for univ in caches:
        for period in PERIODS:
            dfs = build_period_cache(period, univ)
            add_btc_regime(dfs)
            caches[univ][period.name] = dfs

    base = [eval_g7822(caches), eval_g4692(caches)]
    base_metrics = bundle_metrics(base)
    print(f"  base unique tpm={base_metrics['unique_direct_entries']['trades_per_month']}", flush=True)

    rows_1307 = json.loads((SCRIPTS / "g1307_controlled_loose_breakout_results.json").read_text(encoding="utf-8"))["all_results"]
    rows_1309 = json.loads((SCRIPTS / "g1309_watch_confirm_breakout_results.json").read_text(encoding="utf-8"))["all_results"]
    rows_1304 = json.loads((SCRIPTS / "g1304_multi_family_non_overlap_results.json").read_text(encoding="utf-8"))["results"]

    def pre_gate(row: dict[str, Any]) -> bool:
        w = row.get("weighted", {})
        return (
            w.get("n", 0) > 0
            and w.get("pnl_usd", 0) > 0
            and bool(w.get("all_periods_positive", False))
            and w.get("liquidations", 0) == 0
            and w.get("max_period_dd_usd", 9999) <= 190
            and w.get("wr", 0) >= 0.50
        )

    def pre_rank(row: dict[str, Any]) -> tuple[float, float, float]:
        w = row["weighted"]
        return (float(w.get("n", 0)), float(w.get("annual_pnl_usd", 0)), float(w.get("wr", 0)))

    rows_1307 = sorted([row for row in rows_1307 if pre_gate(row)], key=pre_rank, reverse=True)[:28]
    rows_1309 = sorted([row for row in rows_1309 if pre_gate(row)], key=pre_rank, reverse=True)[:55]
    rows_1304 = sorted([row for row in rows_1304 if pre_gate(row)], key=pre_rank, reverse=True)[:35]

    raw_components: list[Component] = []
    print(
        f"  pre-gated rows: g1307={len(rows_1307)} g1309={len(rows_1309)} g1304={len(rows_1304)}",
        flush=True,
    )
    for row in rows_1307:
        raw_components.append(eval_g1307(row["spec"], caches))
    for row in rows_1309:
        raw_components.append(eval_g1309(row, caches))
    for row in rows_1304:
        raw_components.append(eval_g1304(row, caches))

    seen_keys: set[frozenset[tuple[str, int, str, str]]] = set()
    candidates: list[Component] = []
    for component in raw_components:
        if component.id in {"G4692", "G7822"}:
            continue
        if not passes_component_gate(component):
            continue
        if component.keys in seen_keys:
            continue
        seen_keys.add(component.keys)
        candidates.append(component)

    base_keyset = set().union(*(component.keys for component in base))
    ranked_candidates = sorted(
        candidates,
        key=lambda c: (
            len(set(c.keys) - base_keyset),
            c.weighted["annual_pnl_usd"],
            c.weighted["wr"],
        ),
        reverse=True,
    )
    candidates = ranked_candidates[:90]
    print(f"  candidates retained={len(candidates)} from raw={len(raw_components)}", flush=True)

    beam: list[tuple[list[Component], dict[str, Any]]] = [(base, base_metrics)]
    passes: list[dict[str, Any]] = []
    beam_width = 250
    max_addons = 5

    for depth in range(1, max_addons + 1):
        next_states: dict[tuple[str, ...], tuple[list[Component], dict[str, Any]]] = {}
        for components, _metrics in beam:
            chosen = {component.id for component in components}
            last_idx = max((candidates.index(component) for component in components if component in candidates), default=-1)
            for idx, candidate in enumerate(candidates):
                if candidate.id in chosen or idx <= last_idx:
                    continue
                trial = components + [candidate]
                metrics = bundle_metrics(trial)
                if metrics["slot_sum"]["wr"] < 0.54:
                    continue
                if metrics["slot_sum"]["liquidations"] != 0:
                    continue
                if not metrics["slot_sum"]["all_periods_positive"]:
                    continue
                key = tuple(sorted(metrics["component_ids"]))
                prev = next_states.get(key)
                if prev is None or state_score(metrics) > state_score(prev[1]):
                    next_states[key] = (trial, metrics)
                if metrics["unique_direct_entries"]["trades_per_month"] >= 30.0:
                    passes.append(metrics)
        beam = sorted(next_states.values(), key=lambda item: state_score(item[1]), reverse=True)[:beam_width]
        best = beam[0][1] if beam else None
        print(
            f"  depth={depth} states={len(beam)} passes={len(passes)} "
            f"best_unique_tpm={best['unique_direct_entries']['trades_per_month'] if best else 0}",
            flush=True,
        )
        if passes:
            break

    best_passes = sorted(
        passes,
        key=lambda m: (
            m["unique_direct_entries"]["trades_per_month"],
            m["slot_sum"]["wr"],
            m["slot_sum"]["annual_pnl_usd"],
            -m["n_components"],
        ),
        reverse=True,
    )[:20]

    component_table = [
        {
            "id": c.id,
            "family": c.family,
            "desc": c.desc,
            "weighted": c.weighted,
            "unique_keys": len(c.keys),
            "new_keys_vs_base": len(set(c.keys) - base_keyset),
            "spec": c.spec,
        }
        for c in candidates[:50]
    ]
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": "Can multi-sleeve full-window search solve the >=30 unique entries/month target?",
        "base": base_metrics,
        "candidate_gate": {
            "component_pnl_positive": True,
            "component_all_periods_positive": True,
            "component_liquidations": 0,
            "component_max_dd_lte": 190,
            "component_wr_gte": 0.50,
            "bundle_wr_gte": 0.54,
            "target_unique_trades_per_month": 30.0,
        },
        "n_raw_components": len(raw_components),
        "n_retained_components": len(candidates),
        "top_components": component_table,
        "best_passes": best_passes,
        "decision": {
            "verdict": "PASS" if best_passes else "FAIL",
            "best": best_passes[0] if best_passes else (beam[0][1] if beam else base_metrics),
            "interpretation": "Full-window multi-sleeve paper-observation bundle; not a single shared-equity live portfolio.",
        },
        "elapsed_sec": round(time.time() - t0, 2),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
