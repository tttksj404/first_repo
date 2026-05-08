"""G1307 controlled-loose breakout search.

G1306 showed that very loose starter entries are not worth trading. This pass
searches the narrower zone between strict G4006 and the failed loose variants:
lower one gate at a time, keep entries as actual breakout continuations, and
compare exit profiles.
"""
from __future__ import annotations

import json
import sys
import time
from itertools import product
from pathlib import Path
from typing import Any

ROOT = Path(r"C:\Users\SSAFY\Desktop\first_repo")
SCRIPTS = ROOT / "quant_binance" / "strategies" / "_scripts"
sys.path.insert(0, str(SCRIPTS))

from g1300_two_slot_search import BASELINE  # type: ignore
from g1304_multi_family_non_overlap_search import G1995_SPEC, keys_for_anchor  # type: ignore
from g1306_loose_breakout_adaptive_search import (  # type: ignore
    evaluate,
)
from g900_ensemble_discovery import PERIODS, add_btc_regime, build_period_cache  # type: ignore

OUT = SCRIPTS / "g1307_controlled_loose_breakout_results.json"


def candidate_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    idx = 4450
    gates = [
        {"break_bps": 50, "min_ret_24h": 0.10, "min_vol_ratio": 3.0, "label": "strict"},
        {"break_bps": 30, "min_ret_24h": 0.10, "min_vol_ratio": 3.0, "label": "break30"},
        {"break_bps": 50, "min_ret_24h": 0.08, "min_vol_ratio": 3.0, "label": "ret8"},
        {"break_bps": 50, "min_ret_24h": 0.10, "min_vol_ratio": 2.5, "label": "vol25"},
        {"break_bps": 30, "min_ret_24h": 0.08, "min_vol_ratio": 3.0, "label": "break30_ret8"},
        {"break_bps": 30, "min_ret_24h": 0.10, "min_vol_ratio": 2.5, "label": "break30_vol25"},
        {"break_bps": 50, "min_ret_24h": 0.08, "min_vol_ratio": 2.5, "label": "ret8_vol25"},
    ]
    exits = [
        {"hold": 36, "lev": 8.0, "size": 0.20, "tp_pct": 0.06, "sl_pct": 0.08, "label": "g4006_exit"},
        {"hold": 24, "lev": 7.0, "size": 0.18, "tp_pct": 0.05, "sl_pct": 0.065, "label": "mid_exit"},
        {"hold": 18, "lev": 6.0, "size": 0.16, "tp_pct": 0.04, "sl_pct": 0.055, "label": "fast_exit"},
        {"hold": 12, "lev": 5.0, "size": 0.14, "tp_pct": 0.03, "sl_pct": 0.04, "label": "scalp_exit"},
    ]
    for gate, exit_profile in product(gates, exits):
        trade = {k: exit_profile[k] for k in ["hold", "lev", "size", "tp_pct", "sl_pct"]}
        label = f"{gate['label']}_{exit_profile['label']}"
        specs.append(
            {
                "id": f"G{idx}",
                "desc": f"controlled loose breakout {label}",
                "univ": "no_dead",
                "max_conc": 5,
                "max_hold": max(36, int(exit_profile["hold"])),
                "entry": {
                    "break_bps": gate["break_bps"],
                    "min_ret_24h": gate["min_ret_24h"],
                    "min_vol_ratio": gate["min_vol_ratio"],
                    "atr_min": 0,
                    "atr_max": 8,
                },
                "bucket_rules": {
                    "starter": {"trade": trade},
                    "standard": {
                        "min_ret_24h": gate["min_ret_24h"],
                        "min_vol_ratio": gate["min_vol_ratio"],
                        "min_strength_bps": gate["break_bps"],
                        "trade": trade,
                    },
                    "strong": {
                        "min_ret_24h": gate["min_ret_24h"],
                        "min_vol_ratio": gate["min_vol_ratio"],
                        "min_strength_bps": gate["break_bps"],
                        "trade": trade,
                    },
                },
                "labels": {"gate": gate["label"], "exit": exit_profile["label"]},
            }
        )
        idx += 1
    return specs


def main() -> None:
    print("G1307 controlled-loose breakout search starting...")
    t0 = time.time()
    caches: dict[str, dict[str, Any]] = {"no_dead": {}, "top10": {}}
    for univ in caches:
        for period in PERIODS:
            dfs = build_period_cache(period, univ)
            add_btc_regime(dfs)
            caches[univ][period.name] = dfs
            print(f"  loaded {period.name}/{univ}: {len(dfs)} symbols")

    anchors = {
        "G1165": keys_for_anchor(BASELINE, caches),
        "G1995": keys_for_anchor(G1995_SPEC, caches),
    }
    print(f"  anchors: G1165={len(anchors['G1165'])} G1995={len(anchors['G1995'])}")

    results = []
    for spec in candidate_specs():
        res = evaluate(spec, caches, anchors)
        results.append(res)
        w = res["weighted"]
        if res["verdict"] == "PASS" or w["annual_pnl_usd"] >= 90:
            print(
                f"  {res['id']} {spec['labels']} n={w['n']:>4} wr={w['wr']:.3f} "
                f"ann={w['annual_pnl_usd']:>8.2f} dd={w['max_period_dd_usd']:>7.2f} "
                f"minp={w['min_period_pnl_usd']:>7.2f} verdict={res['verdict']}"
            )

    ranked = sorted(results, key=lambda r: (r["verdict"] == "PASS", r["score"]), reverse=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": "Which controlled-loose breakout gate increases entries without losing G4006 edge?",
        "criteria": {
            "n_min": 100,
            "wr_min": 0.54,
            "annual_min_usd": 100,
            "all_periods_positive": True,
            "liquidations": 0,
            "max_dd_usd": 160,
            "overlap_j_max_each_anchor": 0.05,
        },
        "anchors": {"G1165_keys": len(anchors["G1165"]), "G1995_keys": len(anchors["G1995"])},
        "n_specs": len(results),
        "n_pass": sum(1 for r in results if r["verdict"] == "PASS"),
        "top": ranked[:12],
        "all_results": results,
        "elapsed_sec": round(time.time() - t0, 2),
    }
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
