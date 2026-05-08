"""G1304 multi-family non-overlap strategy search.

This is a scouting pass for a second paper slot that should *not* reuse the
CH1/Mingogogo entry family.  It compares several independent alpha families
under the same three-period, path-safe simulator and records overlap against
the current CH1 anchors:

- G1165: no-dead CH1 path-safe paper service
- G1995: proposed top10 CH1 slot

Families tested:
- breakout_long / breakout_short: volume-confirmed 24h range break
- climax_reversal_long / climax_reversal_short: 6h overreaction fade
- trend_pullback_long / trend_pullback_short: trend continuation after pullback
- funding_fade: funding extreme fade with 24h move confirmation

The output intentionally separates strict pass from watchlist candidates.
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

OUT = SCRIPTS / "g1304_multi_family_non_overlap_results.json"

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


def finite(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def event(
    df: Any,
    idx: int,
    sym: str,
    side: str,
    engine: str,
    spec: dict[str, Any],
    confidence: float,
) -> dict[str, Any]:
    return make_event(
        df.at[idx, "open_time"],
        sym,
        idx,
        side,
        engine,
        spec["hold"],
        spec["lev"],
        spec["size"],
        confidence,
        spec["tp_pct"],
        spec["sl_pct"],
    )


def range_break_events(dfs: dict[str, Any], spec: dict[str, Any], side: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sym, df in dfs.items():
        common = (
            (df["vol_ratio"] >= spec["vol_ratio"])
            & (df["atr_pct"].between(spec["atr_min"], spec["atr_max"]))
        )
        if side == "long":
            mask = (
                common
                & (df["close_price"] > df["roll_hi_24"] * (1.0 + spec["break_bps"] / 10000.0))
                & (df["ret_24h"] >= spec["mom_24h"])
            )
        else:
            mask = (
                common
                & (df["close_price"] < df["roll_lo_24"] * (1.0 - spec["break_bps"] / 10000.0))
                & (df["ret_24h"] <= -spec["mom_24h"])
            )
        if spec.get("btc_gate") is not None:
            gate = spec["btc_gate"]
            mask &= df["btc_regime"] >= gate if side == "long" else df["btc_regime"] <= -gate
        idxs = np.where(mask.fillna(False).to_numpy(dtype=bool))[0]
        for idx in idxs:
            if idx + spec["hold"] >= len(df):
                continue
            vr = finite(df.at[idx, "vol_ratio"], 1.0)
            conf = 1.0 + min(1.5, max(0.0, vr - spec["vol_ratio"]))
            out.append(event(df, idx, sym, side, spec["engine"], spec, conf))
    return out


def climax_reversal_events(dfs: dict[str, Any], spec: dict[str, Any], side: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sym, df in dfs.items():
        common = (
            (df["vol_ratio"] >= spec["vol_ratio"])
            & (df["atr_pct"].between(spec["atr_min"], spec["atr_max"]))
        )
        if side == "long":
            mask = common & (df["ret_6h"] <= -spec["move_6h"])
            if spec.get("confirm_24h"):
                mask &= df["ret_24h"] <= -spec["move_24h"]
        else:
            mask = common & (df["ret_6h"] >= spec["move_6h"])
            if spec.get("confirm_24h"):
                mask &= df["ret_24h"] >= spec["move_24h"]
        idxs = np.where(mask.fillna(False).to_numpy(dtype=bool))[0]
        for idx in idxs:
            if idx + spec["hold"] >= len(df):
                continue
            move = abs(finite(df.at[idx, "ret_6h"], 0.0))
            conf = 1.0 + min(1.5, max(0.0, move / spec["move_6h"] - 1.0))
            out.append(event(df, idx, sym, side, spec["engine"], spec, conf))
    return out


def trend_pullback_events(dfs: dict[str, Any], spec: dict[str, Any], side: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sym, df in dfs.items():
        common = (
            (df["vol_ratio"] >= spec["vol_ratio"])
            & (df["atr_pct"].between(spec["atr_min"], spec["atr_max"]))
        )
        if side == "long":
            mask = common & (df["ret_24h"] >= spec["trend_24h"]) & (df["ret_6h"] <= -spec["pullback_6h"])
        else:
            mask = common & (df["ret_24h"] <= -spec["trend_24h"]) & (df["ret_6h"] >= spec["pullback_6h"])
        idxs = np.where(mask.fillna(False).to_numpy(dtype=bool))[0]
        for idx in idxs:
            if idx + spec["hold"] >= len(df):
                continue
            trend = abs(finite(df.at[idx, "ret_24h"], 0.0))
            conf = 1.0 + min(1.5, max(0.0, trend / spec["trend_24h"] - 1.0))
            out.append(event(df, idx, sym, side, spec["engine"], spec, conf))
    return out


def funding_fade_events(dfs: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sym, df in dfs.items():
        common = df["atr_pct"].between(spec["atr_min"], spec["atr_max"])
        short_mask = common & (df["funding_rate"] >= spec["pos_rate"]) & (df["ret_24h"] >= spec["move_24h"])
        long_mask = common & (df["funding_rate"] <= -spec["pos_rate"]) & (df["ret_24h"] <= -spec["move_24h"])
        for side, mask in [("short", short_mask), ("long", long_mask)]:
            idxs = np.where(mask.fillna(False).to_numpy(dtype=bool))[0]
            for idx in idxs:
                if idx + spec["hold"] >= len(df):
                    continue
                rate = abs(finite(df.at[idx, "funding_rate"], 0.0))
                conf = 1.0 + min(1.5, rate / max(spec["pos_rate"], 1e-9) - 1.0)
                out.append(event(df, idx, sym, side, "funding_fade", spec, conf))
    return out


def events_for_spec(dfs: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    family = spec["family"]
    params = spec["params"]
    if family == "breakout_long":
        return range_break_events(dfs, params, "long")
    if family == "breakout_short":
        return range_break_events(dfs, params, "short")
    if family == "climax_reversal_long":
        return climax_reversal_events(dfs, params, "long")
    if family == "climax_reversal_short":
        return climax_reversal_events(dfs, params, "short")
    if family == "trend_pullback_long":
        return trend_pullback_events(dfs, params, "long")
    if family == "trend_pullback_short":
        return trend_pullback_events(dfs, params, "short")
    if family == "funding_fade":
        return funding_fade_events(dfs, params)
    raise ValueError(f"unknown family: {family}")


def keys_for_anchor(spec: dict[str, Any], caches: dict[str, dict[str, Any]]) -> set[tuple[str, int, str, str]]:
    keys: set[tuple[str, int, str, str]] = set()
    for period in PERIODS:
        dfs = caches[spec["univ"]][period.name]
        res = simulate_with_keys(ch1_events(dfs, spec["engines"]["ch1"]), dfs, spec["max_conc"], period.days, period.name)
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


def evaluate(
    spec: dict[str, Any],
    caches: dict[str, dict[str, Any]],
    base_keys: set[tuple[str, int, str, str]],
    g1995_keys: set[tuple[str, int, str, str]],
) -> dict[str, Any]:
    periods: dict[str, Any] = {}
    keys: set[tuple[str, int, str, str]] = set()
    for period in PERIODS:
        dfs = caches[spec["univ"]][period.name]
        events = events_for_spec(dfs, spec)
        res = simulate_with_keys(events, dfs, spec["max_conc"], period.days, period.name)
        keys.update(map(tuple, res.pop("keys")))
        periods[period.name] = res

    valid = [periods[p.name] for p in PERIODS if periods[p.name]["n"] > 0]
    n = sum(r["n"] for r in valid)
    pnl = sum(r["pnl_usd"] for r in valid)
    days = sum(p.days for p in PERIODS if periods[p.name]["n"] > 0)
    wr = sum(r["wr"] * r["n"] for r in valid) / max(n, 1)
    annual = pnl / days * 365 if days else 0.0
    liq = sum(r["liquidations"] for r in valid)
    dd = max((r["max_dd_usd"] for r in valid), default=0.0)
    min_period_pnl = min((periods[p.name]["pnl_usd"] for p in PERIODS), default=0.0)
    all_pos = all(periods[p.name]["pnl_usd"] > 0 for p in PERIODS)
    long_n = sum(r["by_side"]["long"]["n"] for r in valid)
    short_n = sum(r["by_side"]["short"]["n"] for r in valid)
    bov = overlap(keys, base_keys)
    gov = overlap(keys, g1995_keys)
    weighted = {
        "n": n,
        "wr": round(wr, 4),
        "pnl_usd": round(pnl, 2),
        "annual_pnl_usd": round(annual, 2),
        "monthly_pnl_usd": round(annual / 12, 2),
        "all_periods_positive": all_pos,
        "min_period_pnl_usd": round(min_period_pnl, 2),
        "liquidations": liq,
        "liq_rate": round(liq / max(n, 1), 4) if n else 0.0,
        "max_period_dd_usd": round(dd, 2),
        "long_n": long_n,
        "short_n": short_n,
        "g1165_overlap": bov,
        "g1995_overlap": gov,
    }
    strict_checks = {
        "n_>=_30": n >= 30,
        "wr_>=_60": wr >= 0.60,
        "annual_pnl_>=_120": annual >= 120,
        "all_periods_positive": all_pos,
        "liq_==_0": liq == 0,
        "max_dd_<=_100": dd <= 100,
        "g1165_j_<=_0.05": float(bov["jaccard"]) <= 0.05,
        "g1995_j_<=_0.05": float(gov["jaccard"]) <= 0.05,
    }
    watch_checks = {
        "n_>=_30": n >= 30,
        "wr_>=_55": wr >= 0.55,
        "annual_pnl_>=_80": annual >= 80,
        "all_periods_positive": all_pos,
        "liq_==_0": liq == 0,
        "max_dd_<=_150": dd <= 150,
        "g1165_j_<=_0.05": float(bov["jaccard"]) <= 0.05,
        "g1995_j_<=_0.05": float(gov["jaccard"]) <= 0.05,
    }
    score = (
        annual
        + wr * 60
        + min_period_pnl * 0.2
        - dd * 0.25
        - (float(bov["jaccard"]) + float(gov["jaccard"])) * 100
    )
    return {
        "id": spec["id"],
        "family": spec["family"],
        "spec": spec,
        "periods": periods,
        "weighted": weighted,
        "multi_family_score": round(score, 4),
        "strict": {"checks": strict_checks, "verdict": "PASS" if all(strict_checks.values()) else "FAIL"},
        "watchlist": {"checks": watch_checks, "verdict": "PASS" if all(watch_checks.values()) else "FAIL"},
    }


def candidate_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    idx = 4000
    universes = ["no_dead", "top10"]
    profiles = [
        {"lev": 5, "size": 0.30},
        {"lev": 6, "size": 0.25},
        {"lev": 8, "size": 0.20},
        {"lev": 10, "size": 0.15},
    ]

    for family, univ, hold, break_bps, mom, vol, profile, tp, sl in product(
        ["breakout_long", "breakout_short"],
        universes,
        [24, 36],
        [50],
        [0.10],
        [3.0],
        [profiles[0], profiles[2]],
        [0.06, 0.10],
        [0.08],
    ):
        specs.append(
            {
                "id": f"G{idx}",
                "family": family,
                "univ": univ,
                "max_conc": 5,
                "params": {
                    "engine": family,
                    "hold": hold,
                    "break_bps": break_bps,
                    "mom_24h": mom,
                    "vol_ratio": vol,
                    "atr_min": 0,
                    "atr_max": 8,
                    "lev": profile["lev"],
                    "size": profile["size"],
                    "tp_pct": tp,
                    "sl_pct": sl,
                    "btc_gate": None,
                },
            }
        )
        idx += 1

    for family, univ, hold, move, vol, confirm, profile, tp, sl in product(
        ["climax_reversal_long", "climax_reversal_short"],
        universes,
        [3, 6],
        [0.06, 0.08],
        [2.0, 3.0],
        [False, True],
        profiles[:2],
        [0.03, 0.05],
        [0.04],
    ):
        specs.append(
            {
                "id": f"G{idx}",
                "family": family,
                "univ": univ,
                "max_conc": 5,
                "params": {
                    "engine": family,
                    "hold": hold,
                    "move_6h": move,
                    "move_24h": 0.08,
                    "confirm_24h": confirm,
                    "vol_ratio": vol,
                    "atr_min": 0,
                    "atr_max": 8,
                    "lev": profile["lev"],
                    "size": profile["size"],
                    "tp_pct": tp,
                    "sl_pct": sl,
                },
            }
        )
        idx += 1

    for family, univ, hold, trend, pullback, vol, profile, tp, sl in product(
        ["trend_pullback_long", "trend_pullback_short"],
        universes,
        [6, 12],
        [0.12],
        [0.04],
        [2.0, 3.0],
        profiles[:2],
        [0.05],
        [0.04],
    ):
        specs.append(
            {
                "id": f"G{idx}",
                "family": family,
                "univ": univ,
                "max_conc": 5,
                "params": {
                    "engine": family,
                    "hold": hold,
                    "trend_24h": trend,
                    "pullback_6h": pullback,
                    "vol_ratio": vol,
                    "atr_min": 0,
                    "atr_max": 8,
                    "lev": profile["lev"],
                    "size": profile["size"],
                    "tp_pct": tp,
                    "sl_pct": sl,
                },
            }
        )
        idx += 1

    for univ, hold, rate, move, profile, tp, sl in product(
        universes,
        [12, 24],
        [0.0005, 0.0008],
        [0.05],
        profiles[:1],
        [0.05],
        [0.04],
    ):
        specs.append(
            {
                "id": f"G{idx}",
                "family": "funding_fade",
                "univ": univ,
                "max_conc": 5,
                "params": {
                    "engine": "funding_fade",
                    "hold": hold,
                    "pos_rate": rate,
                    "move_24h": move,
                    "atr_min": 0,
                    "atr_max": 8,
                    "lev": profile["lev"],
                    "size": profile["size"],
                    "tp_pct": tp,
                    "sl_pct": sl,
                },
            }
        )
        idx += 1
    return specs


def family_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for family in sorted({r["family"] for r in results}):
        rows = [r for r in results if r["family"] == family]
        best = max(rows, key=lambda r: (r["multi_family_score"], r["weighted"]["annual_pnl_usd"]))
        out[family] = {
            "n_specs": len(rows),
            "strict_pass": sum(1 for r in rows if r["strict"]["verdict"] == "PASS"),
            "watch_pass": sum(1 for r in rows if r["watchlist"]["verdict"] == "PASS"),
            "best_id": best["id"],
            "best_score": best["multi_family_score"],
            "best_weighted": best["weighted"],
            "best_spec": best["spec"],
            "best_strict_fails": [k for k, v in best["strict"]["checks"].items() if not v],
            "best_watch_fails": [k for k, v in best["watchlist"]["checks"].items() if not v],
        }
    return out


def main() -> None:
    print("G1304 multi-family non-overlap search starting...")
    t0 = time.time()
    caches: dict[str, dict[str, Any]] = {}
    for univ in ["no_dead", "top10"]:
        caches[univ] = {}
        for period in PERIODS:
            dfs = build_period_cache(period, univ)
            add_btc_regime(dfs)
            caches[univ][period.name] = dfs
            print(f"  loaded {period.name}/{univ}: {len(dfs)} symbols")

    base_keys = keys_for_anchor(BASELINE, caches)
    g1995_keys = keys_for_anchor(G1995_SPEC, caches)
    print(f"  anchors: G1165={len(base_keys)} G1995={len(g1995_keys)}")

    specs = candidate_specs()
    print(f"  specs: {len(specs)}")
    results = []
    for i, spec in enumerate(specs, 1):
        res = evaluate(spec, caches, base_keys, g1995_keys)
        results.append(res)
        if i % 250 == 0 or res["strict"]["verdict"] == "PASS" or res["watchlist"]["verdict"] == "PASS":
            w = res["weighted"]
            print(
                f"{i:04d}/{len(specs)} {res['id']} {res['family']} "
                f"n={w['n']:>4} wr={w['wr']:.3f} ann={w['annual_pnl_usd']:>8.2f} "
                f"dd={w['max_period_dd_usd']:>7.2f} "
                f"j1165={w['g1165_overlap']['jaccard']:.3f} "
                f"j1995={w['g1995_overlap']['jaccard']:.3f} "
                f"strict={res['strict']['verdict']} watch={res['watchlist']['verdict']}"
            )

    strict_pass = [r for r in results if r["strict"]["verdict"] == "PASS"]
    watch_pass = [r for r in results if r["watchlist"]["verdict"] == "PASS"]
    ranked_strict = sorted(strict_pass, key=lambda r: (r["multi_family_score"], r["weighted"]["annual_pnl_usd"]), reverse=True)
    ranked_watch = sorted(watch_pass, key=lambda r: (r["multi_family_score"], r["weighted"]["annual_pnl_usd"]), reverse=True)
    ranked_all = sorted(results, key=lambda r: (r["multi_family_score"], r["weighted"]["annual_pnl_usd"]), reverse=True)

    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cost_bps": COST_BPS,
        "equity": EQUITY,
        "anchors": {"G1165_keys": len(base_keys), "G1995_keys": len(g1995_keys)},
        "n_specs": len(specs),
        "n_strict_pass": len(strict_pass),
        "n_watch_pass": len(watch_pass),
        "strict_criteria": {
            "n_min": 30,
            "wr_min": 0.60,
            "annual_pnl_min_usd": 120,
            "all_periods_positive": True,
            "liquidations": 0,
            "max_dd_usd": 100,
            "overlap_j_max_each_anchor": 0.05,
        },
        "watchlist_criteria": {
            "n_min": 30,
            "wr_min": 0.55,
            "annual_pnl_min_usd": 80,
            "all_periods_positive": True,
            "liquidations": 0,
            "max_dd_usd": 150,
            "overlap_j_max_each_anchor": 0.05,
        },
        "family_summary": family_summary(results),
        "top_strict": ranked_strict[:30],
        "top_watchlist": ranked_watch[:30],
        "top_overall": ranked_all[:50],
        "results": results,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nSTRICT PASS {len(strict_pass)}/{len(specs)}")
    print(f"WATCH PASS {len(watch_pass)}/{len(specs)}")
    for r in (ranked_strict or ranked_watch or ranked_all)[:20]:
        w = r["weighted"]
        fails = [k for k, v in r["strict"]["checks"].items() if not v]
        print(
            f"  {r['id']} {r['family']} {r['spec']['univ']} "
            f"strict={r['strict']['verdict']} watch={r['watchlist']['verdict']} "
            f"score={r['multi_family_score']:.2f} n={w['n']} wr={w['wr']:.3f} "
            f"ann={w['annual_pnl_usd']:.2f} dd={w['max_period_dd_usd']:.2f} "
            f"long/short={w['long_n']}/{w['short_n']} "
            f"j1165={w['g1165_overlap']['jaccard']:.3f} "
            f"j1995={w['g1995_overlap']['jaccard']:.3f} "
            f"strict_fails={','.join(fails) if fails else '-'}"
        )
    print(f"Wrote {OUT}")
    print(f"Elapsed {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
