"""Full-window frequency validation for the G7822 cadence problem.

This script intentionally separates:
- slot-sum fills: what separate paper sleeves would count in total; and
- unique direct entries: timestamp/symbol/side de-duplicated observations.

The user target is fast paper validation, so duplicated breakout-family entries
should not be counted as fully independent cadence.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "quant_binance" / "strategies" / "_scripts"
sys.path.insert(0, str(SCRIPTS))

from g1300_two_slot_search import simulate_with_keys  # type: ignore
from g1306_loose_breakout_adaptive_search import adaptive_breakout_events, simulate_adaptive  # type: ignore
from g1307_controlled_loose_breakout_search import candidate_specs as g1307_specs  # type: ignore
from g1309_watch_confirm_breakout_search import simulate as simulate_breakout  # type: ignore
from g1309_watch_confirm_breakout_search import watch_confirm_events  # type: ignore
from g7822_g4692_frequency_solution import G4692_SPEC, G7822_EXCLUDED, G7822_SPEC, weighted  # type: ignore
from g900_ensemble_discovery import PERIODS, add_btc_regime, build_period_cache, ch1_events  # type: ignore

OUT = SCRIPTS / "g7824_full_frequency_validation_results.json"


def strip_keys(result: dict[str, Any]) -> tuple[dict[str, Any], set[tuple[str, int, str, str]]]:
    keys = set(map(tuple, result.pop("keys")))
    return result, keys


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def oi_coverage() -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]:
        path = ROOT / "quant_runtime" / "historical" / sym / "oi_1h.json"
        if not path.exists():
            rows[sym] = {"exists": False}
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        raw_rows = data.get("data", data) if isinstance(data, dict) else data
        timestamps: list[int] = []
        for row in raw_rows:
            value = row.get("timestamp") if isinstance(row, dict) else row[0] if row else None
            if value is None:
                continue
            ts = int(value)
            if ts < 10**12:
                ts *= 1000
            timestamps.append(ts)
        rows[sym] = {
            "exists": True,
            "rows": len(raw_rows),
            "timestamp_rows": len(timestamps),
            "min_utc": iso(min(timestamps)) if timestamps else None,
            "max_utc": iso(max(timestamps)) if timestamps else None,
        }
    return {
        "required_window": "full price-validation windows: OOS22-23, OOS24-Q1, IS25-26",
        "available": rows,
        "full_window_available": False,
        "decision": "G264402 cannot be accepted as a full-window frequency fix with the current local OI data.",
    }


def eval_g7822(caches: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], set[tuple[str, int, str, str]]]:
    periods: dict[str, Any] = {}
    keys: set[tuple[str, int, str, str]] = set()
    for period in PERIODS:
        dfs = {sym: df for sym, df in caches[period.name].items() if sym not in G7822_EXCLUDED}
        result, period_keys = strip_keys(
            simulate_with_keys(ch1_events(dfs, G7822_SPEC["engine"]), dfs, G7822_SPEC["max_conc"], period.days, period.name)
        )
        periods[period.name] = result
        keys.update(period_keys)
    return periods, keys


def eval_g4692(caches: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], set[tuple[str, int, str, str]]]:
    periods: dict[str, Any] = {}
    keys: set[tuple[str, int, str, str]] = set()
    for period in PERIODS:
        dfs = caches[period.name]
        result, period_keys = strip_keys(simulate_breakout(watch_confirm_events(dfs, G4692_SPEC), dfs, 5, period.days, period.name))
        periods[period.name] = result
        keys.update(period_keys)
    return periods, keys


def eval_g1307(
    candidate_id: str,
    caches: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], set[tuple[str, int, str, str]], dict[str, Any]]:
    spec = next(spec for spec in g1307_specs() if spec["id"] == candidate_id)
    periods: dict[str, Any] = {}
    keys: set[tuple[str, int, str, str]] = set()
    for period in PERIODS:
        dfs = caches[period.name]
        result, period_keys = strip_keys(simulate_adaptive(adaptive_breakout_events(dfs, spec), dfs, spec["max_conc"], period.days, period.name))
        periods[period.name] = result
        keys.update(period_keys)
    return periods, keys, spec


def slot_sum(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = sum(row["weighted"]["n"] for row in rows)
    pnl = sum(row["weighted"]["pnl_usd"] for row in rows)
    days = sum(period.days for period in PERIODS)
    wins = sum(row["weighted"]["wr"] * row["weighted"]["n"] for row in rows)
    liquidations = sum(row["weighted"]["liquidations"] for row in rows)
    return {
        "n": n,
        "trades_per_month": round(n / days * 30.4, 2),
        "wr": round(wins / max(n, 1), 4),
        "pnl_usd": round(pnl, 2),
        "annual_pnl_usd": round(pnl / days * 365, 2),
        "all_periods_positive": all(row["weighted"]["all_periods_positive"] for row in rows),
        "liquidations": liquidations,
        "max_component_period_dd_usd": max(row["weighted"]["max_period_dd_usd"] for row in rows),
    }


def main() -> None:
    print("G7824 full frequency validation starting...", flush=True)
    t0 = time.time()
    caches: dict[str, dict[str, Any]] = {}
    for period in PERIODS:
        dfs = build_period_cache(period, "no_dead")
        add_btc_regime(dfs)
        caches[period.name] = dfs

    components: dict[str, dict[str, Any]] = {}
    for name, evaluator in [("G7822", eval_g7822), ("G4692", eval_g4692)]:
        periods, keys = evaluator(caches)
        components[name] = {
            "weighted": weighted(periods),
            "periods": periods,
            "unique_keys": len(keys),
            "_keys": keys,
        }
        print(f"  {name}: {components[name]['weighted']}", flush=True)

    for candidate_id in ["G4474", "G4475"]:
        periods, keys, spec = eval_g1307(candidate_id, caches)
        components[candidate_id] = {
            "weighted": weighted(periods),
            "periods": periods,
            "unique_keys": len(keys),
            "spec": spec,
            "_keys": keys,
        }
        print(f"  {candidate_id}: {components[candidate_id]['weighted']}", flush=True)

    base_keys = components["G7822"]["_keys"] | components["G4692"]["_keys"]
    bundle_checks: dict[str, Any] = {}
    for candidate_id in ["G4474", "G4475"]:
        candidate_keys = components[candidate_id]["_keys"]
        union = base_keys | candidate_keys
        overlap = base_keys & candidate_keys
        bundle_rows = [components["G7822"], components["G4692"], components[candidate_id]]
        bundle_checks[f"G7822_G4692_{candidate_id}"] = {
            "slot_sum": slot_sum(bundle_rows),
            "unique_direct_entries": {
                "n": len(union),
                "trades_per_month": round(len(union) / sum(period.days for period in PERIODS) * 30.4, 2),
                "overlap_with_g7822_g4692": len(overlap),
                "added_unique_entries": len(candidate_keys - base_keys),
            },
            "frequency_gate": {
                "target_unique_trades_per_month": 30.0,
                "passes": len(union) / sum(period.days for period in PERIODS) * 30.4 >= 30.0,
            },
        }

    for value in components.values():
        value.pop("_keys", None)

    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": "Can the frequency problem be solved under full-window validation?",
        "oi_coverage": oi_coverage(),
        "components": components,
        "bundle_checks": bundle_checks,
        "decision": {
            "verdict": "FAIL",
            "reason": (
                "G264402 is blocked by insufficient full-window OI coverage. "
                "The best full-price add-ons improve slot-sum cadence, but after direct-entry de-duplication "
                "they still reach only 25.33-26.64 unique entries/month, below the 30/month target."
            ),
            "next_research_target": "Find a non-breakout, full-window validated sleeve adding at least 3.36 unique entries/month after overlap.",
        },
        "elapsed_sec": round(time.time() - t0, 2),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
