"""G915 path-safe CH1 exit/veto search.

This round starts from G914 and searches only the dimensions that matter after
the G900 ensemble result:

  - TP/SL path exits
  - hold duration
  - leverage/size profiles
  - ATR band
  - optional funding veto

Funding is not treated as a standalone entry engine here. The prior G900 run
showed that naive funding-fade trades diluted the CH1 edge.
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

from g900_ensemble_discovery import (  # type: ignore
    PERIODS,
    add_btc_regime,
    build_period_cache,
    ch1_events,
    simulate,
)

OUT = SCRIPTS / "g915_exit_veto_results.json"


def candidate_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    idx = 915
    thresholds = [80, 82]
    holds = [24, 36, 48]
    atr_mins = [0, 3]
    atr_maxs = [8, 10]
    profiles = [
        {"lev": 6, "size": 0.35},
        {"lev": 8, "size": 0.30},
        {"lev": 10, "size": 0.25},
    ]
    tps = [0.10, 0.12, 0.14]
    sls = [0.060, 0.075]
    funding_vetoes = [None, 0.0008]

    for thr, hold, atr_min, atr_max, profile, tp, sl, veto in product(
        thresholds, holds, atr_mins, atr_maxs, profiles, tps, sls, funding_vetoes
    ):
        if atr_min >= atr_max:
            continue
        ch1 = {
            "thr": thr,
            "hold": hold,
            "atr_min": atr_min,
            "atr_max": atr_max,
            "lev": profile["lev"],
            "size": profile["size"],
            "tp_pct": tp,
            "sl_pct": sl,
        }
        if veto is not None:
            ch1["max_funding"] = veto
        specs.append(
            {
                "id": f"G{idx}",
                "desc": "path_safe_ch1_exit_veto",
                "univ": "no_dead",
                "max_conc": 5,
                "engines": {"ch1": ch1},
            }
        )
        idx += 1
    return specs


def evaluate_spec(spec: dict[str, Any], period_caches: dict[str, Any]) -> dict[str, Any]:
    period_results: dict[str, Any] = {}
    for period in PERIODS:
        dfs = period_caches[period.name]
        events = ch1_events(dfs, spec["engines"]["ch1"])
        period_results[period.name] = simulate(events, dfs, spec["max_conc"], period.days)

    valid = [r for r in period_results.values() if r["n"] > 0]
    total_n = sum(r["n"] for r in valid)
    total_pnl = sum(r["pnl_usd"] for r in valid)
    total_days = sum(p.days for p in PERIODS if period_results[p.name]["n"] > 0)
    weighted_wr = sum(r["wr"] * r["n"] for r in valid) / max(total_n, 1)
    annual = total_pnl / total_days * 365 if total_days else 0.0
    liq = sum(r["liquidations"] for r in valid)
    max_dd = max((r["max_dd_usd"] for r in valid), default=0.0)
    min_period_pnl = min((period_results[p.name]["pnl_usd"] for p in PERIODS), default=0.0)
    all_pos = all(period_results[p.name]["pnl_usd"] > 0 for p in PERIODS)
    weighted = {
        "n": total_n,
        "wr": round(weighted_wr, 4),
        "pnl_usd": round(total_pnl, 2),
        "annual_pnl_usd": round(annual, 2),
        "monthly_pnl_usd": round(annual / 12, 2),
        "all_periods_positive": all_pos,
        "min_period_pnl_usd": round(min_period_pnl, 2),
        "liquidations": liq,
        "liq_rate": round(liq / total_n, 4) if total_n else 0.0,
        "max_period_dd_usd": round(max_dd, 2),
    }
    checks = {
        "n_>=_30": total_n >= 30,
        "wr_>=_60": weighted_wr >= 0.60,
        "annual_pnl_>=_100": annual >= 100,
        "all_periods_positive": all_pos,
        "liq_==_0": liq == 0,
        "max_period_dd_<=_100": max_dd <= 100,
    }
    score = annual + weighted_wr * 50 + min_period_pnl * 0.25 - max_dd * 0.3
    return {
        "id": spec["id"],
        "desc": spec["desc"],
        "spec": spec,
        "periods": period_results,
        "weighted": weighted,
        "score": round(score, 4),
        "decision": {"checks": checks, "verdict": "PASS" if all(checks.values()) else "FAIL"},
    }


def main() -> None:
    print("G915 exit/veto search starting...")
    t0 = time.time()
    period_caches = {}
    for period in PERIODS:
        dfs = build_period_cache(period, "no_dead")
        add_btc_regime(dfs)
        period_caches[period.name] = dfs
        print(f"  loaded {period.name}: {len(dfs)} symbols")

    specs = candidate_specs()
    results = []
    for i, spec in enumerate(specs, 1):
        res = evaluate_spec(spec, period_caches)
        results.append(res)
        if i % 25 == 0 or res["decision"]["verdict"] == "PASS":
            w = res["weighted"]
            print(
                f"{i:03d}/{len(specs)} {res['id']} n={w['n']:>3} "
                f"wr={w['wr']:.3f} ann={w['annual_pnl_usd']:>7.2f} "
                f"dd={w['max_period_dd_usd']:>6.2f} liq={w['liq_rate']:.3f} "
                f"{res['decision']['verdict']}"
            )

    ranked = sorted(
        results,
        key=lambda r: (
            r["decision"]["verdict"] == "PASS",
            r["score"],
            r["weighted"]["annual_pnl_usd"],
            r["weighted"]["wr"],
        ),
        reverse=True,
    )
    passers = [r for r in results if r["decision"]["verdict"] == "PASS"]
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_specs": len(specs),
        "n_pass": len(passers),
        "decision_criteria": {
            "n_min": 30,
            "wr_min": 0.60,
            "annual_pnl_min_usd": 100,
            "all_periods_positive": True,
            "liquidations": 0,
            "max_period_dd_usd": 100,
        },
        "top": ranked[:20],
        "results": results,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nPASS {len(passers)}/{len(specs)}")
    for r in ranked[:10]:
        w = r["weighted"]
        ch1 = r["spec"]["engines"]["ch1"]
        print(
            f"  {r['id']} score={r['score']:.2f} n={w['n']} wr={w['wr']:.3f} "
            f"ann={w['annual_pnl_usd']:.2f} mo={w['monthly_pnl_usd']:.2f} "
            f"dd={w['max_period_dd_usd']:.2f} liq={w['liq_rate']:.3f} "
            f"thr={ch1['thr']} hold={ch1['hold']} atr={ch1['atr_min']}-{ch1['atr_max']} "
            f"lev={ch1['lev']} size={ch1['size']} tp={ch1['tp_pct']} sl={ch1['sl_pct']} "
            f"veto={ch1.get('max_funding')}"
        )
    print(f"Wrote {OUT}")
    print(f"Elapsed {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
