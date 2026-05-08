"""G1303 non-CH1 strategy search with overlap gates.

This search deliberately avoids CH1/Mingogogo score inputs. It tests simple
price-action engines that can be evaluated on the same three historical
windows as G1165/G1995:

- breakout: 24h range break with momentum and volume confirmation
- overreaction: 6h dump/pump reversal with volume confirmation
- pullback: 24h trend with 6h counter-move entry

The ranking penalizes overlap against both G1165 and G1995.
"""
from __future__ import annotations

import json
import math
import sys
import time
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(r"C:\Users\SSAFY\Desktop\first_repo")
SCRIPTS = ROOT / "quant_binance" / "strategies" / "_scripts"
sys.path.insert(0, str(SCRIPTS))

from g1300_two_slot_search import BASELINE, simulate_with_keys  # type: ignore
from g900_ensemble_discovery import (  # type: ignore
    COST_BPS,
    EQUITY,
    PERIODS,
    add_btc_regime,
    build_period_cache,
    ch1_events,
    make_event,
)

OUT = SCRIPTS / "g1303_non_ch1_overlap_results.json"

G1995_SPEC = {
    "id": "G1995",
    "desc": "slot_ch1_top10",
    "univ": "top10",
    "max_conc": 5,
    "engines": {
        "ch1": {
            "thr": 80,
            "hold": 36,
            "atr_min": 0,
            "atr_max": 8,
            "lev": 10,
            "size": 0.25,
            "tp_pct": 0.16,
            "sl_pct": 0.075,
        }
    },
}


