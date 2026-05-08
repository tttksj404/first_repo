"""G1308 weak breakout fast-stop search.

G1306/G1307 showed that weak breakout entries lose money when treated like a
normal continuation trade. This script tests a narrower idea: weak breakouts
may still be tradable if failure is recognized quickly.

Weak entries explicitly exclude the strict G4006 signal. Exits are short-hold,
small TP/SL, plus a failure-close exit when price closes back below the entry
breakout reference.
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

from g1300_two_slot_search import BASELINE, resolve_conflicts  # type: ignore
from g1304_multi_family_non_overlap_search import G1995_SPEC, keys_for_anchor, overlap  # type: ignore
from g900_ensemble_discovery import COST_BPS, EQUITY, PERIODS, add_btc_regime, build_period_cache  # type: ignore

OUT = SCRIPTS / "g1308_weak_breakout_fast_stop_results.json"


def finite(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def weak_events(dfs: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    gate = spec["entry"]
    for sym, df in dfs.items():
        close = df["close_price"]
        base_level = df["roll_hi_24"]
        entry_level = base_level * (1.0 + gate["break_bps"] / 10000.0)
        weak_mask = (
            (close > entry_level)
            & (df["ret_24h"] >= gate["min_ret_24h"])
            & (df["vol_ratio"] >= gate["min_vol_ratio"])
            & (df["atr_pct"].between(0, 8))
        )
        strict_mask = (
            (close > base_level * 1.005)
            & (df["ret_24h"] >= 0.10)
            & (df["vol_ratio"] >= 3.0)
            & (df["atr_pct"].between(0, 8))
        )
        mask = weak_mask & ~strict_mask
        if gate.get("close_green"):
            mask &= df["close_price"] > df["open_price"]
        idxs = np.where(mask.fillna(False).to_numpy(dtype=bool))[0]
        for idx in idxs:
            if idx + spec["exit"]["hold"] >= len(df):
                continue
            ref = finite(df.at[idx, "roll_hi_24"]) * (1.0 + spec["exit"]["failure_bps"] / 10000.0)
            level = finite(df.at[idx, "roll_hi_24"]) * (1.0 + gate["break_bps"] / 10000.0)
            strength_bps = (finite(df.at[idx, "close_price"]) / level - 1.0) * 10000.0 if level > 0 else 0.0
            confidence = (
                1.0
                + max(0.0, strength_bps) / 100.0
                + max(0.0, finite(df.at[idx, "ret_24h"]) - gate["min_ret_24h"]) * 8.0
                + min(1.5, max(0.0, finite(df.at[idx, "vol_ratio"], 1.0) - gate["min_vol_ratio"]) * 0.25)
            )
            out.append(
                {
                    "ts": int(df.at[idx, "open_time"]),
                    "sym": sym,
                    "idx": int(idx),
                    "side": "long",
                    "engine": spec["id"],
                    "hold": int(spec["exit"]["hold"]),
                    "lev": float(spec["exit"]["lev"]),
                    "size": float(spec["exit"]["size"]),
                    "confidence": float(confidence),
                    "tp_pct": float(spec["exit"]["tp_pct"]),
                    "sl_pct": float(spec["exit"]["sl_pct"]),
                    "failure_level": float(ref),
                    "strength_bps": round(strength_bps, 4),
                    "ret_24h": round(finite(df.at[idx, "ret_24h"]), 6),
                    "vol_ratio": round(finite(df.at[idx, "vol_ratio"], 1.0), 6),
                }
            )
    return out


def fast_return(df: Any, ev: dict[str, Any]) -> tuple[float, bool, str]:
    idx = int(ev["idx"])
    hold = int(ev["hold"])
    exit_idx = idx + hold
    if exit_idx >= len(df):
        return 0.0, False, "no_path"
    entry = float(df.at[idx, "close_price"])
    if entry <= 0:
        return 0.0, False, "bad_entry"
    path = df.iloc[idx + 1 : exit_idx + 1]
    liq_move = 0.90 / float(ev["lev"])
    adverse = 0.0
    raw: float | None = None
    reason = "time_exit"
    for _, bar in path.iterrows():
        hi = float(bar["high_price"])
        lo = float(bar["low_price"])
        close = float(bar["close_price"])
        adverse = min(adverse, lo / entry - 1.0)
        if lo <= entry * (1.0 - float(ev["sl_pct"])):
            raw = -float(ev["sl_pct"])
            reason = "stop_loss"
            break
        if adverse <= -liq_move:
            return -0.90, True, "liquidation"
        if hi >= entry * (1.0 + float(ev["tp_pct"])):
            raw = float(ev["tp_pct"])
            reason = "take_profit"
            break
        if close < float(ev["failure_level"]):
            raw = close / entry - 1.0
            reason = "failure_close"
            break
    if raw is None:
        raw = float(df.at[exit_idx, "close_price"]) / entry - 1.0
    net_pct = (raw - COST_BPS / 10000.0) * float(ev["lev"])
    return net_pct, False, reason


def simulate(events: list[dict[str, Any]], dfs: dict[str, Any], max_conc: int, days: int, period_name: str) -> dict[str, Any]:
    events = resolve_conflicts(events)
    open_pos: list[tuple[int, str]] = []
    pnl = 0.0
    wins = 0
    liq = 0
    taken = 0
    curve = [0.0]
    keys: list[tuple[str, int, str, str]] = []
    by_reason: dict[str, dict[str, float | int]] = {}

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
        net_pct, liquidated, reason = fast_return(df, ev)
        trade_pnl = EQUITY * float(ev["size"]) * net_pct
        pnl += trade_pnl
        curve.append(pnl)
        taken += 1
        wins += int(trade_pnl > 0)
        liq += int(liquidated)
        row = by_reason.setdefault(reason, {"n": 0, "wins": 0, "pnl_usd": 0.0})
        row["n"] = int(row["n"]) + 1
        row["wins"] = int(row["wins"]) + int(trade_pnl > 0)
        row["pnl_usd"] = float(row["pnl_usd"]) + trade_pnl
        open_pos.append((ts + int(ev["hold"]) * 3600 * 1000, sym))
        keys.append((period_name, ts, sym, ev["side"]))

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
        "by_reason": {
            name: {
                "n": int(row["n"]),
                "wr": round(int(row["wins"]) / max(int(row["n"]), 1), 4),
                "pnl_usd": round(float(row["pnl_usd"]), 2),
            }
            for name, row in sorted(by_reason.items())
        },
        "keys": keys,
    }


def evaluate(spec: dict[str, Any], caches: dict[str, dict[str, Any]], anchors: dict[str, set]) -> dict[str, Any]:
    periods: dict[str, Any] = {}
    keys: set[tuple[str, int, str, str]] = set()
    for period in PERIODS:
        dfs = caches["no_dead"][period.name]
        res = simulate(weak_events(dfs, spec), dfs, 5, period.days, period.name)
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
    all_pos = all(periods[p.name]["pnl_usd"] > 0 for p in PERIODS)
    min_period = min((periods[p.name]["pnl_usd"] for p in PERIODS), default=0.0)
    reasons: dict[str, dict[str, float | int]] = {}
    for res in valid:
        for name, row in res.get("by_reason", {}).items():
            cur = reasons.setdefault(name, {"n": 0, "wins": 0, "pnl_usd": 0.0})
            cur["n"] = int(cur["n"]) + int(row["n"])
            cur["wins"] = int(cur["wins"]) + round(float(row["wr"]) * int(row["n"]))
            cur["pnl_usd"] = float(cur["pnl_usd"]) + float(row["pnl_usd"])
    by_reason = {
        name: {
            "n": int(row["n"]),
            "wr": round(int(row["wins"]) / max(int(row["n"]), 1), 4),
            "pnl_usd": round(float(row["pnl_usd"]), 2),
        }
        for name, row in sorted(reasons.items())
    }
    weighted = {
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
        "g1165_overlap": overlap(keys, anchors["G1165"]),
        "g1995_overlap": overlap(keys, anchors["G1995"]),
        "by_reason": by_reason,
    }
    checks = {
        "n_>=_100": n >= 100,
        "wr_>=_52": wr >= 0.52,
        "annual_>=_60": annual >= 60,
        "all_periods_positive": all_pos,
        "liq_==_0": liq == 0,
        "dd_<=_80": dd <= 80,
        "g1165_j_<=_0.05": float(weighted["g1165_overlap"]["jaccard"]) <= 0.05,
        "g1995_j_<=_0.05": float(weighted["g1995_overlap"]["jaccard"]) <= 0.05,
    }
    score = annual + wr * 40 + min_period * 0.2 - dd * 0.35
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
    specs = []
    idx = 4500
    gates = [
        {"break_bps": -20, "min_ret_24h": 0.05, "min_vol_ratio": 1.8, "label": "near_ret5_vol18"},
        {"break_bps": 0, "min_ret_24h": 0.05, "min_vol_ratio": 2.0, "label": "break_ret5_vol2"},
        {"break_bps": 0, "min_ret_24h": 0.08, "min_vol_ratio": 2.0, "label": "break_ret8_vol2"},
        {"break_bps": 30, "min_ret_24h": 0.08, "min_vol_ratio": 2.5, "label": "break30_ret8_vol25"},
    ]
    exits = [
        {"hold": 4, "lev": 4.0, "size": 0.08, "tp_pct": 0.012, "sl_pct": 0.008, "failure_bps": 0, "label": "h4_tp12_sl8"},
        {"hold": 6, "lev": 4.0, "size": 0.08, "tp_pct": 0.016, "sl_pct": 0.010, "failure_bps": 0, "label": "h6_tp16_sl10"},
        {"hold": 8, "lev": 5.0, "size": 0.08, "tp_pct": 0.020, "sl_pct": 0.012, "failure_bps": 0, "label": "h8_tp20_sl12"},
        {"hold": 12, "lev": 5.0, "size": 0.10, "tp_pct": 0.025, "sl_pct": 0.015, "failure_bps": 0, "label": "h12_tp25_sl15"},
        {"hold": 6, "lev": 4.0, "size": 0.08, "tp_pct": 0.014, "sl_pct": 0.008, "failure_bps": 20, "label": "h6_tp14_sl8_fail20"},
    ]
    for gate, exit_profile in product(gates, exits):
        specs.append(
            {
                "id": f"G{idx}",
                "desc": f"weak breakout fast stop {gate['label']} {exit_profile['label']}",
                "entry": {k: gate[k] for k in ["break_bps", "min_ret_24h", "min_vol_ratio"]},
                "exit": {k: exit_profile[k] for k in ["hold", "lev", "size", "tp_pct", "sl_pct", "failure_bps"]},
                "labels": {"gate": gate["label"], "exit": exit_profile["label"]},
            }
        )
        idx += 1
    return specs


def main() -> None:
    print("G1308 weak breakout fast-stop search starting...")
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
        if res["verdict"] == "PASS" or w["annual_pnl_usd"] >= 30:
            print(
                f"  {res['id']} {spec['labels']} n={w['n']:>4} wr={w['wr']:.3f} "
                f"ann={w['annual_pnl_usd']:>8.2f} dd={w['max_period_dd_usd']:>7.2f} "
                f"minp={w['min_period_pnl_usd']:>7.2f} verdict={res['verdict']}"
            )
    ranked = sorted(results, key=lambda r: (r["verdict"] == "PASS", r["score"]), reverse=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": "Can weak breakout entries be salvaged by very fast stops and failure-close exits?",
        "criteria": {
            "n_min": 100,
            "wr_min": 0.52,
            "annual_min_usd": 60,
            "all_periods_positive": True,
            "liquidations": 0,
            "max_dd_usd": 80,
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
