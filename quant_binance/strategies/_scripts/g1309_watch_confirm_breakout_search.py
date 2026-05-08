"""G1309 watch-confirm breakout strategy search.

Prior rounds showed:
- strict G4006 breakout has real edge;
- weak breakout immediate entries lose money;
- fast stops reduce drawdown but do not rescue weak-entry expectancy.

This round treats weak breakouts as WATCH states. Entry is delayed until a
confirmation bar proves continuation. Specs can run confirmed-only or combine
strict immediate entries with confirmed watch entries.
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
from g900_ensemble_discovery import EQUITY, PERIODS, add_btc_regime, build_period_cache, event_return, make_event  # type: ignore

OUT = SCRIPTS / "g1309_watch_confirm_breakout_results.json"


def finite(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def is_strict(df: Any, idx: int) -> bool:
    return (
        finite(df.at[idx, "close_price"]) > finite(df.at[idx, "roll_hi_24"]) * 1.005
        and finite(df.at[idx, "ret_24h"]) >= 0.10
        and finite(df.at[idx, "vol_ratio"], 1.0) >= 3.0
        and 0 <= finite(df.at[idx, "atr_pct"], 999.0) <= 8
    )


def strict_event(df: Any, idx: int, sym: str, trade: dict[str, Any]) -> dict[str, Any]:
    vr = finite(df.at[idx, "vol_ratio"], 1.0)
    conf = 1.0 + min(1.5, max(0.0, vr - 3.0))
    return make_event(
        df.at[idx, "open_time"],
        sym,
        idx,
        "long",
        "strict_breakout",
        trade["hold"],
        trade["lev"],
        trade["size"],
        conf,
        trade["tp_pct"],
        trade["sl_pct"],
    )


def confirmed_event(
    df: Any,
    watch_idx: int,
    confirm_idx: int,
    sym: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    trade = spec["confirm_trade"]
    watch_level = finite(df.at[watch_idx, "roll_hi_24"]) * (1.0 + spec["watch"]["break_bps"] / 10000.0)
    strict_level = finite(df.at[watch_idx, "roll_hi_24"]) * 1.005
    confirm_close = finite(df.at[confirm_idx, "close_price"])
    strength = (confirm_close / max(strict_level, watch_level, 1e-12) - 1.0) * 10000.0
    vr = finite(df.at[confirm_idx, "vol_ratio"], 1.0)
    ret = finite(df.at[confirm_idx, "ret_24h"])
    conf = 1.0 + max(0.0, strength) / 90.0 + max(0.0, ret - spec["confirm"]["min_ret_24h"]) * 8.0 + max(0.0, vr - spec["confirm"]["min_vol_ratio"]) * 0.25
    ev = make_event(
        df.at[confirm_idx, "open_time"],
        sym,
        confirm_idx,
        "long",
        "watch_confirm",
        trade["hold"],
        trade["lev"],
        trade["size"],
        conf,
        trade["tp_pct"],
        trade["sl_pct"],
    )
    ev["watch_ts"] = int(df.at[watch_idx, "open_time"])
    ev["confirm_lag"] = int(confirm_idx - watch_idx)
    ev["confirm_strength_bps"] = round(strength, 4)
    ev["confirm_ret_24h"] = round(ret, 6)
    ev["confirm_vol_ratio"] = round(vr, 6)
    return ev


def watch_confirm_events(dfs: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    watch = spec["watch"]
    confirm = spec["confirm"]
    strict_trade = spec["strict_trade"]
    for sym, df in dfs.items():
        close = df["close_price"]
        roll = df["roll_hi_24"]
        strict_mask = (
            (close > roll * 1.005)
            & (df["ret_24h"] >= 0.10)
            & (df["vol_ratio"] >= 3.0)
            & (df["atr_pct"].between(0, 8))
        )
        if spec["mode"] in {"strict_only", "strict_plus_confirm"}:
            idxs = np.where(strict_mask.fillna(False).to_numpy(dtype=bool))[0]
            for idx in idxs:
                if idx + strict_trade["hold"] < len(df):
                    out.append(strict_event(df, idx, sym, strict_trade))
        if spec["mode"] == "strict_only":
            continue

        watch_level = roll * (1.0 + watch["break_bps"] / 10000.0)
        watch_mask = (
            (close > watch_level)
            & (df["ret_24h"] >= watch["min_ret_24h"])
            & (df["vol_ratio"] >= watch["min_vol_ratio"])
            & (df["atr_pct"].between(0, 8))
            & ~strict_mask
        )
        if watch.get("close_green"):
            watch_mask &= df["close_price"] > df["open_price"]
        watch_idxs = np.where(watch_mask.fillna(False).to_numpy(dtype=bool))[0]
        for idx in watch_idxs:
            if idx + confirm["max_lag_bars"] + spec["confirm_trade"]["hold"] >= len(df):
                continue
            base = finite(df.at[idx, "roll_hi_24"])
            failure_level = base * (1.0 + confirm["failure_bps"] / 10000.0)
            target_level = base * (1.0 + confirm["confirm_break_bps"] / 10000.0)
            watch_close = finite(df.at[idx, "close_price"])
            failed = False
            for cidx in range(idx + 1, idx + confirm["max_lag_bars"] + 1):
                if finite(df.at[cidx, "close_price"]) < failure_level:
                    failed = True
                    break
                if finite(df.at[cidx, "low_price"]) < failure_level and confirm.get("intra_low_invalidates"):
                    failed = True
                    break
                ok = (
                    finite(df.at[cidx, "close_price"]) > target_level
                    and finite(df.at[cidx, "close_price"]) >= watch_close * (1.0 + confirm["min_follow_bps"] / 10000.0)
                    and finite(df.at[cidx, "ret_24h"]) >= confirm["min_ret_24h"]
                    and finite(df.at[cidx, "vol_ratio"], 1.0) >= confirm["min_vol_ratio"]
                    and 0 <= finite(df.at[cidx, "atr_pct"], 999.0) <= 8
                )
                if confirm.get("confirm_green"):
                    ok = ok and finite(df.at[cidx, "close_price"]) > finite(df.at[cidx, "open_price"])
                if ok and not failed:
                    out.append(confirmed_event(df, idx, cidx, sym, spec))
                    break
    return out


def simulate(events: list[dict[str, Any]], dfs: dict[str, Any], max_conc: int, days: int, period_name: str) -> dict[str, Any]:
    events = resolve_conflicts(events)
    open_pos: list[tuple[int, str]] = []
    pnl = 0.0
    wins = 0
    liq = 0
    taken = 0
    curve = [0.0]
    keys: list[tuple[str, int, str, str]] = []
    by_engine: dict[str, dict[str, float | int]] = {}

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
        trade_pnl = EQUITY * float(ev["size"]) * net_pct
        pnl += trade_pnl
        curve.append(pnl)
        taken += 1
        wins += int(trade_pnl > 0)
        liq += int(liquidated)
        engine = str(ev.get("engine", "unknown"))
        row = by_engine.setdefault(engine, {"n": 0, "wins": 0, "pnl_usd": 0.0})
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
        "by_engine": {
            name: {
                "n": int(row["n"]),
                "wr": round(int(row["wins"]) / max(int(row["n"]), 1), 4),
                "pnl_usd": round(float(row["pnl_usd"]), 2),
            }
            for name, row in sorted(by_engine.items())
        },
        "keys": keys,
    }


def evaluate(spec: dict[str, Any], caches: dict[str, dict[str, Any]], anchors: dict[str, set]) -> dict[str, Any]:
    periods: dict[str, Any] = {}
    keys: set[tuple[str, int, str, str]] = set()
    for period in PERIODS:
        dfs = caches["no_dead"][period.name]
        res = simulate(watch_confirm_events(dfs, spec), dfs, 5, period.days, period.name)
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
    engines: dict[str, dict[str, float | int]] = {}
    for res in valid:
        for name, row in res.get("by_engine", {}).items():
            cur = engines.setdefault(name, {"n": 0, "wins": 0, "pnl_usd": 0.0})
            cur["n"] = int(cur["n"]) + int(row["n"])
            cur["wins"] = int(cur["wins"]) + round(float(row["wr"]) * int(row["n"]))
            cur["pnl_usd"] = float(cur["pnl_usd"]) + float(row["pnl_usd"])
    by_engine = {
        name: {
            "n": int(row["n"]),
            "wr": round(int(row["wins"]) / max(int(row["n"]), 1), 4),
            "pnl_usd": round(float(row["pnl_usd"]), 2),
        }
        for name, row in sorted(engines.items())
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
        "by_engine": by_engine,
    }
    checks = {
        "n_>=_100": n >= 100,
        "wr_>=_55": wr >= 0.55,
        "annual_>=_120": annual >= 120,
        "all_periods_positive": all_pos,
        "liq_==_0": liq == 0,
        "dd_<=_140": dd <= 140,
        "g1165_j_<=_0.05": float(weighted["g1165_overlap"]["jaccard"]) <= 0.05,
        "g1995_j_<=_0.05": float(weighted["g1995_overlap"]["jaccard"]) <= 0.05,
    }
    score = annual + wr * 55 + min_period * 0.2 - dd * 0.18 + min(n, 900) * 0.02
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
    strict_trade = {"hold": 36, "lev": 8.0, "size": 0.20, "tp_pct": 0.06, "sl_pct": 0.08}
    confirm_trades = [
        {"hold": 36, "lev": 8.0, "size": 0.18, "tp_pct": 0.06, "sl_pct": 0.08, "label": "g4006_like"},
        {"hold": 24, "lev": 7.0, "size": 0.16, "tp_pct": 0.05, "sl_pct": 0.065, "label": "mid"},
        {"hold": 18, "lev": 6.0, "size": 0.14, "tp_pct": 0.04, "sl_pct": 0.055, "label": "fast"},
    ]
    watches = [
        {"break_bps": 0, "min_ret_24h": 0.05, "min_vol_ratio": 2.0, "label": "w_break_ret5_vol2"},
        {"break_bps": 0, "min_ret_24h": 0.08, "min_vol_ratio": 2.0, "label": "w_break_ret8_vol2"},
        {"break_bps": 30, "min_ret_24h": 0.08, "min_vol_ratio": 2.5, "label": "w_break30_ret8_vol25"},
        {"break_bps": 0, "min_ret_24h": 0.05, "min_vol_ratio": 2.0, "close_green": True, "label": "w_green_ret5_vol2"},
    ]
    confirms = [
        {"max_lag_bars": 1, "confirm_break_bps": 50, "min_follow_bps": 0, "min_ret_24h": 0.10, "min_vol_ratio": 3.0, "failure_bps": 0, "label": "c1_strict"},
        {"max_lag_bars": 2, "confirm_break_bps": 50, "min_follow_bps": 0, "min_ret_24h": 0.10, "min_vol_ratio": 3.0, "failure_bps": 0, "label": "c2_strict"},
        {"max_lag_bars": 2, "confirm_break_bps": 50, "min_follow_bps": 20, "min_ret_24h": 0.10, "min_vol_ratio": 2.5, "failure_bps": 0, "label": "c2_follow20_vol25"},
        {"max_lag_bars": 3, "confirm_break_bps": 50, "min_follow_bps": 30, "min_ret_24h": 0.10, "min_vol_ratio": 2.5, "failure_bps": 0, "confirm_green": True, "label": "c3_green_follow30"},
        {"max_lag_bars": 2, "confirm_break_bps": 30, "min_follow_bps": 30, "min_ret_24h": 0.08, "min_vol_ratio": 3.0, "failure_bps": 0, "intra_low_invalidates": True, "label": "c2_hold_break30"},
    ]
    modes = ["confirmed_only", "strict_plus_confirm"]
    specs = []
    idx = 4600
    specs.append(
        {
            "id": "G4600_STRICT_BASELINE",
            "desc": "strict G4006 immediate baseline",
            "mode": "strict_only",
            "strict_trade": strict_trade,
            "confirm_trade": strict_trade,
            "watch": watches[0],
            "confirm": confirms[0],
            "labels": {"mode": "strict_only", "watch": "none", "confirm": "none", "exit": "g4006"},
        }
    )
    idx += 1
    for mode, watch, confirm, trade in product(modes, watches, confirms, confirm_trades):
        specs.append(
            {
                "id": f"G{idx}",
                "desc": f"watch-confirm breakout {mode} {watch['label']} {confirm['label']} {trade['label']}",
                "mode": mode,
                "strict_trade": strict_trade,
                "confirm_trade": {k: trade[k] for k in ["hold", "lev", "size", "tp_pct", "sl_pct"]},
                "watch": {k: v for k, v in watch.items() if k != "label"},
                "confirm": {k: v for k, v in confirm.items() if k != "label"},
                "labels": {"mode": mode, "watch": watch["label"], "confirm": confirm["label"], "exit": trade["label"]},
            }
        )
        idx += 1
    return specs


def main() -> None:
    print("G1309 watch-confirm breakout search starting...")
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
        if res["verdict"] == "PASS" or w["annual_pnl_usd"] >= 120:
            print(
                f"  {res['id']} {spec['labels']} n={w['n']:>4} wr={w['wr']:.3f} "
                f"ann={w['annual_pnl_usd']:>8.2f} dd={w['max_period_dd_usd']:>7.2f} "
                f"minp={w['min_period_pnl_usd']:>7.2f} verdict={res['verdict']}"
            )

    ranked = sorted(results, key=lambda r: (r["verdict"] == "PASS", r["score"]), reverse=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": "Can weak breakout WATCH states improve the strict breakout strategy after delayed confirmation?",
        "criteria": {
            "n_min": 100,
            "wr_min": 0.55,
            "annual_min_usd": 120,
            "all_periods_positive": True,
            "liquidations": 0,
            "max_dd_usd": 140,
            "overlap_j_max_each_anchor": 0.05,
        },
        "anchors": {"G1165_keys": len(anchors["G1165"]), "G1995_keys": len(anchors["G1995"])},
        "n_specs": len(results),
        "n_pass": sum(1 for r in results if r["verdict"] == "PASS"),
        "top": ranked[:20],
        "all_results": results,
        "elapsed_sec": round(time.time() - t0, 2),
    }
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