def breakout_events(dfs: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sym, df in dfs.items():
        close = df["close_price"]
        long_mask = (
            (close > df["roll_hi_24"] * (1.0 + spec["break_bps"] / 10000.0))
            & (df["ret_24h"] >= spec["mom_24h"])
            & (df["vol_ratio"] >= spec["vol_ratio"])
            & (df["atr_pct"].between(spec["atr_min"], spec["atr_max"]))
        )
        short_mask = (
            (close < df["roll_lo_24"] * (1.0 - spec["break_bps"] / 10000.0))
            & (df["ret_24h"] <= -spec["mom_24h"])
            & (df["vol_ratio"] >= spec["vol_ratio"])
            & (df["atr_pct"].between(spec["atr_min"], spec["atr_max"]))
        )
        if spec.get("btc_gate") is not None:
            gate = spec["btc_gate"]
            long_mask &= df["btc_regime"] >= gate
            short_mask &= df["btc_regime"] <= -gate
        for side, mask in [("long", long_mask), ("short", short_mask)]:
            idxs = np.where(mask.fillna(False).to_numpy(dtype=bool))[0]
            for idx in idxs:
                if idx + spec["hold"] >= len(df):
                    continue
                vr = float(df.at[idx, "vol_ratio"])
                conf = 1.0 + min(1.5, max(0.0, vr - spec["vol_ratio"]))
                out.append(
                    make_event(
                        df.at[idx, "open_time"],
                        sym,
                        idx,
                        side,
                        "breakout",
                        spec["hold"],
                        spec["lev"],
                        spec["size"],
                        conf,
                        spec["tp_pct"],
                        spec["sl_pct"],
                    )
                )
    return out


def overreaction_events(dfs: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sym, df in dfs.items():
        common = (
            (df["vol_ratio"] >= spec["vol_ratio"])
            & (df["atr_pct"].between(spec["atr_min"], spec["atr_max"]))
        )
        long_mask = common & (df["ret_6h"] <= -spec["move_6h"])
        short_mask = common & (df["ret_6h"] >= spec["move_6h"])
        if spec.get("trend_filter") == "counter_24h":
            long_mask &= df["ret_24h"] <= -spec["move_24h"]
            short_mask &= df["ret_24h"] >= spec["move_24h"]
        for side, mask in [("long", long_mask), ("short", short_mask)]:
            idxs = np.where(mask.fillna(False).to_numpy(dtype=bool))[0]
            for idx in idxs:
                if idx + spec["hold"] >= len(df):
                    continue
                conf = 1.0 + min(1.5, abs(float(df.at[idx, "ret_6h"])) / spec["move_6h"] - 1.0)
                out.append(
                    make_event(
                        df.at[idx, "open_time"],
                        sym,
                        idx,
                        side,
                        "overreaction",
                        spec["hold"],
                        spec["lev"],
                        spec["size"],
                        conf,
                        spec["tp_pct"],
                        spec["sl_pct"],
                    )
                )
    return out


def pullback_events(dfs: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sym, df in dfs.items():
        common = (
            (df["vol_ratio"] >= spec["vol_ratio"])
            & (df["atr_pct"].between(spec["atr_min"], spec["atr_max"]))
        )
        long_mask = common & (df["ret_24h"] >= spec["trend_24h"]) & (df["ret_6h"] <= -spec["pullback_6h"])
        short_mask = common & (df["ret_24h"] <= -spec["trend_24h"]) & (df["ret_6h"] >= spec["pullback_6h"])
        for side, mask in [("long", long_mask), ("short", short_mask)]:
            idxs = np.where(mask.fillna(False).to_numpy(dtype=bool))[0]
            for idx in idxs:
                if idx + spec["hold"] >= len(df):
                    continue
                conf = 1.0 + min(1.5, abs(float(df.at[idx, "ret_24h"])) / spec["trend_24h"] - 1.0)
                out.append(
                    make_event(
                        df.at[idx, "open_time"],
                        sym,
                        idx,
                        side,
                        "pullback",
                        spec["hold"],
                        spec["lev"],
                        spec["size"],
                        conf,
                        spec["tp_pct"],
                        spec["sl_pct"],
                    )
                )
    return out


def events_for_spec(dfs: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    engine = spec["engine"]
    params = spec["params"]
    if engine == "breakout":
        return breakout_events(dfs, params)
    if engine == "overreaction":
        return overreaction_events(dfs, params)
    if engine == "pullback":
        return pullback_events(dfs, params)
    raise ValueError(engine)


def keys_for_ch1_anchor(spec: dict[str, Any], caches: dict[str, dict[str, Any]]) -> set[tuple[str, int, str, str]]:
    keys: set[tuple[str, int, str, str]] = set()
    for period in PERIODS:
        dfs = caches[spec["univ"]][period.name]
        events = ch1_events(dfs, spec["engines"]["ch1"])
        res = simulate_with_keys(events, dfs, spec["max_conc"], period.days, period.name)
        keys.update(map(tuple, res["keys"]))
    return keys


def overlap(keys: set[tuple[str, int, str, str]], other: set[tuple[str, int, str, str]]) -> dict[str, float | int]:
    inter = len(keys & other)
    return {
        "n": inter,
        "candidate_cover": round(inter / max(len(keys), 1), 4),
        "other_cover": round(inter / max(len(other), 1), 4),
        "jaccard": round(inter / max(len(keys | other), 1), 4),
    }


def evaluate_spec(
    spec: dict[str, Any],
    caches: dict[str, dict[str, Any]],
    base_keys: set[tuple[str, int, str, str]],
    g1995_keys: set[tuple[str, int, str, str]],
) -> dict[str, Any]:
    period_results: dict[str, Any] = {}
    all_keys: set[tuple[str, int, str, str]] = set()
    for period in PERIODS:
        dfs = caches[spec["univ"]][period.name]
        events = events_for_spec(dfs, spec)
        res = simulate_with_keys(events, dfs, spec["max_conc"], period.days, period.name)
        all_keys.update(map(tuple, res.pop("keys")))
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
    base_ov = overlap(all_keys, base_keys)
    g1995_ov = overlap(all_keys, g1995_keys)
    long_n = sum(r["by_side"]["long"]["n"] for r in valid)
    short_n = sum(r["by_side"]["short"]["n"] for r in valid)

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
        "long_n": long_n,
        "short_n": short_n,
        "g1165_overlap": base_ov,
        "g1995_overlap": g1995_ov,
    }
    checks = {
        "n_>=_30": total_n >= 30,
        "wr_>=_60": wr >= 0.60,
        "annual_pnl_>=_120": annual >= 120,
        "all_periods_positive": all_pos,
        "liq_==_0": liq == 0,
        "max_period_dd_<=_100": max_dd <= 100,
        "g1165_j_<=_0.30": float(base_ov["jaccard"]) <= 0.30,
        "g1995_j_<=_0.30": float(g1995_ov["jaccard"]) <= 0.30,
        "both_sides": long_n > 0 and short_n > 0,
    }
    score = (
        annual
        + wr * 60
        + min_period_pnl * 0.2
        - max_dd * 0.25
        - (float(base_ov["jaccard"]) + float(g1995_ov["jaccard"])) * 75
    )
    return {
        "id": spec["id"],
        "desc": spec["desc"],
        "engine": spec["engine"],
        "spec": spec,
        "periods": period_results,
        "weighted": weighted,
        "non_ch1_score": round(score, 4),
        "decision": {"checks": checks, "verdict": "PASS" if all(checks.values()) else "FAIL"},
    }


def candidate_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    idx = 3500
    universes = ["no_dead", "top10"]
    profiles = [
        {"lev": 5, "size": 0.30},
        {"lev": 6, "size": 0.25},
        {"lev": 8, "size": 0.20},
    ]

    for univ, hold, break_bps, mom, vol, atr_max, profile, tp, sl, btc_gate in product(
        universes,
        [12, 24],
        [50],
        [0.10],
        [3.0],
        [8],
        profiles[1:2],
        [0.08],
        [0.06],
        [None],
    ):
        specs.append(
            {
                "id": f"G{idx}",
                "desc": "non_ch1_breakout",
                "univ": univ,
                "max_conc": 5,
                "engine": "breakout",
                "params": {
                    "hold": hold,
                    "break_bps": break_bps,
                    "mom_24h": mom,
                    "vol_ratio": vol,
                    "atr_min": 0,
                    "atr_max": atr_max,
                    "lev": profile["lev"],
                    "size": profile["size"],
                    "tp_pct": tp,
                    "sl_pct": sl,
                    "btc_gate": btc_gate,
                },
            }
        )
        idx += 1

    for univ, hold, move_6h, move_24h, vol, atr_max, profile, tp, sl, trend_filter in product(
        universes,
        [3, 6],
        [0.06, 0.08],
        [0.08],
        [2.0, 3.0],
        [8],
        profiles[:2],
        [0.05],
        [0.04],
        [None, "counter_24h"],
    ):
        specs.append(
            {
                "id": f"G{idx}",
                "desc": "non_ch1_overreaction",
                "univ": univ,
                "max_conc": 5,
                "engine": "overreaction",
                "params": {
                    "hold": hold,
                    "move_6h": move_6h,
                    "move_24h": move_24h,
                    "trend_filter": trend_filter,
                    "vol_ratio": vol,
                    "atr_min": 0,
                    "atr_max": atr_max,
                    "lev": profile["lev"],
                    "size": profile["size"],
                    "tp_pct": tp,
                    "sl_pct": sl,
                },
            }
        )
        idx += 1

    for univ, hold, trend, pullback, vol, atr_max, profile, tp, sl in product(
        universes,
        [6, 12],
        [0.12],
        [0.04],
        [2.0, 3.0],
        [8],
        profiles[:2],
        [0.05],
        [0.04],
    ):
        specs.append(
            {
                "id": f"G{idx}",
                "desc": "non_ch1_pullback",
                "univ": univ,
                "max_conc": 5,
                "engine": "pullback",
                "params": {
                    "hold": hold,
                    "trend_24h": trend,
                    "pullback_6h": pullback,
                    "vol_ratio": vol,
                    "atr_min": 0,
                    "atr_max": atr_max,
                    "lev": profile["lev"],
                    "size": profile["size"],
                    "tp_pct": tp,
                    "sl_pct": sl,
                },
            }
        )
        idx += 1
    return specs


def main() -> None:
    print("G1303 non-CH1 overlap search starting...")
    t0 = time.time()
    caches: dict[str, dict[str, dict[str, Any]]] = {}
    for univ in ["no_dead", "top10"]:
        caches[univ] = {}
        for period in PERIODS:
            dfs = build_period_cache(period, univ)
            add_btc_regime(dfs)
            caches[univ][period.name] = dfs
            print(f"  loaded {period.name}/{univ}: {len(dfs)} symbols")

    base_keys = keys_for_ch1_anchor(BASELINE, caches)
    g1995_keys = keys_for_ch1_anchor(G1995_SPEC, caches)
    print(f"  anchor keys: G1165={len(base_keys)} G1995={len(g1995_keys)}")

    specs = candidate_specs()
    results = []
    for i, spec in enumerate(specs, 1):
        res = evaluate_spec(spec, caches, base_keys, g1995_keys)
        results.append(res)
        if i % 1000 == 0 or res["decision"]["verdict"] == "PASS":
            w = res["weighted"]
            print(
                f"{i:05d}/{len(specs)} {res['id']} {res['engine']} "
                f"n={w['n']:>4} wr={w['wr']:.3f} ann={w['annual_pnl_usd']:>8.2f} "
                f"dd={w['max_period_dd_usd']:>7.2f} "
                f"j1165={w['g1165_overlap']['jaccard']:.3f} "
                f"j1995={w['g1995_overlap']['jaccard']:.3f} "
                f"{res['decision']['verdict']}"
            )

    passers = [r for r in results if r["decision"]["verdict"] == "PASS"]
    ranked = sorted(
        passers,
        key=lambda r: (r["non_ch1_score"], r["weighted"]["annual_pnl_usd"]),
        reverse=True,
    )
    near = sorted(
        results,
        key=lambda r: (
            r["non_ch1_score"],
            r["weighted"]["annual_pnl_usd"],
            -r["weighted"]["max_period_dd_usd"],
        ),
        reverse=True,
    )
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cost_bps": COST_BPS,
        "equity": EQUITY,
        "anchors": {
            "G1165_keys": len(base_keys),
            "G1995_keys": len(g1995_keys),
        },
        "n_specs": len(specs),
        "n_pass": len(passers),
        "decision_criteria": {
            "n_min": 30,
            "wr_min": 0.60,
            "annual_pnl_min_usd": 120,
            "all_periods_positive": True,
            "liquidations": 0,
            "max_period_dd_usd": 100,
            "g1165_j_max": 0.30,
            "g1995_j_max": 0.30,
            "both_sides": True,
        },
        "top_non_ch1_replacements": ranked[:30],
        "top_near_misses": near[:40],
        "results": results,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nPASS {len(passers)}/{len(specs)}")
    print("Top candidates:")
    for r in (ranked or near)[:15]:
        w = r["weighted"]
        p = r["spec"]["params"]
        fails = [k for k, v in r["decision"]["checks"].items() if not v]
        print(
            f"  {r['id']} {r['engine']} {r['spec']['univ']} verdict={r['decision']['verdict']} "
            f"score={r['non_ch1_score']:.2f} n={w['n']} wr={w['wr']:.3f} "
            f"ann={w['annual_pnl_usd']:.2f} dd={w['max_period_dd_usd']:.2f} "
            f"long/short={w['long_n']}/{w['short_n']} "
            f"j1165={w['g1165_overlap']['jaccard']:.3f} "
            f"j1995={w['g1995_overlap']['jaccard']:.3f} "
            f"hold={p['hold']} lev={p['lev']} size={p['size']} tp={p['tp_pct']} sl={p['sl_pct']} "
            f"fails={','.join(fails) if fails else '-'}"
        )
    print(f"Wrote {OUT}")
    print(f"Elapsed {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
