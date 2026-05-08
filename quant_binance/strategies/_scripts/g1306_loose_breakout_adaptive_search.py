"""G1306 loose breakout + adaptive response search.

G4006 is intentionally selective: 24h high breakout + 10% 24h momentum +
3x volume. This script tests the user's hypothesis that if the signal state is
understood, we can take more entries and adapt size/exit by signal strength.

The search keeps the alpha family non-CH1 and overlap-gated against G1165 and
G1995. It tests a small, interpretable surface rather than a wide random grid.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(r"C:\Users\SSAFY\Desktop\first_repo")
SCRIPTS = ROOT / "quant_binance" / "strategies" / "_scripts"
sys.path.insert(0, str(SCRIPTS))

from g1300_two_slot_search import BASELINE, resolve_conflicts, simulate_with_keys  # type: ignore
from g1304_multi_family_non_overlap_search import G1995_SPEC, keys_for_anchor, overlap  # type: ignore
from g900_ensemble_discovery import (  # type: ignore
    EQUITY,
    PERIODS,
    add_btc_regime,
    build_period_cache,
    ch1_events,
    event_return,
    make_event,
)

OUT = SCRIPTS / "g1306_loose_breakout_adaptive_results.json"


def finite(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def bucket_for(row: Any, spec: dict[str, Any], strength_bps: float) -> tuple[str, dict[str, Any]]:
    ret_24h = finite(row["ret_24h"])
    vol_ratio = finite(row["vol_ratio"], 1.0)
    rules = spec["bucket_rules"]
    if (
        ret_24h >= rules["strong"]["min_ret_24h"]
        and vol_ratio >= rules["strong"]["min_vol_ratio"]
        and strength_bps >= rules["strong"]["min_strength_bps"]
    ):
        return "strong", rules["strong"]["trade"]
    if (
        ret_24h >= rules["standard"]["min_ret_24h"]
        and vol_ratio >= rules["standard"]["min_vol_ratio"]
        and strength_bps >= rules["standard"]["min_strength_bps"]
    ):
        return "standard", rules["standard"]["trade"]
    return "starter", rules["starter"]["trade"]


def adaptive_breakout_events(dfs: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    entry = spec["entry"]
    for sym, df in dfs.items():
        close = df["close_price"]
        breakout_ref = df["roll_hi_24"] * (1.0 + entry["break_bps"] / 10000.0)
        mask = (
            (close > breakout_ref)
            & (df["ret_24h"] >= entry["min_ret_24h"])
            & (df["vol_ratio"] >= entry["min_vol_ratio"])
            & (df["atr_pct"].between(entry["atr_min"], entry["atr_max"]))
        )
        if entry.get("close_green"):
            mask &= df["close_price"] > df["open_price"]
        if entry.get("btc_gate") is not None:
            mask &= df["btc_regime"] >= float(entry["btc_gate"])

        idxs = np.where(mask.fillna(False).to_numpy(dtype=bool))[0]
        for idx in idxs:
            if idx + spec["max_hold"] >= len(df):
                continue
            row = df.iloc[idx]
            level = finite(df.at[idx, "roll_hi_24"]) * (1.0 + entry["break_bps"] / 10000.0)
            strength_bps = (finite(row["close_price"]) / level - 1.0) * 10000.0 if level > 0 else 0.0
            bucket, trade = bucket_for(row, spec, strength_bps)
            vol_ratio = finite(row["vol_ratio"], 1.0)
            ret_24h = finite(row["ret_24h"])
            confidence = (
                1.0
                + max(0.0, strength_bps) / 100.0
                + max(0.0, ret_24h - entry["min_ret_24h"]) * 10.0
                + min(2.0, max(0.0, vol_ratio - entry["min_vol_ratio"]) * 0.35)
            )
            ev = make_event(
                df.at[idx, "open_time"],
                sym,
                idx,
                "long",
                spec["id"],
                trade["hold"],
                trade["lev"],
                trade["size"],
                confidence,
                trade["tp_pct"],
                trade["sl_pct"],
            )
            ev["bucket"] = bucket
            ev["strength_bps"] = round(strength_bps, 4)
            ev["ret_24h"] = round(ret_24h, 6)
            ev["vol_ratio"] = round(vol_ratio, 6)
            out.append(ev)
    return out


def simulate_adaptive(
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
    curve = [0.0]
    keys: list[tuple[str, int, str, str]] = []
    by_bucket: dict[str, dict[str, float | int]] = {}

    for ev in events:
        ts = int(ev["ts"])
        sym = str(ev["sym"])
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
        bucket = str(ev.get("bucket", "unknown"))
        row = by_bucket.setdefault(bucket, {"n": 0, "wins": 0, "pnl_usd": 0.0})
        row["n"] = int(row["n"]) + 1
        row["wins"] = int(row["wins"]) + int(trade_pnl > 0)
        row["pnl_usd"] = float(row["pnl_usd"]) + trade_pnl
        open_pos.append((ts + int(ev["hold"]) * 3600 * 1000, sym))
        keys.append((period_name, ts, sym, ev["side"]))

    arr = np.array(curve, dtype=float)
    peak = np.maximum.accumulate(arr)
    max_dd = float((peak - arr).max()) if len(arr) else 0.0
    bucket_stats = {
        name: {
            "n": int(row["n"]),
            "wr": round(int(row["wins"]) / max(int(row["n"]), 1), 4),
            "pnl_usd": round(float(row["pnl_usd"]), 2),
        }
        for name, row in sorted(by_bucket.items())
    }
    return {
        "n": taken,
        "wr": wins / taken if taken else 0.0,
        "pnl_usd": round(pnl, 2),
        "annual_pnl_usd": round(pnl / days * 365, 2) if days else 0.0,
        "monthly_pnl_usd": round(pnl / days * 30.4, 2) if days else 0.0,
        "liquidations": liq,
        "liq_rate": liq / taken if taken else 0.0,
        "max_dd_usd": round(max_dd, 2),
        "by_side": {"long": {"n": taken, "pnl": round(pnl, 2)}, "short": {"n": 0, "pnl": 0.0}},
        "by_bucket": bucket_stats,
        "keys": keys,
    }


def summarize_periods(periods: dict[str, Any], keys: set[tuple[str, int, str, str]], anchors: dict[str, set]) -> dict[str, Any]:
    valid = [periods[p.name] for p in PERIODS if periods[p.name]["n"] > 0]
    n = sum(r["n"] for r in valid)
    pnl = sum(r["pnl_usd"] for r in valid)
    days = sum(p.days for p in PERIODS if periods[p.name]["n"] > 0)
    wr = sum(r["wr"] * r["n"] for r in valid) / max(n, 1)
    annual = pnl / days * 365 if days else 0.0
    liq = sum(r["liquidations"] for r in valid)
    dd = max((r["max_dd_usd"] for r in valid), default=0.0)
    all_pos = all(periods[p.name]["pnl_usd"] > 0 for p in PERIODS)
    min_period = min((periods[p.name]["pnl_usd"] for p in PERIODS), default=0.0)
    g1165_ov = overlap(keys, anchors["G1165"])
    g1995_ov = overlap(keys, anchors["G1995"])

    buckets: dict[str, dict[str, float | int]] = {}
    for res in valid:
        for name, row in res.get("by_bucket", {}).items():
            cur = buckets.setdefault(name, {"n": 0, "wins": 0, "pnl_usd": 0.0})
            cur["n"] = int(cur["n"]) + int(row["n"])
            cur["wins"] = int(cur["wins"]) + round(float(row["wr"]) * int(row["n"]))
            cur["pnl_usd"] = float(cur["pnl_usd"]) + float(row["pnl_usd"])
    bucket_stats = {
        name: {
            "n": int(row["n"]),
            "wr": round(int(row["wins"]) / max(int(row["n"]), 1), 4),
            "pnl_usd": round(float(row["pnl_usd"]), 2),
        }
        for name, row in sorted(buckets.items())
    }

    return {
        "n": n,
        "wr": round(wr, 4),
        "pnl_usd": round(pnl, 2),
        "annual_pnl_usd": round(annual, 2),
        "monthly_pnl_usd": round(annual / 12, 2),
        "all_periods_positive": all_pos,
        "min_period_pnl_usd": round(min_period, 2),
        "liquidations": liq,
        "liq_rate": round(liq / max(n, 1), 4) if n else 0.0,
        "max_period_dd_usd": round(dd, 2),
        "g1165_overlap": g1165_ov,
        "g1995_overlap": g1995_ov,
        "by_bucket": bucket_stats,
    }


def evaluate(spec: dict[str, Any], caches: dict[str, dict[str, Any]], anchors: dict[str, set]) -> dict[str, Any]:
    periods: dict[str, Any] = {}
    keys: set[tuple[str, int, str, str]] = set()
    for period in PERIODS:
        dfs = caches[spec["univ"]][period.name]
        if spec["id"] == "G4006_BASELINE":
            events = adaptive_breakout_events(dfs, spec)
            converted = []
            for ev in events:
                ev["hold"] = 36
                ev["lev"] = 8.0
                ev["size"] = 0.20
                ev["tp_pct"] = 0.06
                ev["sl_pct"] = 0.08
                ev["bucket"] = "strict"
                converted.append(ev)
            res = simulate_adaptive(converted, dfs, spec["max_conc"], period.days, period.name)
        else:
            events = adaptive_breakout_events(dfs, spec)
            res = simulate_adaptive(events, dfs, spec["max_conc"], period.days, period.name)
        keys.update(map(tuple, res.pop("keys")))
        periods[period.name] = res

    weighted = summarize_periods(periods, keys, anchors)
    checks = {
        "n_>=_100": weighted["n"] >= 100,
        "wr_>=_54": weighted["wr"] >= 0.54,
        "annual_>=_100": weighted["annual_pnl_usd"] >= 100,
        "all_periods_positive": bool(weighted["all_periods_positive"]),
        "liq_==_0": weighted["liquidations"] == 0,
        "dd_<=_160": weighted["max_period_dd_usd"] <= 160,
        "g1165_j_<=_0.05": float(weighted["g1165_overlap"]["jaccard"]) <= 0.05,
        "g1995_j_<=_0.05": float(weighted["g1995_overlap"]["jaccard"]) <= 0.05,
    }
    score = (
        float(weighted["annual_pnl_usd"])
        + float(weighted["wr"]) * 50
        + float(weighted["min_period_pnl_usd"]) * 0.2
        - float(weighted["max_period_dd_usd"]) * 0.20
        + min(float(weighted["n"]), 500.0) * 0.03
    )
    return {
        "id": spec["id"],
        "desc": spec["desc"],
        "spec": spec,
        "periods": periods,
        "weighted": weighted,
        "checks": checks,
        "verdict": "PASS" if all(checks.values()) else "FAIL",
        "score": round(score, 4),
    }


def candidate_specs() -> list[dict[str, Any]]:
    strong = {
        "min_ret_24h": 0.10,
        "min_vol_ratio": 3.0,
        "min_strength_bps": 50.0,
        "trade": {"hold": 36, "lev": 8.0, "size": 0.20, "tp_pct": 0.06, "sl_pct": 0.08},
    }
    profiles = [
        {
            "id": "G4006_BASELINE",
            "desc": "strict G4006 baseline",
            "entry": {"break_bps": 50, "min_ret_24h": 0.10, "min_vol_ratio": 3.0, "atr_min": 0, "atr_max": 8},
            "bucket_rules": {
                "starter": strong,
                "standard": strong,
                "strong": strong,
            },
        },
        {
            "id": "G4401_LOOSE_STATIC",
            "desc": "loose entry, one conservative exit",
            "entry": {"break_bps": 0, "min_ret_24h": 0.05, "min_vol_ratio": 2.0, "atr_min": 0, "atr_max": 8},
            "bucket_rules": {
                "starter": {"trade": {"hold": 18, "lev": 5.0, "size": 0.14, "tp_pct": 0.035, "sl_pct": 0.045}},
                "standard": {"min_ret_24h": 0.08, "min_vol_ratio": 2.5, "min_strength_bps": 20, "trade": {"hold": 18, "lev": 5.0, "size": 0.14, "tp_pct": 0.035, "sl_pct": 0.045}},
                "strong": strong,
            },
        },
        {
            "id": "G4402_ADAPTIVE_5_2",
            "desc": "ret5 vol2 adaptive starter/standard/strong",
            "entry": {"break_bps": 0, "min_ret_24h": 0.05, "min_vol_ratio": 2.0, "atr_min": 0, "atr_max": 8},
            "bucket_rules": {
                "starter": {"trade": {"hold": 12, "lev": 5.0, "size": 0.10, "tp_pct": 0.025, "sl_pct": 0.035}},
                "standard": {"min_ret_24h": 0.08, "min_vol_ratio": 2.5, "min_strength_bps": 20, "trade": {"hold": 24, "lev": 6.0, "size": 0.15, "tp_pct": 0.045, "sl_pct": 0.055}},
                "strong": strong,
            },
        },
        {
            "id": "G4403_ADAPTIVE_5_18",
            "desc": "ret5 vol1.8 adaptive, more entries",
            "entry": {"break_bps": -20, "min_ret_24h": 0.05, "min_vol_ratio": 1.8, "atr_min": 0, "atr_max": 8},
            "bucket_rules": {
                "starter": {"trade": {"hold": 8, "lev": 4.0, "size": 0.08, "tp_pct": 0.018, "sl_pct": 0.028}},
                "standard": {"min_ret_24h": 0.075, "min_vol_ratio": 2.3, "min_strength_bps": 0, "trade": {"hold": 18, "lev": 5.0, "size": 0.13, "tp_pct": 0.035, "sl_pct": 0.045}},
                "strong": strong,
            },
        },
        {
            "id": "G4404_ADAPTIVE_8_2",
            "desc": "ret8 vol2 adaptive, mid selectivity",
            "entry": {"break_bps": 0, "min_ret_24h": 0.08, "min_vol_ratio": 2.0, "atr_min": 0, "atr_max": 8},
            "bucket_rules": {
                "starter": {"trade": {"hold": 12, "lev": 5.0, "size": 0.11, "tp_pct": 0.028, "sl_pct": 0.038}},
                "standard": {"min_ret_24h": 0.10, "min_vol_ratio": 2.5, "min_strength_bps": 20, "trade": {"hold": 24, "lev": 6.0, "size": 0.16, "tp_pct": 0.045, "sl_pct": 0.055}},
                "strong": strong,
            },
        },
        {
            "id": "G4405_GREEN_CONFIRM",
            "desc": "ret5 vol2 adaptive with green close",
            "entry": {"break_bps": 0, "min_ret_24h": 0.05, "min_vol_ratio": 2.0, "atr_min": 0, "atr_max": 8, "close_green": True},
            "bucket_rules": {
                "starter": {"trade": {"hold": 12, "lev": 5.0, "size": 0.10, "tp_pct": 0.025, "sl_pct": 0.035}},
                "standard": {"min_ret_24h": 0.08, "min_vol_ratio": 2.5, "min_strength_bps": 20, "trade": {"hold": 24, "lev": 6.0, "size": 0.15, "tp_pct": 0.045, "sl_pct": 0.055}},
                "strong": strong,
            },
        },
        {
            "id": "G4406_BTC_GATE",
            "desc": "ret5 vol2 adaptive with BTC 72h >= 0",
            "entry": {"break_bps": 0, "min_ret_24h": 0.05, "min_vol_ratio": 2.0, "atr_min": 0, "atr_max": 8, "btc_gate": 0.0},
            "bucket_rules": {
                "starter": {"trade": {"hold": 12, "lev": 5.0, "size": 0.10, "tp_pct": 0.025, "sl_pct": 0.035}},
                "standard": {"min_ret_24h": 0.08, "min_vol_ratio": 2.5, "min_strength_bps": 20, "trade": {"hold": 24, "lev": 6.0, "size": 0.15, "tp_pct": 0.045, "sl_pct": 0.055}},
                "strong": strong,
            },
        },
    ]
    out = []
    for spec in profiles:
        out.append({"univ": "no_dead", "max_conc": 5, "max_hold": 36, **spec})
    return out


def main() -> None:
    print("G1306 loose breakout adaptive search starting...")
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
        print(
            f"  {res['id']} n={w['n']:>4} wr={w['wr']:.3f} "
            f"ann={w['annual_pnl_usd']:>8.2f} dd={w['max_period_dd_usd']:>7.2f} "
            f"minp={w['min_period_pnl_usd']:>7.2f} "
            f"j1165={w['g1165_overlap']['jaccard']:.3f} "
            f"j1995={w['g1995_overlap']['jaccard']:.3f} verdict={res['verdict']}"
        )

    ranked = sorted(results, key=lambda r: (r["verdict"] == "PASS", r["score"]), reverse=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": "Can looser non-CH1 breakout entries stay profitable when response is adapted by signal strength?",
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
        "top": ranked,
        "elapsed_sec": round(time.time() - t0, 2),
    }
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
