"""Search for a genuinely high-frequency, high-WR full-window alpha sleeve.

The strict G7826 check showed the existing cadence sleeves top out around
58-59% WR. This pass looks for a new price-data family with:

- >= 8-15 trades/month
- >= 65% WR, ideally near 69%
- positive PnL in every full validation window
- zero liquidations

This is research-only. It intentionally explores interpretable event families
instead of stacking more of the same breakout variants.
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

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "quant_binance" / "strategies" / "_scripts"
sys.path.insert(0, str(SCRIPTS))

from g1300_two_slot_search import resolve_conflicts  # type: ignore
from g900_ensemble_discovery import EQUITY, PERIODS, add_btc_regime, build_period_cache, event_return, make_event  # type: ignore

OUT = SCRIPTS / "g7827_high_wr_alpha_search_results.json"
TOTAL_DAYS = sum(period.days for period in PERIODS)


def finite(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def add_features(dfs: dict[str, Any]) -> None:
    for sym, df in list(dfs.items()):
        df["ret_1h"] = df["close_price"].pct_change(1)
        df["ret_3h"] = df["close_price"].pct_change(3)
        df["ret_12h"] = df["close_price"].pct_change(12)
        df["range_pct"] = (df["high_price"] / df["low_price"] - 1.0).replace([np.inf, -np.inf], np.nan)
        df["close_pos"] = ((df["close_price"] - df["low_price"]) / (df["high_price"] - df["low_price"])).replace(
            [np.inf, -np.inf], np.nan
        )
        df["body_pct"] = (df["close_price"] / df["open_price"] - 1.0).replace([np.inf, -np.inf], np.nan)


def event(df: Any, idx: int, sym: str, side: str, engine: str, spec: dict[str, Any], confidence: float) -> dict[str, Any]:
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


def trend_pullback_events(dfs: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    side = spec["side"]
    for sym, df in dfs.items():
        common = (df["vol_ratio"] >= spec["min_vol"]) & (df["vol_ratio"] <= spec["max_vol"]) & df["atr_pct"].between(
            spec["atr_min"], spec["atr_max"]
        )
        if side == "long":
            mask = common & (df["ret_24h"] >= spec["trend_24h"]) & (df[spec["pull_col"]] <= -spec["pullback"])
            if spec.get("recover_green"):
                mask &= df["close_price"] > df["open_price"]
            if spec.get("btc_gate") is not None:
                mask &= df["btc_regime"] >= spec["btc_gate"]
        else:
            mask = common & (df["ret_24h"] <= -spec["trend_24h"]) & (df[spec["pull_col"]] >= spec["pullback"])
            if spec.get("recover_green"):
                mask &= df["close_price"] < df["open_price"]
            if spec.get("btc_gate") is not None:
                mask &= df["btc_regime"] <= -spec["btc_gate"]
        idxs = np.where(mask.fillna(False).to_numpy(dtype=bool))[0]
        for idx in idxs:
            if idx + spec["hold"] >= len(df):
                continue
            conf = 1.0 + abs(finite(df.at[idx, "ret_24h"])) * 5.0 + abs(finite(df.at[idx, spec["pull_col"]])) * 8.0
            out.append(event(df, idx, sym, side, "trend_pullback_high_wr", spec, conf))
    return out


def climax_reclaim_events(dfs: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    side = spec["side"]
    for sym, df in dfs.items():
        common = (df["vol_ratio"] >= spec["min_vol"]) & df["atr_pct"].between(spec["atr_min"], spec["atr_max"])
        if side == "long":
            mask = common & (df[spec["move_col"]] <= -spec["move"]) & (df["close_pos"] >= spec["close_pos"])
            if spec.get("confirm_1h"):
                mask &= df["ret_1h"] >= 0
            if spec.get("btc_gate") is not None:
                mask &= df["btc_regime"] >= -spec["btc_gate"]
        else:
            mask = common & (df[spec["move_col"]] >= spec["move"]) & (df["close_pos"] <= 1.0 - spec["close_pos"])
            if spec.get("confirm_1h"):
                mask &= df["ret_1h"] <= 0
            if spec.get("btc_gate") is not None:
                mask &= df["btc_regime"] <= spec["btc_gate"]
        idxs = np.where(mask.fillna(False).to_numpy(dtype=bool))[0]
        for idx in idxs:
            if idx + spec["hold"] >= len(df):
                continue
            conf = 1.0 + abs(finite(df.at[idx, spec["move_col"]])) * 8.0 + finite(df.at[idx, "vol_ratio"], 1.0) * 0.1
            out.append(event(df, idx, sym, side, "climax_reclaim_high_wr", spec, conf))
    return out


def range_reversion_events(dfs: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    side = spec["side"]
    for sym, df in dfs.items():
        common = (
            (df["range_pct"] >= spec["range_min"])
            & (df["vol_ratio"] >= spec["min_vol"])
            & (df["vol_ratio"] <= spec["max_vol"])
            & df["atr_pct"].between(spec["atr_min"], spec["atr_max"])
        )
        if side == "long":
            mask = common & (df["ret_3h"] <= -spec["move_3h"]) & (df["close_pos"] >= spec["close_pos"])
        else:
            mask = common & (df["ret_3h"] >= spec["move_3h"]) & (df["close_pos"] <= 1.0 - spec["close_pos"])
        idxs = np.where(mask.fillna(False).to_numpy(dtype=bool))[0]
        for idx in idxs:
            if idx + spec["hold"] >= len(df):
                continue
            conf = 1.0 + finite(df.at[idx, "range_pct"]) * 10.0
            out.append(event(df, idx, sym, side, "range_reversion_high_wr", spec, conf))
    return out


def events_for_spec(dfs: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    if spec["family"] == "trend_pullback":
        return trend_pullback_events(dfs, spec)
    if spec["family"] == "climax_reclaim":
        return climax_reclaim_events(dfs, spec)
    if spec["family"] == "range_reversion":
        return range_reversion_events(dfs, spec)
    raise ValueError(spec["family"])


def simulate(events: list[dict[str, Any]], dfs: dict[str, Any], max_conc: int, days: int, period_name: str) -> dict[str, Any]:
    events = resolve_conflicts(events)
    open_pos: list[tuple[int, str]] = []
    pnl = 0.0
    wins = 0
    liq = 0
    taken = 0
    curve = [0.0]
    keys: list[tuple[str, int, str, str]] = []
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
        net_pct, liquidated, _ = event_return(df, ev["idx"], ev["side"], ev["hold"], ev["lev"], ev.get("tp_pct"), ev.get("sl_pct"))
        trade_pnl = EQUITY * ev["size"] * net_pct
        pnl += trade_pnl
        curve.append(pnl)
        taken += 1
        wins += int(trade_pnl > 0)
        liq += int(liquidated)
        open_pos.append((ts + int(ev["hold"]) * 3600 * 1000, sym))
        keys.append((period_name, ts, sym, ev["side"]))
    arr = np.array(curve, dtype=float)
    peak = np.maximum.accumulate(arr)
    dd = peak - arr
    return {
        "n": taken,
        "wr": wins / taken if taken else 0.0,
        "pnl_usd": round(pnl, 2),
        "annual_pnl_usd": round(pnl / days * 365, 2) if days else 0.0,
        "monthly_pnl_usd": round(pnl / days * 30.4, 2) if days else 0.0,
        "liquidations": liq,
        "liq_rate": liq / max(taken, 1),
        "max_dd_usd": round(float(dd.max()) if len(dd) else 0.0, 2),
        "keys": keys,
    }


def summarize(periods: dict[str, Any], keys: set[tuple[str, int, str, str]]) -> dict[str, Any]:
    valid = [periods[p.name] for p in PERIODS if periods[p.name]["n"] > 0]
    n = sum(r["n"] for r in valid)
    pnl = sum(r["pnl_usd"] for r in valid)
    wr = sum(r["wr"] * r["n"] for r in valid) / max(n, 1)
    liq = sum(r["liquidations"] for r in valid)
    maxdd = max((r["max_dd_usd"] for r in valid), default=0.0)
    minp = min((periods[p.name]["pnl_usd"] for p in PERIODS), default=0.0)
    return {
        "n": n,
        "unique_n": len(keys),
        "trades_per_month": round(len(keys) / TOTAL_DAYS * 30.4, 2),
        "wr": round(wr, 4),
        "pnl_usd": round(pnl, 2),
        "annual_pnl_usd": round(pnl / TOTAL_DAYS * 365, 2),
        "liquidations": liq,
        "liq_rate": round(liq / max(n, 1), 4),
        "max_period_dd_usd": round(maxdd, 2),
        "min_period_pnl_usd": round(minp, 2),
        "all_periods_positive": all(periods[p.name]["pnl_usd"] > 0 for p in PERIODS),
    }


def candidate_specs() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    idx = 782700
    exits = [
        {"hold": 9, "tp_pct": 0.018, "sl_pct": 0.045, "lev": 5.0, "size": 0.10},
        {"hold": 12, "tp_pct": 0.020, "sl_pct": 0.050, "lev": 5.0, "size": 0.10},
    ]
    for side, trend, pull, pull_col, min_vol, max_vol, atr_max, recover, btc_gate, ex in product(
        ["long", "short"],
        [0.08, 0.10],
        [0.025, 0.035],
        ["ret_3h", "ret_6h"],
        [1.2, 1.6],
        [3.0, 5.0],
        [6, 8, 12],
        [True],
        [None, 0.0],
        exits,
    ):
        out.append(
            {
                "id": f"G{idx}",
                "family": "trend_pullback",
                "side": side,
                "trend_24h": trend,
                "pullback": pull,
                "pull_col": pull_col,
                "min_vol": min_vol,
                "max_vol": max_vol,
                "atr_min": 0,
                "atr_max": atr_max,
                "recover_green": recover,
                "btc_gate": btc_gate,
                "max_conc": 5,
                **ex,
            }
        )
        idx += 1
    for side, move, move_col, min_vol, close_pos, atr_max, confirm, btc_gate, ex in product(
        ["long", "short"],
        [0.06, 0.08, 0.10],
        ["ret_3h", "ret_6h"],
        [1.8, 2.5],
        [0.65, 0.75],
        [6, 8],
        [True],
        [None, 0.0],
        exits,
    ):
        out.append(
            {
                "id": f"G{idx}",
                "family": "climax_reclaim",
                "side": side,
                "move": move,
                "move_col": move_col,
                "min_vol": min_vol,
                "atr_min": 0,
                "atr_max": atr_max,
                "close_pos": close_pos,
                "confirm_1h": confirm,
                "btc_gate": btc_gate,
                "max_conc": 5,
                **ex,
            }
        )
        idx += 1
    return out


def evaluate(spec: dict[str, Any], caches: dict[str, dict[str, Any]]) -> dict[str, Any]:
    periods: dict[str, Any] = {}
    keys: set[tuple[str, int, str, str]] = set()
    for period in PERIODS:
        dfs = caches[period.name]
        res = simulate(events_for_spec(dfs, spec), dfs, spec["max_conc"], period.days, period.name)
        keys.update(map(tuple, res.pop("keys")))
        periods[period.name] = res
    w = summarize(periods, keys)
    checks = {
        "tpm_gte_8": w["trades_per_month"] >= 8.0,
        "tpm_gte_12": w["trades_per_month"] >= 12.0,
        "wr_gte_65": w["wr"] >= 0.65,
        "wr_gte_69": w["wr"] >= 0.69,
        "pnl_positive": w["pnl_usd"] > 0,
        "annual_gte_50": w["annual_pnl_usd"] >= 50,
        "liq_zero": w["liquidations"] == 0,
        "all_periods_positive": w["all_periods_positive"],
        "dd_lte_120": w["max_period_dd_usd"] <= 120,
    }
    score = (
        w["wr"] * 400
        + min(w["trades_per_month"], 20) * 30
        + w["annual_pnl_usd"] * 0.4
        + w["min_period_pnl_usd"] * 0.2
        - w["max_period_dd_usd"] * 0.5
    )
    return {
        "id": spec["id"],
        "family": spec["family"],
        "side": spec["side"],
        "spec": spec,
        "periods": periods,
        "weighted": w,
        "checks": checks,
        "strict_high_wr_pass": all(
            checks[k]
            for k in ["tpm_gte_8", "wr_gte_65", "pnl_positive", "liq_zero", "all_periods_positive", "dd_lte_120"]
        ),
        "dream_pass": all(
            checks[k]
            for k in ["tpm_gte_12", "wr_gte_69", "pnl_positive", "liq_zero", "all_periods_positive", "dd_lte_120"]
        ),
        "score": round(score, 4),
    }


def main() -> None:
    print("G7827 high-WR alpha search starting...", flush=True)
    t0 = time.time()
    caches: dict[str, dict[str, Any]] = {}
    for period in PERIODS:
        dfs = build_period_cache(period, "no_dead")
        add_btc_regime(dfs)
        add_features(dfs)
        caches[period.name] = dfs
        print(f"  loaded {period.name}: {len(dfs)} symbols", flush=True)

    specs = candidate_specs()
    print(f"  specs={len(specs)}", flush=True)
    results: list[dict[str, Any]] = []
    for i, spec in enumerate(specs, 1):
        res = evaluate(spec, caches)
        results.append(res)
        if i % 100 == 0:
            print(f"  done {i}/{len(specs)} pass65={sum(r['strict_high_wr_pass'] for r in results)}", flush=True)

    top = sorted(results, key=lambda r: (r["strict_high_wr_pass"], r["dream_pass"], r["score"]), reverse=True)
    by_wr_high_cadence = sorted(
        [r for r in results if r["weighted"]["trades_per_month"] >= 8 and r["weighted"]["pnl_usd"] > 0],
        key=lambda r: (r["weighted"]["wr"], r["weighted"]["trades_per_month"], r["weighted"]["annual_pnl_usd"]),
        reverse=True,
    )
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": "Is there a full-window high-frequency high-WR price alpha to repair G7822's quality-frequency conflict?",
        "n_specs": len(results),
        "n_strict_high_wr_pass": sum(r["strict_high_wr_pass"] for r in results),
        "n_dream_pass": sum(r["dream_pass"] for r in results),
        "criteria": {
            "strict_high_wr": "tpm>=8, wr>=65%, pnl>0, liq=0, all periods positive, dd<=120",
            "dream": "tpm>=12, wr>=69%, pnl>0, liq=0, all periods positive, dd<=120",
        },
        "top": top[:80],
        "top_by_wr_high_cadence": by_wr_high_cadence[:80],
        "elapsed_sec": round(time.time() - t0, 2),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)
    if top:
        best = top[0]
        print(json.dumps({"id": best["id"], "weighted": best["weighted"], "checks": best["checks"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
